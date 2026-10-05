"""Controles de emergencia de TODA la plataforma. Solo el rol plataforma.

Hoy: el interruptor global de llamadas salientes. Se lee en cada llamada
(el dialplan se pide por llamada, y el clic-para-llamar y el marcador
consultan la política antes de cada originate), así que cortar es
inmediato para toda llamada nueva.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import usuario_actual
from app.core.database import get_admin_session
from app.api.security import _auditoria_salida, _filtrar_auditoria
from app.models import AuditLog, PlatformState, SecurityAlert, Tenant, User
from app.api.consumo import csv_respuesta
from app.services import consumo, esl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plataforma", tags=["plataforma"])


class SalientesGlobal(BaseModel):
    outbound_blocked: bool


async def _estado(session: AsyncSession) -> PlatformState:
    estado = await session.get(PlatformState, 1)
    if estado is None:
        estado = PlatformState(id=1, outbound_blocked=False)
        session.add(estado)
        await session.commit()
    return estado


@router.get("/salientes", response_model=SalientesGlobal)
async def ver_salientes(session: AsyncSession = Depends(get_admin_session)):
    return SalientesGlobal(outbound_blocked=bool((await _estado(session)).outbound_blocked))


@router.put("/salientes", response_model=SalientesGlobal)
async def cambiar_salientes(
    payload: SalientesGlobal,
    session: AsyncSession = Depends(get_admin_session),
    usuario: User = Depends(usuario_actual),
):
    estado = await _estado(session)
    estado.outbound_blocked = payload.outbound_blocked
    await session.commit()
    logger.warning(
        "Salientes de TODA la plataforma %s por %s",
        "CORTADAS" if payload.outbound_blocked else "reactivadas",
        usuario.username,
    )
    # El dialplan se sirve en vivo; reloadxml purga lo que FreeSWITCH tenga
    # cacheado. Si no responde, la política igual se aplica en la próxima
    # consulta.
    try:
        await esl.reloadxml()
    except Exception:
        pass
    return SalientesGlobal(outbound_blocked=payload.outbound_blocked)


@router.post("/salientes/colgar")
async def colgar_salientes_de_todas(
    session: AsyncSession = Depends(get_admin_session), usuario: User = Depends(usuario_actual)
):
    """Cuelga las salientes EN CURSO de todas las empresas (ver
    services/emergencia.py). Cortar las salientes frena las nuevas; esto,
    las que ya están hablando."""
    from app.services import emergencia

    ids = (await session.execute(select(Tenant.id))).scalars().all()
    try:
        hechas = await emergencia.colgar_salientes(ids)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no respondió; no se pudo colgar: {exc}")
    logger.warning("Salientes en curso de TODA la plataforma colgadas por %s", usuario.username)
    return {"empresas": len(hechas)}


class DestinosBloqueados(BaseModel):
    # "53, 7, +2346": códigos de país o prefijos internacionales (sin el +).
    prefijos: str
    # Solo en la respuesta: los fijos, que no se pueden quitar.
    fijos: list[str] = []


@router.get("/destinos-bloqueados", response_model=DestinosBloqueados)
async def ver_destinos_bloqueados(session: AsyncSession = Depends(get_admin_session)):
    from app.services import salientes

    return DestinosBloqueados(prefijos=(await _estado(session)).blocked_prefixes or "", fijos=list(salientes.CODIGOS_BLOQUEADOS))


@router.put("/destinos-bloqueados", response_model=DestinosBloqueados)
async def cambiar_destinos_bloqueados(
    payload: DestinosBloqueados,
    session: AsyncSession = Depends(get_admin_session),
    usuario: User = Depends(usuario_actual),
):
    """Bloquea un país o prefijo internacional para TODAS las empresas, aunque
    una lo tenga entre sus países permitidos. Aplica en el dialplan, el clic
    para llamar y las campañas desde la próxima llamada."""
    from app.services import salientes

    try:
        prefijos = salientes.prefijos_desde_texto(payload.prefijos)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    estado = await _estado(session)
    estado.blocked_prefixes = ",".join(prefijos)
    await session.commit()
    logger.warning("Destinos bloqueados para toda la plataforma: %s (por %s)", estado.blocked_prefixes or "ninguno", usuario.username)
    try:
        await esl.reloadxml()
    except Exception:
        pass
    return DestinosBloqueados(prefijos=estado.blocked_prefixes, fijos=list(salientes.CODIGOS_BLOQUEADOS))


@router.get("/alertas")
async def alertas_de_todas(session: AsyncSession = Depends(get_admin_session)):
    """Alertas de tráfico saliente de todas las empresas, las más recientes primero."""
    filas = (
        await session.execute(
            select(SecurityAlert, Tenant.name)
            .join(Tenant, Tenant.id == SecurityAlert.tenant_id)
            .order_by(SecurityAlert.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {"id": a.id, "empresa": nombre, "tenant_id": a.tenant_id, "tipo": a.kind, "detalle": a.detail, "cuando": a.created_at}
        for a, nombre in filas
    ]


@router.get("/auditoria")
async def auditoria_de_todas(
    accion: str | None = None,
    actor: str | None = None,
    resultado: str | None = None,
    tenant_id: int | None = None,
    limite: int = Query(default=100, ge=1, le=500),
    desplazamiento: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_admin_session),
):
    """Registro de auditoría de toda la plataforma, incluidas las acciones
    sin empresa (las de la plataforma y los logins de usuarios inexistentes)."""
    consulta = _filtrar_auditoria(select(AuditLog), accion, actor, resultado)
    if tenant_id is not None:
        consulta = consulta.where(AuditLog.tenant_id == tenant_id)
    filas = (
        await session.execute(consulta.order_by(AuditLog.id.desc()).limit(limite).offset(desplazamiento))
    ).scalars().all()
    return [{**_auditoria_salida(f), "tenant_id": f.tenant_id} for f in filas]


@router.get("/consumo")
async def consumo_de_todas(mes: str | None = None, session: AsyncSession = Depends(get_admin_session)):
    """Consumo del mes de cada empresa: la base para facturar."""

    try:
        consumo.rango_del_mes(mes)
    except consumo.MesInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    empresas = (await session.execute(select(Tenant).order_by(Tenant.id))).scalars().all()
    return [
        {"empresa": t.name, "slug": t.slug, **await consumo.resumen(session, t.id, mes)} for t in empresas
    ]


@router.get("/consumo/csv")
async def consumo_de_todas_csv(mes: str | None = None, session: AsyncSession = Depends(get_admin_session)):
    filas = await consumo_de_todas(mes, session)
    etiqueta = consumo.rango_del_mes(mes)[0]
    return csv_respuesta(consumo.a_csv(filas), f"consumo-{etiqueta}.csv")


@router.get("/csp")
async def avisos_csp():
    """Lo que la CSP completa bloquearía si se aplicara (ver app/api/csp.py)."""
    from app.api import csp

    return csp.resumen()
