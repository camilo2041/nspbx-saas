"""Controles de emergencia de TODA la plataforma. Solo el rol plataforma.

Hoy: el interruptor global de llamadas salientes. Se lee en cada llamada
(el dialplan se pide por llamada, y el clic-para-llamar y el marcador
consultan la política antes de cada originate), así que cortar es
inmediato para toda llamada nueva.
"""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import usuario_actual
from app.core.database import get_admin_session
from app.api.security import _auditoria_salida, _filtrar_auditoria
from app.models import AuditLog, PlatformState, SecurityAlert, Tenant, User
from app.services import esl

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
