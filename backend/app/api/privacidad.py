"""Solicitudes de los titulares de datos (Ley 1581): consultar y suprimir.

Las hace el administrador de la empresa cuando una persona lo pide; ver
services/privacidad.py. Se piden por POST para que el teléfono no quede en
la URL (ni en los logs del proxy); la auditoría lo guarda enmascarado.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services import privacidad

router = APIRouter(prefix="/api/privacidad", tags=["privacidad"])


class Titular(BaseModel):
    telefono: str = Field(min_length=1, max_length=30)


class Supresion(Titular):
    # El teléfono escrito dos veces: no se puede deshacer.
    confirmacion: str = Field(min_length=1, max_length=30)


@router.post("/titular/consultar")
async def consultar(payload: Titular, session: AsyncSession = Depends(get_session)):
    try:
        datos = await privacidad.datos_del_titular(session, payload.telefono)
    except privacidad.TelefonoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"telefono": payload.telefono, "datos": datos}


@router.post("/titular/suprimir")
async def suprimir(payload: Supresion, session: AsyncSession = Depends(get_session)):
    # Últimos 10 dígitos, como la búsqueda: "+57 315…" confirma "315…".
    if privacidad.solo_digitos(payload.confirmacion)[-10:] != privacidad.solo_digitos(payload.telefono)[-10:]:
        raise HTTPException(status_code=422, detail="La confirmación no coincide con el teléfono")
    try:
        cuentas = await privacidad.suprimir_titular(session, payload.telefono)
    except privacidad.TelefonoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    await session.commit()
    return cuentas
