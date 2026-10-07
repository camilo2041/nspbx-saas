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


class PruebaHumo(BaseModel):
    tenant_id: int
    buzon: str | None = None
    grupo: str | None = None


@router.post("/humo")
async def prueba_de_humo(datos: PruebaHumo, usuario: User = Depends(usuario_actual)):
    """Llamadas de prueba dentro de la central de la empresa (services/humo.py).
    Tarda hasta un par de minutos."""
    from app.services import humo

    for valor in (datos.buzon, datos.grupo):
        if valor and not valor.isdigit():
            raise HTTPException(status_code=422, detail="La extensión y el grupo son números")
    try:
        resultado = await humo.probar(datos.tenant_id, datos.buzon, datos.grupo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    logger.info("Prueba de humo de %s por %s: %s", resultado["empresa"], usuario.username, "ok" if resultado["ok"] else "con fallos")
    return resultado


@router.get("/operacion")
async def operacion(session: AsyncSession = Depends(get_admin_session)):
    """Respaldo diario, copia externa cifrada y último simulacro de
    restauración (services/operacion.py)."""
    from app.core.config import settings as cfg
    from app.models import SystemSettings
    from app.services import operacion as op

    ultimo = (
        await session.execute(select(SystemSettings.last_backup_at, SystemSettings.last_backup_ok, SystemSettings.last_backup_error)
                              .order_by(SystemSettings.last_backup_at.desc().nulls_last()).limit(1))
    ).first()
    volcado = op.ultimo_volcado()
    return {
        "respaldo": {"at": ultimo[0] if ultimo else None, "ok": ultimo[1] if ultimo else None,
                     "error": ultimo[2] if ultimo else None, "archivo": volcado.name if volcado else None},
        "externo": op.copia_externa(),
        "simulacro": op.simulacro(),
        "metricas": bool(cfg.metrics_token),
    }


@router.get("/sin-ruta")
async def numeros_sin_ruta(session: AsyncSession = Depends(get_admin_session)):
    """Números a los que entran llamadas por una troncal sin ninguna ruta de
    entrada (se cuelgan): falta crearles la ruta, o el proveedor manda el
    número en otro formato (services/sin_ruta.py)."""
    from app.models import NumeroSinRuta
    from app.services import sin_ruta

    empresas = {t.id: t for t in (await session.execute(select(Tenant))).scalars().all()}
    slugs = {tid: t.slug for tid, t in empresas.items()}
    filas = (
        await session.execute(select(NumeroSinRuta).order_by(NumeroSinRuta.ultima_vez.desc()).limit(200))
    ).scalars().all()
    salida = []
    for n in filas:
        tid = sin_ruta.empresa_de_troncal(n.troncal, slugs)
        salida.append({
            "id": n.id, "numero": n.numero, "para": n.para, "origen": n.origen, "troncal": n.troncal,
            "empresa": empresas[tid].name if tid else None, "tenant_id": tid, "veces": n.veces,
            "primera_vez": n.primera_vez, "ultima_vez": n.ultima_vez,
        })
    return salida


@router.delete("/sin-ruta/{numero_id}", status_code=204)
async def olvidar_sin_ruta(numero_id: int, session: AsyncSession = Depends(get_admin_session)):
    """Ya se resolvió (o no interesa): sale de la lista hasta que vuelva a llamar."""
    from sqlalchemy import delete

    from app.models import NumeroSinRuta

    await session.execute(delete(NumeroSinRuta).where(NumeroSinRuta.id == numero_id))
    await session.commit()


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

# --- Desbloqueo de IP de fail2ban (services/desbloqueos.py) -------------------------------


class DesbloqueoIn(BaseModel):
    jail: str
    ip: str
    motivo: str | None = None


@router.get("/desbloqueos")
async def ver_desbloqueos(session: AsyncSession = Depends(get_admin_session)):
    """Lo que fail2ban tiene bloqueado ahora y los últimos pedidos de desbloqueo."""
    from app.models import DesbloqueoIp
    from app.services import desbloqueos, fail2ban

    pedidos = (await session.execute(select(DesbloqueoIp).order_by(DesbloqueoIp.id.desc()).limit(30))).scalars().all()
    return {
        "disponible": fail2ban.disponible(),
        "bloqueos": [{"jail": b.jail, "ip": b.ip, "desde": b.desde, "hasta": b.hasta, "veces": b.veces}
                     for b in fail2ban.bloqueos()],
        "pedidos": [{
            "id": p.id, "jail": p.jail, "ip": p.ip, "motivo": p.motivo, "pedido_por": p.pedido_por,
            "pedido_en": p.pedido_en, "estado": p.estado, "resuelto_en": p.resuelto_en, "detalle": p.detalle,
            "sin_atender": desbloqueos.sin_atender(p),
        } for p in pedidos],
    }


@router.post("/desbloqueos", status_code=201)
async def pedir_desbloqueo(
    datos: DesbloqueoIn, session: AsyncSession = Depends(get_admin_session), usuario: User = Depends(usuario_actual),
):
    """Deja el pedido; lo ejecuta el script del host en menos de un minuto."""
    from app.services import desbloqueos

    try:
        pedido = await desbloqueos.pedir(session, datos.jail, datos.ip, datos.motivo, usuario.username)
    except desbloqueos.PedidoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    logger.warning("Desbloqueo de %s (%s) pedido por %s", pedido.ip, pedido.jail, usuario.username)
    return {"id": pedido.id, "estado": pedido.estado}
