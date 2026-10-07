"""Calidad de llamadas (services/calidad.py).

Evaluar y ver los resultados de todos: quien supervisa (`supervision:ver`).
Cada persona ve las evaluaciones de sus propias llamadas en `/mias`.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import CallLog, CriterioCalidad, EvaluacionLlamada, User
from app.services import calidad, reportes

router = APIRouter(prefix="/api/calidad", tags=["calidad"])

_SUPERVISA = Depends(requiere(permissions.SUPERVISION_VER))
_PROPIAS = Depends(requiere(permissions.LLAMADAS_VER_PROPIAS))
MIN_SEGUNDOS = 10  # menos que esto no es una conversación que evaluar


class CriterioIn(BaseModel):
    id: int | None = None
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=500)
    peso: int = Field(default=1, ge=1, le=10)
    activo: bool = True


class EvaluacionIn(BaseModel):
    puntajes: dict[str, int]
    comentario: str | None = Field(default=None, max_length=2000)
    origen: str = Field(default="manual", pattern="^(manual|ia)$")


def _empresa(session) -> int:
    tid = tenant_de_sesion(session)
    if tid is None:
        raise HTTPException(status_code=403, detail="La calidad de llamadas es de cada empresa")
    return tid


async def _hacer(corrutina):
    try:
        return await corrutina
    except calidad.ErrorCalidad as exc:
        raise HTTPException(status_code=exc.codigo, detail=exc.mensaje) from None


def _criterio_out(c: CriterioCalidad) -> dict:
    return {"id": c.id, "nombre": c.nombre, "descripcion": c.descripcion, "peso": c.peso, "activo": c.activo}


def _evaluacion_out(e: EvaluacionLlamada, nombres: dict[int, str]) -> dict:
    return {
        "id": e.id, "call_id": e.call_id, "agente_id": e.agente_id, "agente": nombres.get(e.agente_id or 0),
        "evaluador": nombres.get(e.evaluador_id or 0), "puntajes": e.puntajes, "total_pct": e.total_pct,
        "comentario": e.comentario, "origen": e.origen, "revisada": e.revisada, "created_at": e.created_at,
    }


async def _nombres(session, ids) -> dict[int, str]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    filas = (await session.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
    return {i: n or u for i, n, u in filas}


async def _llamada(session, call_id: int) -> CallLog:
    call = await traer_propio(session, CallLog, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    return call


# --- Criterios -----------------------------------------------------------------------------


@router.get("/criterios")
async def listar_criterios(session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    lista = await calidad.criterios(session, _empresa(session), solo_activos=False)
    await session.commit()
    return [_criterio_out(c) for c in lista]


@router.put("/criterios")
async def guardar_criterios(datos: list[CriterioIn], session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    """Reemplaza la lista: los que no vienen se desactivan (no se borran: las
    evaluaciones viejas los siguen nombrando)."""
    if not 1 <= len(datos) <= 30:
        raise HTTPException(status_code=422, detail="Entre 1 y 30 criterios")
    tid = _empresa(session)
    existentes = {c.id: c for c in await calidad.criterios(session, tid, solo_activos=False)}
    vistos = set()
    for orden, d in enumerate(datos):
        c = existentes.get(d.id) if d.id else None
        if c is None:
            c = CriterioCalidad(tenant_id=tid)
            session.add(c)
        c.nombre, c.descripcion, c.peso, c.activo, c.orden = d.nombre.strip(), d.descripcion, d.peso, d.activo, orden
        if c.id:
            vistos.add(c.id)
    for cid, c in existentes.items():
        if cid not in vistos:
            c.activo = False
    await session.commit()
    return [_criterio_out(c) for c in await calidad.criterios(session, tid, solo_activos=False)]


# --- Llamadas para evaluar -------------------------------------------------------------------


@router.get("/llamadas")
async def llamadas(
    desde: date, hasta: date, sin_evaluar: bool = False, limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA,
):
    """Llamadas contestadas y grabadas del rango, con su evaluación si tiene."""
    try:
        r = reportes.rango_utc(desde, hasta)
    except reportes.RangoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    ultima = (
        select(EvaluacionLlamada.call_id, func.max(EvaluacionLlamada.id).label("eid"))
        .group_by(EvaluacionLlamada.call_id)
        .subquery()
    )
    query = (
        select(CallLog, EvaluacionLlamada)
        .outerjoin(ultima, ultima.c.call_id == CallLog.id)
        .outerjoin(EvaluacionLlamada, EvaluacionLlamada.id == ultima.c.eid)
        .where(
            CallLog.started_at >= r.ini, CallLog.started_at < r.fin, CallLog.recording_path.is_not(None),
            CallLog.billsec >= MIN_SEGUNDOS,
        )
        .order_by(desc(CallLog.started_at))
        .limit(limit)
    )
    if sin_evaluar:
        query = query.where(EvaluacionLlamada.id.is_(None))
    filas = (await session.execute(query)).all()
    nombres = await _nombres(session, [c.agente_id for c, _ in filas] + [e.agente_id for _, e in filas if e])
    return [
        {
            "id": c.id, "started_at": c.started_at, "direccion": c.direction, "de": c.caller_number, "a": c.callee_number,
            "billsec": c.billsec, "cola": c.cola, "agente": nombres.get(c.agente_id or 0) or c.cola_agente,
            "evaluacion": None if e is None else {"id": e.id, "total_pct": e.total_pct, "origen": e.origen, "revisada": e.revisada},
        }
        for c, e in filas
    ]


@router.get("/llamadas/{call_id}")
async def detalle(call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    call = await _llamada(session, call_id)
    evals = list(
        (await session.execute(
            select(EvaluacionLlamada).where(EvaluacionLlamada.call_id == call.id).order_by(desc(EvaluacionLlamada.id))
        )).scalars()
    )
    agente_id = await calidad.agente_de(session, call)
    nombres = await _nombres(session, [agente_id] + [e.evaluador_id for e in evals] + [e.agente_id for e in evals])
    return {
        "id": call.id, "started_at": call.started_at, "de": call.caller_number, "a": call.callee_number,
        "billsec": call.billsec, "cola": call.cola, "agente_id": agente_id, "agente": nombres.get(agente_id or 0),
        "resumen": call.summary, "transcripcion": call.transcripcion,
        "evaluaciones": [_evaluacion_out(e, nombres) for e in evals],
    }


@router.post("/llamadas/{call_id}/transcribir")
async def transcribir(call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    call = await _llamada(session, call_id)
    return {"transcripcion": await _hacer(calidad.transcripcion(session, call))}


@router.post("/llamadas/{call_id}/sugerencia")
async def sugerencia(call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    """Lo que propone la IA. No se guarda: se revisa y se guarda con POST /evaluaciones."""
    call = await _llamada(session, call_id)
    lista = await calidad.criterios(session, _empresa(session))
    return await _hacer(calidad.sugerir(session, call, lista))


@router.post("/llamadas/{call_id}/evaluaciones", status_code=201)
async def evaluar(
    call_id: int, datos: EvaluacionIn, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA
):
    call = await _llamada(session, call_id)
    lista = await calidad.criterios(session, _empresa(session))
    puntajes = await _hacer(_validar(datos.puntajes, lista))
    # Una evaluación hecha por una persona reemplaza la propuesta automática sin revisar.
    await session.execute(
        delete(EvaluacionLlamada).where(EvaluacionLlamada.call_id == call.id, EvaluacionLlamada.revisada.is_(False))
    )
    e = EvaluacionLlamada(
        tenant_id=call.tenant_id, call_id=call.id, agente_id=await calidad.agente_de(session, call),
        evaluador_id=usuario.id, puntajes=puntajes, total_pct=calidad.total(puntajes, lista),
        comentario=(datos.comentario or "").strip() or None, origen=datos.origen, created_at=datetime.utcnow(),
    )
    session.add(e)
    await session.commit()
    return _evaluacion_out(e, await _nombres(session, [e.agente_id, e.evaluador_id]))


async def _validar(puntajes, lista):
    return calidad.validar_puntajes(puntajes, lista)


# --- Resultados ---------------------------------------------------------------------------------


@router.get("/resumen")
async def resumen(desde: date, hasta: date, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    """Promedio por persona y por criterio en el rango."""
    try:
        r = reportes.rango_utc(desde, hasta)
    except reportes.RangoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    evals = list(
        (await session.execute(
            select(EvaluacionLlamada).where(EvaluacionLlamada.created_at >= r.ini, EvaluacionLlamada.created_at < r.fin,
                                            EvaluacionLlamada.revisada.is_(True))
        )).scalars()
    )
    lista = await calidad.criterios(session, _empresa(session), solo_activos=False)
    nombres = await _nombres(session, [e.agente_id for e in evals])
    por_agente: dict[int | None, list[EvaluacionLlamada]] = {}
    for e in evals:
        por_agente.setdefault(e.agente_id, []).append(e)

    def promedios(grupo: list[EvaluacionLlamada]) -> dict:
        por_criterio = {}
        for c in lista:
            valores = [e.puntajes.get(str(c.id)) for e in grupo if str(c.id) in (e.puntajes or {})]
            if valores:
                por_criterio[str(c.id)] = round(100.0 * sum(valores) / (calidad.PUNTAJE_MAX * len(valores)), 1)
        return {
            "evaluaciones": len(grupo),
            "promedio_pct": round(sum(e.total_pct for e in grupo) / len(grupo), 1) if grupo else None,
            "por_criterio": por_criterio,
        }

    filas = [
        {"agente_id": aid, "agente": nombres.get(aid or 0) or "Sin identificar", **promedios(g)}
        for aid, g in por_agente.items()
    ]
    filas.sort(key=lambda f: (f["promedio_pct"] is None, -(f["promedio_pct"] or 0)))
    await session.commit()
    return {"criterios": [_criterio_out(c) for c in lista], "filas": filas, "total": promedios(evals)}


@router.get("/mias")
async def mias(session: AsyncSession = Depends(get_session), usuario: User = _PROPIAS):
    """Las evaluaciones de las llamadas propias (para que cada persona vea su
    retroalimentación)."""
    evals = list(
        (await session.execute(
            select(EvaluacionLlamada).where(EvaluacionLlamada.agente_id == usuario.id, EvaluacionLlamada.revisada.is_(True))
            .order_by(desc(EvaluacionLlamada.created_at)).limit(50)
        )).scalars()
    )
    lista = await calidad.criterios(session, _empresa(session), solo_activos=False) if usuario.tenant_id else []
    await session.commit()
    nombres = await _nombres(session, [e.evaluador_id for e in evals] + [usuario.id])
    return {"criterios": [_criterio_out(c) for c in lista], "evaluaciones": [_evaluacion_out(e, nombres) for e in evals]}


# --- Calidad automática (services/calidad_auto.py) -----------------------------------------------


class AutomaticoIn(BaseModel):
    por_agente: int = Field(ge=0, le=20)
    tope: int = Field(ge=1, le=500)


class RevisarIn(BaseModel):
    puntajes: dict[str, int] | None = None
    comentario: str | None = Field(default=None, max_length=2000)


@router.get("/automatico")
async def ver_automatico(session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    from app.services.ajustes import ajustes_de

    a = await ajustes_de(session, _empresa(session))
    por_revisar = (
        await session.execute(select(func.count()).select_from(EvaluacionLlamada).where(EvaluacionLlamada.revisada.is_(False)))
    ).scalar_one()
    return {
        "por_agente": getattr(a, "calidad_auto_por_agente", 0) or 0,
        "tope": getattr(a, "calidad_auto_tope", 20) or 20,
        "ultima": getattr(a, "calidad_auto_ultima", None),
        "por_revisar": por_revisar,
        "tiene_ia": bool(a and a.ai_llm_api_key and a.deepgram_api_key),
    }


@router.put("/automatico")
async def guardar_automatico(datos: AutomaticoIn, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    from app.services.ajustes import ajustes_de

    a = await ajustes_de(session, _empresa(session))
    if a is None:
        raise HTTPException(status_code=404, detail="La empresa no tiene ajustes")
    a.calidad_auto_por_agente, a.calidad_auto_tope = datos.por_agente, datos.tope
    await session.commit()
    return {"por_agente": datos.por_agente, "tope": datos.tope}


@router.get("/por-revisar")
async def por_revisar(session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    """Lo que propuso la IA y nadie confirmó todavía."""
    filas = (
        await session.execute(
            select(EvaluacionLlamada, CallLog)
            .join(CallLog, CallLog.id == EvaluacionLlamada.call_id)
            .where(EvaluacionLlamada.revisada.is_(False))
            .order_by(EvaluacionLlamada.created_at.desc())
            .limit(200)
        )
    ).all()
    nombres = await _nombres(session, [e.agente_id for e, _ in filas])
    return [
        {**_evaluacion_out(e, nombres), "llamada": {"started_at": c.started_at, "de": c.caller_number,
                                                     "a": c.callee_number, "billsec": c.billsec, "cola": c.cola}}
        for e, c in filas
    ]


async def _propuesta(session, evaluacion_id: int) -> EvaluacionLlamada:
    e = await traer_propio(session, EvaluacionLlamada, evaluacion_id)
    if e is None or e.revisada:
        raise HTTPException(status_code=404, detail="Evaluación por revisar no encontrada")
    return e


@router.post("/evaluaciones/{evaluacion_id}/revisar")
async def revisar(evaluacion_id: int, datos: RevisarIn, session: AsyncSession = Depends(get_session),
                  usuario: User = _SUPERVISA):
    """Confirmar la propuesta de la IA, o corregirla (puntajes y comentario)."""
    e = await _propuesta(session, evaluacion_id)
    if datos.puntajes is not None:
        lista = await calidad.criterios(session, _empresa(session))
        e.puntajes = await _hacer(_validar(datos.puntajes, lista))
        e.total_pct = calidad.total(e.puntajes, lista)
    if datos.comentario is not None:
        e.comentario = datos.comentario.strip() or None
    e.revisada, e.evaluador_id = True, usuario.id
    await session.commit()
    return _evaluacion_out(e, await _nombres(session, [e.agente_id, e.evaluador_id]))


@router.delete("/evaluaciones/{evaluacion_id}", status_code=204)
async def descartar(evaluacion_id: int, session: AsyncSession = Depends(get_session), usuario: User = _SUPERVISA):
    """Descartar una propuesta de la IA (no se confirma ni cuenta)."""
    e = await _propuesta(session, evaluacion_id)
    await session.delete(e)
    await session.commit()


@router.get("/tendencia")
async def tendencia(semanas: int = Query(default=8, ge=2, le=26), session: AsyncSession = Depends(get_session),
                    usuario: User = _SUPERVISA):
    """Promedio semanal por persona (evaluaciones confirmadas), de la más vieja a la última."""
    desde = datetime.utcnow() - timedelta(weeks=semanas)
    semana = func.date_trunc("week", EvaluacionLlamada.created_at)
    filas = (
        await session.execute(
            select(EvaluacionLlamada.agente_id, semana, func.avg(EvaluacionLlamada.total_pct), func.count())
            .where(EvaluacionLlamada.created_at >= desde, EvaluacionLlamada.revisada.is_(True))
            .group_by(EvaluacionLlamada.agente_id, semana)
            .order_by(semana)
        )
    ).all()
    nombres = await _nombres(session, [a for a, *_ in filas])
    por: dict = {}
    for aid, inicio, prom, n in filas:
        por.setdefault(aid, []).append({"semana": inicio.date().isoformat(), "promedio_pct": round(float(prom), 1), "evaluaciones": n})
    return [
        {"agente_id": aid, "agente": nombres.get(aid or 0) or "Sin identificar", "semanas": puntos,
         "cambio": round(puntos[-1]["promedio_pct"] - puntos[-2]["promedio_pct"], 1) if len(puntos) >= 2 else None}
        for aid, puntos in por.items()
    ]
