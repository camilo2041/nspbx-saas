"""Webhook que llama FreeSWITCH (vía `curl` en el dialplan, ver
services/config_generator.py:_append_mobile_push_hook) justo antes de
timbrarle a una extensión con la app móvil registrada.

Dispara un push de voz (PushKit/FCM) para despertarla — es lo único que
puede sacar a la app de segundo plano o de cerrada del todo en un
teléfono real. Ver services/push.py y mobile/SETUP.md.
"""

import asyncio
import logging
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.core import validacion
from app.core.firmas import firma_push_valida
from app.core.database import get_admin_session
from app.models import Tenant
from app.services import esl, push

logger = logging.getLogger(__name__)

router = APIRouter(tags=["freeswitch-push"])

_UUID_RE = re.compile(r"[0-9a-fA-F-]{8,64}")
_NUMERO_RE = re.compile(r"[^0-9+*#]")
_NOMBRE_RE = re.compile(r"[^A-Za-z0-9 .,\-áéíóúüñÁÉÍÓÚÜÑ]")


async def _variable_de_canal(uuid_canal: str, variable: str) -> str:
    """Valor de una variable del canal, o "" si no se pudo leer (best-effort)."""
    try:
        valor = (await asyncio.wait_for(esl.api_buscar(f"uuid_getvar {uuid_canal} {variable}"), timeout=1.5)).strip()
    except Exception:
        return ""
    return "" if valor.startswith("-ERR") or valor == "_undef_" else valor[:120]


# GET y POST: el `curl` del dialplan (mod_curl) hace GET por omisión.
@router.api_route("/fs/push/{firma}/{slug}/{extension}", methods=["GET", "POST"])
async def avisar_llamada_entrante(
    firma: str,
    slug: str,
    extension: str,
    caller_id_number: str = "",
    caller_id_name: str = "",
    call_uuid: str = "",
    session: AsyncSession = Depends(get_admin_session),
):
    """Best-effort: si algo falla acá, la llamada sigue timbrando igual
    por SIP en cualquier softphone ya registrado — nunca hay que dejar que
    un error de push tumbe o demore la llamada real más de lo necesario.
    """
    # La firma solo vale para ESTA empresa y ESTA extensión (core/firmas.py):
    # quien la vea en un log no puede avisar llamadas de otras extensiones
    # ni usarla en /fs/directory o /fs/cdr.
    if not firma_push_valida(firma, slug, extension):
        raise HTTPException(status_code=403, detail="No autorizado")
    if not validacion.EXTENSION_RE.fullmatch(extension):
        raise HTTPException(status_code=422, detail="Extensión inválida")
    # Vienen del caller ID de quien llama (controlado por un tercero).
    call_uuid = call_uuid[:64]
    if not _UUID_RE.fullmatch(call_uuid):
        call_uuid = ""
    # El dialplan solo manda el uuid: quién llama se pregunta a FreeSWITCH, así el
    # nombre del llamante nunca pasa por un shell. Sanea lo recibido: lo controla un tercero.
    if call_uuid and not (caller_id_number or caller_id_name):
        caller_id_number = await _variable_de_canal(call_uuid, "caller_id_number")
        caller_id_name = await _variable_de_canal(call_uuid, "caller_id_name")
    caller_id_number = _NUMERO_RE.sub("", caller_id_number)[:40]
    caller_id_name = _NOMBRE_RE.sub("", caller_id_name)[:100]

    tenant = (await session.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        return {"ok": False, "motivo": "empresa no encontrada"}

    enviados = await push.avisar_llamada(session, tenant.id, slug, extension, call_uuid, caller_id_number, caller_id_name)
    return {"ok": True, "enviados": enviados}
