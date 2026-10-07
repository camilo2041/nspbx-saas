"""Buzón de voz: los mensajes que dejaron quienes llamaron a una extensión
que no contestó (ver services/buzon.py y config_generator._acciones_buzon).

Cada persona ve los de SU extensión; quien puede ver todas las llamadas de
la empresa ve también los de todas las extensiones.
"""

import io
import wave
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calls import _VER, _solo_suyas
from app.core.database import get_session, traer_propio
from app.core import validacion
from app.core.config import settings
from app.models import Extension, MensajeBuzon, User
from app.services import buzon

router = APIRouter(prefix="/api/buzon", tags=["buzon"])


class MensajeBuzonOut(BaseModel):
    id: int
    extension: str
    caller_number: str | None = None
    caller_name: str | None = None
    duracion: int
    escuchado: bool
    transcripcion: str | None = None
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


# --- Saludo propio de cada extensión -------------------------------------------------------
# Lo mismo que graba *98 desde el teléfono (config_generator._append_buzon_grabar_saludo).

SALUDO_MAX_BYTES = 5 * 1024 * 1024
SALUDO_MAX_SEG = 60


async def _extension_del_saludo(extension: str | None, session: AsyncSession, usuario: User) -> str:
    """La propia; quien ve todas las llamadas puede elegir otra de la empresa."""
    propia = _solo_suyas(usuario)
    ext = propia if propia is not None else (extension or (usuario.extension.number if usuario.extension else None))
    if not ext or not validacion.EXTENSION_RE.fullmatch(ext):
        raise HTTPException(status_code=400, detail="Tu usuario no tiene una extensión")
    if extension and extension != ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    existe = (await session.execute(select(Extension.id).where(Extension.number == ext))).first()
    if not existe:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    return ext


def _ruta_saludo(tenant_id: int, ext: str) -> Path:
    return Path(settings.recordings_dir) / f"t{int(tenant_id)}" / "buzon" / ext / "saludo.wav"


@router.get("/saludo")
async def ver_saludo(extension: str | None = None, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    ext = await _extension_del_saludo(extension, session, usuario)
    ruta = _ruta_saludo(usuario.tenant_id, ext)
    return {"extension": ext, "propio": ruta.exists(),
            "segundos": round(buzon.duracion_wav(ruta) or 0) if ruta.exists() else None}


@router.get("/saludo/audio")
async def oir_saludo(extension: str | None = None, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    ext = await _extension_del_saludo(extension, session, usuario)
    ruta = _ruta_saludo(usuario.tenant_id, ext)
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Esa extensión usa el saludo general")
    return FileResponse(ruta, media_type="audio/wav", filename=f"saludo-{ext}.wav")


@router.post("/saludo")
async def subir_saludo(
    archivo: UploadFile = File(...), extension: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session), usuario: User = _VER,
):
    """Un WAV de hasta 60 s. También se graba marcando *98 desde el teléfono."""
    ext = await _extension_del_saludo(extension, session, usuario)
    datos = await archivo.read(SALUDO_MAX_BYTES + 1)
    if len(datos) > SALUDO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="El saludo pesa demasiado (máximo 5 MB)")
    try:
        with wave.open(io.BytesIO(datos), "rb") as w:
            segundos = w.getnframes() / float(w.getframerate() or 8000)
    except (wave.Error, EOFError):
        raise HTTPException(status_code=422, detail="Sube un archivo WAV (PCM)") from None
    if not 1 <= segundos <= SALUDO_MAX_SEG:
        raise HTTPException(status_code=422, detail=f"El saludo debe durar entre 1 y {SALUDO_MAX_SEG} segundos")
    ruta = _ruta_saludo(usuario.tenant_id, ext)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return {"extension": ext, "propio": True, "segundos": round(segundos)}


@router.delete("/saludo", status_code=status.HTTP_204_NO_CONTENT)
async def quitar_saludo(extension: str | None = None, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    """Vuelve al saludo general."""
    ext = await _extension_del_saludo(extension, session, usuario)
    try:
        _ruta_saludo(usuario.tenant_id, ext).unlink(missing_ok=True)
    except OSError:
        pass


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
