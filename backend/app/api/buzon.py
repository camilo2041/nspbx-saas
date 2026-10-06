"""Buzón de voz: los mensajes que dejaron quienes llamaron a una extensión
que no contestó (ver services/buzon.py y config_generator._acciones_buzon).

Cada persona ve los de SU extensión; quien puede ver todas las llamadas de
la empresa ve también los de todas las extensiones.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calls import _VER, _solo_suyas
from app.core.database import get_session, traer_propio
from app.models import MensajeBuzon, User
from app.services import buzon

router = APIRouter(prefix="/api/buzon", tags=["buzon"])


class MensajeBuzonOut(BaseModel):
    id: int
    extension: str
    caller_number: str | None = None
    caller_name: str | None = None
    duracion: int
    escuchado: bool
    created_at: datetime | None = None


class MarcarMensaje(BaseModel):
    escuchado: bool


def _acotar(query, usuario: User):
    propia = _solo_suyas(usuario)
    return query if propia is None else query.where(MensajeBuzon.extension == propia)


async def _traer(mensaje_id: int, session: AsyncSession, usuario: User) -> MensajeBuzon:
    """404 también cuando es de otra extensión: no se confirma que exista."""
    mensaje = await traer_propio(session, MensajeBuzon, mensaje_id)
    propia = _solo_suyas(usuario)
    if mensaje is None or (propia is not None and mensaje.extension != propia):
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    return mensaje


@router.get("", response_model=list[MensajeBuzonOut])
async def listar(
    extension: str | None = None,
    sin_escuchar: bool = False,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
    usuario: User = _VER,
):
    query = _acotar(select(MensajeBuzon), usuario).order_by(desc(MensajeBuzon.created_at), desc(MensajeBuzon.id))
    if extension:
        query = query.where(MensajeBuzon.extension == extension)
    if sin_escuchar:
        query = query.where(MensajeBuzon.escuchado.is_(False))
    return (await session.execute(query.limit(max(1, min(limit, 500))))).scalars().all()


@router.get("/resumen")
async def resumen(session: AsyncSession = Depends(get_session), usuario: User = _VER):
    """Cuántos hay sin escuchar (el número junto a «Buzón de voz» en el menú)."""
    query = _acotar(select(func.count()).select_from(MensajeBuzon), usuario).where(MensajeBuzon.escuchado.is_(False))
    return {"sin_escuchar": (await session.execute(query)).scalar_one()}


@router.get("/{mensaje_id}/audio")
async def audio(mensaje_id: int, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    mensaje = await _traer(mensaje_id, session, usuario)
    local = buzon.ruta_local(mensaje.ruta, mensaje.tenant_id)
    if local is None or not local.exists():
        raise HTTPException(status_code=404, detail="El audio del mensaje ya no está en el servidor")
    fecha = mensaje.created_at.strftime("%Y%m%d-%H%M") if mensaje.created_at else str(mensaje.id)
    return FileResponse(local, media_type="audio/wav", filename=f"mensaje-{mensaje.extension}-{fecha}.wav")


@router.put("/{mensaje_id}", response_model=MensajeBuzonOut)
async def marcar(
    mensaje_id: int, datos: MarcarMensaje, session: AsyncSession = Depends(get_session), usuario: User = _VER
):
    mensaje = await _traer(mensaje_id, session, usuario)
    mensaje.escuchado = datos.escuchado
    await session.commit()
    await session.refresh(mensaje)
    return mensaje


@router.delete("/{mensaje_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(mensaje_id: int, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    mensaje = await _traer(mensaje_id, session, usuario)
    local = buzon.ruta_local(mensaje.ruta, mensaje.tenant_id)
    await session.delete(mensaje)
    await session.commit()
    if local is not None:
        try:
            local.unlink(missing_ok=True)
        except OSError:
            pass
