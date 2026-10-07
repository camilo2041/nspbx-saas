"""Buzón de voz: guardar el mensaje que dejó quien llamó y avisarle a la
persona de esa extensión.

El dialplan (config_generator._acciones_buzon) graba el mensaje y deja en el
canal `nspbx_buzon_ext` (la extensión) y `nspbx_buzon` (el archivo). Al
colgar, FreeSWITCH manda el CDR con esas variables y api/calls.py:receive_cdr
llama a `registrar`. Un mensaje vacío (colgó antes del tono, o solo silencio)
no se guarda: se borra el archivo.
"""

import asyncio
import logging
import re
import wave
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validacion
from app.core.config import settings
from app.models import Extension, MensajeBuzon, Tenant, User

logger = logging.getLogger(__name__)

# Menos que esto es colgar al oír el saludo, no un mensaje.
MIN_SEG = 2.0
# Más grande no va adjunto (muchos servidores de correo rechazan >10 MB).
MAX_ADJUNTO = 8 * 1024 * 1024
_RUTA_RE = re.compile(r"^[A-Za-z0-9_./-]{1,300}$")


def ruta_local(ruta_fs: str, tenant_id: int) -> Path | None:
    """La ruta del mensaje como la ve el backend, o None si no es un archivo
    del buzón de ESA empresa (el CDR llega de FreeSWITCH, pero el valor es
    una variable de canal: no se confía en él a ciegas)."""
    prefijo = f"{settings.fs_recordings_dir.rstrip('/')}/t{int(tenant_id)}/buzon/"
    if not ruta_fs or not ruta_fs.startswith(prefijo) or ".." in ruta_fs or not _RUTA_RE.fullmatch(ruta_fs):
        return None
    base = Path(settings.recordings_dir).resolve()
    local = (base / ruta_fs[len(settings.fs_recordings_dir.rstrip("/")) + 1 :]).resolve()
    if base not in local.parents or local.suffix.lower() != ".wav":
        return None
    return local


def duracion_wav(ruta: Path) -> float | None:
    try:
        with wave.open(str(ruta), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 8000)
    except (OSError, EOFError, wave.Error):
        return None


async def registrar(
    session: AsyncSession, variables: dict, tenant_id: int, uuid: str, caller: str | None, caller_name: str | None
) -> MensajeBuzon | None:
    """Crea el mensaje a partir de las variables del CDR (sin commit)."""
    ext = (variables.get("nspbx_buzon_ext") or "").strip()
    ruta_fs = (variables.get("nspbx_buzon") or "").strip()
    if not validacion.EXTENSION_RE.fullmatch(ext):
        return None
    local = ruta_local(ruta_fs, tenant_id)
    if local is None or f"/buzon/{ext}/" not in ruta_fs:
        logger.warning("Buzón: ruta rechazada en el CDR %s: %r", uuid, ruta_fs[:200])
        return None
    segundos = duracion_wav(local) if local.exists() else None
    if segundos is None or segundos < MIN_SEG:
        try:
            local.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    existente = (
        await session.execute(select(MensajeBuzon).where(MensajeBuzon.call_uuid == uuid))
    ).scalar_one_or_none()
    if existente:
        return existente
    mensaje = MensajeBuzon(
        tenant_id=tenant_id,
        extension=ext,
        call_uuid=uuid,
        caller_number=(caller or "")[:30] or None,
        caller_name=(caller_name or "")[:100] or None,
        ruta=ruta_fs,
        duracion=int(round(segundos)),
    )
    session.add(mensaje)
    return mensaje


async def marcar_oidos(session: AsyncSession, variables: dict, tenant_id: int) -> int:
    """Al escuchar por *97 se reproducen en orden; `nspbx_buzon_oido` es el
    último que terminó. Se marcan ese y los anteriores de esa extensión."""
    try:
        ultimo = int(variables.get("nspbx_buzon_oido") or 0)
    except ValueError:
        return 0
    m = await session.get(MensajeBuzon, ultimo) if ultimo else None
    if m is None or m.tenant_id != tenant_id:
        return 0
    filas = (
        await session.execute(
            select(MensajeBuzon).where(MensajeBuzon.tenant_id == tenant_id, MensajeBuzon.extension == m.extension,
                                       MensajeBuzon.escuchado.is_(False), MensajeBuzon.created_at <= m.created_at)
        )
    ).scalars().all()
    for f in filas:
        f.escuchado = True
    return len(filas)


async def transcribir(session: AsyncSession, mensaje: MensajeBuzon, tenant_id: int) -> str | None:
    """Lo que dijo quien dejó el mensaje (Deepgram, si la empresa tiene la
    API key). Se guarda en el mensaje; sin clave o si falla, None."""
    from app.services import deepgram
    from app.services.ajustes import ajustes_de

    ajustes = await ajustes_de(session, tenant_id)
    clave = (ajustes.deepgram_api_key if ajustes else None) or ""
    local = ruta_local(mensaje.ruta, tenant_id)
    if not clave or local is None or not local.exists():
        return None
    try:
        turnos = await asyncio.wait_for(deepgram.transcribir_grabacion(local.read_bytes(), clave), timeout=60)
    except Exception as exc:
        logger.warning("Buzón: no se pudo transcribir el mensaje %s: %s", mensaje.id, exc)
        return None
    texto = " ".join((t.get("texto") or "").strip() for t in (turnos or [])).strip()
    mensaje.transcripcion = texto[:4000] or None
    return mensaje.transcripcion


async def destinatarios(session: AsyncSession, tenant_id: int, ext: str) -> list[str]:
    """Correos de quienes tienen esa extensión."""
    filas = (
        await session.execute(
            select(User.email)
            .join(Extension, Extension.id == User.extension_id)
            .where(Extension.tenant_id == tenant_id, Extension.number == ext, User.email.is_not(None))
        )
    ).scalars().all()
    return [e for e in filas if e and "@" in e]


def armar_correo(mensaje: MensajeBuzon, para: list[str], empresa: str, audio: Path | None) -> EmailMessage:
    quien = mensaje.caller_name or mensaje.caller_number or "Número oculto"
    numero = f" ({mensaje.caller_number})" if mensaje.caller_name and mensaje.caller_number else ""
    m = EmailMessage()
    m["From"] = settings.smtp_remitente
    m["To"] = ", ".join(para)
    m["Subject"] = f"Nuevo mensaje de voz de {quien}"
    m.set_content(
        f"{quien}{numero} te dejó un mensaje de voz de {mensaje.duracion} segundos en la extensión "
        f"{mensaje.extension} ({empresa}).\n\n"
        + (f"Dice (transcripción automática):\n«{mensaje.transcripcion}»\n\n" if mensaje.transcripcion else "")
        + ("El audio va adjunto. " if audio else "")
        + "También puedes escucharlo en el panel, en «Buzón de voz».\n"
    )
    if audio is not None:
        m.add_attachment(
            audio.read_bytes(), maintype="audio", subtype="wav", filename=f"mensaje-{mensaje.extension}-{mensaje.id}.wav"
        )
    return m


async def avisar(tenant_id: int, mensaje_id: int) -> None:
    """En segundo plano y sin fallar: transcribe el mensaje (si hay clave de
    Deepgram), avisa al celular de la persona (Android) y le manda un correo
    con el audio y lo que dijo. Si algo falta, el mensaje igual queda en el
    panel y en la app."""
    from app.core.database import sesion_de_empresa
    from app.services import push, reportes_programados

    try:
        async with sesion_de_empresa(tenant_id) as session:
            mensaje = await session.get(MensajeBuzon, mensaje_id)
            if mensaje is None:
                return
            await transcribir(session, mensaje, tenant_id)
            await session.commit()
            await push.avisar_mensaje_buzon(session, tenant_id, mensaje)
    except Exception:
        logger.exception("Buzón: no se pudo transcribir o avisar al celular del mensaje %s", mensaje_id)
    if not reportes_programados.correo_configurado():
        return
    try:
        async with sesion_de_empresa(tenant_id) as session:
            mensaje = await session.get(MensajeBuzon, mensaje_id)
            if mensaje is None:
                return
            para = await destinatarios(session, tenant_id, mensaje.extension)
            if not para:
                return
            empresa = await session.get(Tenant, tenant_id)
            local = ruta_local(mensaje.ruta, tenant_id)
            adjunto = local if local and local.exists() and local.stat().st_size <= MAX_ADJUNTO else None
            correo = armar_correo(mensaje, para, empresa.name if empresa else "", adjunto)
        await asyncio.to_thread(reportes_programados._enviar_smtp, correo)
    except Exception:
        logger.exception("Buzón: no se pudo avisar por correo del mensaje %s", mensaje_id)
