"""Push a la app móvil: PushKit (iOS) y FCM (Android) para avisar una
llamada entrante mientras la app está en segundo plano o cerrada.

Todo lo de acá es best-effort: la llamada YA está timbrando por SIP en
cualquier softphone registrado (de escritorio o la app si estaba
conectada); un push perdido no debe tumbar nada de eso, solo significa
que el teléfono no se despertó solo. Por eso cada función atrapa sus
propios errores y se limita a loguear.

Sin `APNS_*`/`FCM_*` configurados (ver core/config.py), estas funciones no
hacen nada más que avisar por log — así el resto de la app (llamar con la
app abierta, ver métricas) sigue sirviendo sin esas credenciales.
"""

import json
import logging
import time

import httpx
import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

_APNS_HOST_PROD = "api.push.apple.com"
_APNS_HOST_SANDBOX = "api.sandbox.push.apple.com"

# Cacheado en memoria del proceso: APNs pide no generar un token de
# proveedor nuevo más seguido que cada 20 minutos, y este vence a la hora.
_apns_token_cache: tuple[str, float] | None = None


def _apns_provider_token() -> str | None:
    global _apns_token_cache
    if not (settings.apns_key_id and settings.apns_team_id and settings.apns_auth_key):
        return None
    ahora = time.time()
    if _apns_token_cache and ahora - _apns_token_cache[1] < 55 * 60:
        return _apns_token_cache[0]
    token = jwt.encode(
        {"iss": settings.apns_team_id, "iat": int(ahora)},
        settings.apns_auth_key,
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _apns_token_cache = (token, ahora)
    return token


async def enviar_voip_ios(voip_token: str, incoming_call_event: dict) -> None:
    """Push de PushKit: lo único que puede despertar la app en segundo
    plano en iOS para mostrar una llamada entrante con CallKit. Requiere
    el capability VoIP del bundle id (ver mobile/SETUP.md).

    El payload va envuelto en `incomingCall` porque así lo espera
    `expo-callkit-telecom` del lado de la app (mobile/src/softphone/*):
    es el módulo el que parsea el push nativo antes de que corra ni una
    línea de JS, y esa es la forma exacta que reconoce.
    """
    provider_token = _apns_provider_token()
    if not provider_token:
        logger.warning("APNs sin configurar (APNS_KEY_ID/APNS_TEAM_ID/APNS_AUTH_KEY): push VoIP no enviado")
        return
    host = _APNS_HOST_SANDBOX if settings.apns_use_sandbox else _APNS_HOST_PROD
    url = f"https://{host}/3/device/{voip_token}"
    headers = {
        "authorization": f"bearer {provider_token}",
        "apns-topic": f"{settings.apns_bundle_id}.voip",
        "apns-push-type": "voip",
        "apns-priority": "10",
        "apns-expiration": "0",
    }
    try:
        async with httpx.AsyncClient(http2=True, timeout=1.5) as client:
            resp = await client.post(url, headers=headers, json={"incomingCall": incoming_call_event})
        if resp.status_code != 200:
            logger.warning("APNs rechazó el push VoIP (%s): %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Error enviando push VoIP a iOS")


# Igual que el de APNs: se reusa el access token de Google mientras no esté
# por vencer, en vez de pedir uno nuevo en cada llamada.
_fcm_token_cache: tuple[str, float] | None = None


async def _fcm_access_token() -> str | None:
    global _fcm_token_cache
    if not settings.fcm_service_account_json:
        return None
    ahora = time.time()
    if _fcm_token_cache and ahora - _fcm_token_cache[1] < 50 * 60:
        return _fcm_token_cache[0]
    cuenta = json.loads(settings.fcm_service_account_json)
    assertion = jwt.encode(
        {
            "iss": cuenta["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": int(ahora),
            "exp": int(ahora) + 3600,
        },
        cuenta["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=3) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _fcm_token_cache = (token, ahora)
    return token


async def enviar_push_android(push_token: str, incoming_call_event: dict) -> None:
    """Mensaje `data`-only de prioridad alta: la app lo recibe con la
    pantalla apagada y es el propio `expo-callkit-telecom` (su
    FirebaseMessagingService, ver mobile/app.json) quien lo parsea antes
    de que corra código JS — un `notification` normal de FCM no puede
    disparar eso ni llegar con la app cerrada.

    El formato (`messageType`/`incomingCall` como JSON-string) es el que
    ese módulo espera; no es arbitrario."""
    if not settings.fcm_project_id:
        logger.warning("FCM sin configurar (FCM_PROJECT_ID/FCM_SERVICE_ACCOUNT_JSON): push no enviado")
        return
    try:
        access_token = await _fcm_access_token()
        if not access_token:
            return
        url = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send"
        body = {
            "message": {
                "token": push_token,
                "data": {
                    "messageType": "incomingCall",
                    "incomingCall": json.dumps(incoming_call_event),
                },
                "android": {"priority": "high"},
            }
        }
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, json=body
            )
        if resp.status_code != 200:
            logger.warning("FCM rechazó el push (%s): %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Error enviando push a Android")
