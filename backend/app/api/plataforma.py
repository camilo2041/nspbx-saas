"""Controles de emergencia de TODA la plataforma. Solo el rol plataforma.

Hoy: el interruptor global de llamadas salientes. Se lee en cada llamada
(el dialplan se pide por llamada, y el clic-para-llamar y el marcador
consultan la política antes de cada originate), así que cortar es
inmediato para toda llamada nueva.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import usuario_actual
from app.core.database import get_admin_session
from app.models import PlatformState, User
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
