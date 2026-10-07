"""La llamada en curso de quien está conectado: ponerla en espera y
transferirla (ver services/transferencias.py). Siempre sobre la llamada
PROPIA: el usuario solo actúa sobre su extensión o su sesión de agente."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere
from app.core.database import get_session
from app.models import User
from app.services import ficha as ficha_svc, transferencias

router = APIRouter(prefix="/api/llamada", tags=["llamada"])

# La consola de agente también necesita el softphone (el audio del agente).
_USUARIO = Depends(requiere(permissions.SOFTPHONE_USAR))


class Espera(BaseModel):
    activar: bool


class Transferir(BaseModel):
    destino: str = Field(min_length=1, max_length=30)
    # True: primero hablas con el destino y después le pasas la llamada.
    consultada: bool = False


async def _hacer(corrutina):
    try:
        return await corrutina
    except transferencias.ErrorTransferencia as exc:
        raise HTTPException(status_code=exc.codigo, detail=exc.mensaje) from None


@router.get("/destinos")
async def destinos(session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await transferencias.destinos(session, usuario)


@router.post("/espera")
async def espera(datos: Espera, session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await _hacer(transferencias.espera(session, usuario, datos.activar))


@router.post("/transferir")
async def transferir(datos: Transferir, session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await _hacer(transferencias.transferir(session, usuario, datos.destino, datos.consultada))


@router.post("/transferencia/completar")
async def completar(session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await _hacer(transferencias.completar(session, usuario))


@router.post("/transferencia/cancelar")
async def cancelar(session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await _hacer(transferencias.cancelar(session, usuario))


@router.post("/transferencia/conferencia")
async def conferencia(session: AsyncSession = Depends(get_session), usuario: User = _USUARIO):
    return await _hacer(transferencias.unir_a_los_tres(session, usuario))


@router.get("/ficha")
async def ficha(
    numero: str = Query(min_length=1, max_length=40),
    session: AsyncSession = Depends(get_session),
    usuario: User = _USUARIO,
):
    """Quién llama: la ficha del CRM, sus últimas notas y llamadas."""
    return await ficha_svc.ficha(session, numero, usuario)
