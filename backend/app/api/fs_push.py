"""Webhook que llama FreeSWITCH (vía `curl` en el dialplan, ver
services/config_generator.py:_append_mobile_push_hook) justo antes de
timbrarle a una extensión con la app móvil registrada.

Dispara un push de voz (PushKit/FCM) para despertarla — es lo único que
puede sacar a la app de segundo plano o de cerrada del todo en un
teléfono real. Ver services/push.py y mobile/SETUP.md.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verificar_secreto_fs
from app.core.database import get_admin_session
from app.models import DeviceToken, Extension, Tenant
from app.services import push

logger = logging.getLogger(__name__)

router = APIRouter(tags=["freeswitch-push"])


@router.post("/fs/push/{secret}/{slug}/{extension}")
async def avisar_llamada_entrante(
    secret: str,
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
    verificar_secreto_fs(secret)

    tenant = (await session.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        return {"ok": False, "motivo": "empresa no encontrada"}

    dispositivos = (
        await session.execute(
            select(DeviceToken)
            .join(Extension, Extension.id == DeviceToken.extension_id)
            .where(DeviceToken.tenant_id == tenant.id, Extension.number == extension)
        )
    ).scalars().all()
    if not dispositivos:
        return {"ok": True, "enviados": 0}

    # Forma exacta que espera `expo-callkit-telecom` del lado de la app
    # (IncomingCallEvent, ver mobile/SETUP.md): `serverCallId` es el uuid
    # de canal de FreeSWITCH, así la app puede correlacionar el push con
    # el INVITE que le va a llegar por SIP apenas reconecte.
    evento_llamada = {
        "eventId": str(uuid.uuid4()),
        "serverCallId": call_uuid or str(uuid.uuid4()),
        "hasVideo": False,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "caller": {
            "id": caller_id_number or "desconocido",
            "displayName": caller_id_name or caller_id_number or "Desconocido",
            "phoneNumber": caller_id_number or None,
        },
        "metadata": {"extension": extension, "tenantSlug": slug},
    }

    async def _enviar(d: DeviceToken):
        try:
            if d.token_type == "APNS_VOIP":
                await asyncio.wait_for(push.enviar_voip_ios(d.token, evento_llamada), timeout=2)
            elif d.token_type == "FCM":
                await asyncio.wait_for(push.enviar_push_android(d.token, evento_llamada), timeout=2)
        except asyncio.TimeoutError:
            logger.warning("Timeout enviando push a dispositivo %s (%s)", d.id, d.platform)
        except Exception:
            logger.exception("Error enviando push a dispositivo %s (%s)", d.id, d.platform)

    await asyncio.gather(*(_enviar(d) for d in dispositivos))
    return {"ok": True, "enviados": len(dispositivos)}
