"""Verificación de Cloudflare Turnstile (captcha invisible).

El widget de llamada web está abierto a internet y provisiona credenciales
SIP: sin una barrera anti-bot, un script podría pedir miles de sesiones.
Turnstile es la opción gratuita de Cloudflare y no muestra puzzles al
usuario en el caso normal.

Si no hay secret configurado (desarrollo), se omite la verificación.
Ante cualquier error de red se falla CERRADO (no se entrega la sesión):
es un endpoint sensible, mejor un "reintentá" que un hueco de abuso.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify(secret: str | None, token: str | None, remoteip: str | None = None) -> bool:
    if not secret:
        return True
    if not token:
        return False
    data = {"secret": secret, "response": token}
    if remoteip and remoteip != "?":
        data["remoteip"] = remoteip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_VERIFY_URL, data=data)
        ok = bool(resp.json().get("success"))
        if not ok:
            logger.info("Turnstile rechazó el token: %s", resp.json().get("error-codes"))
        return ok
    except Exception as exc:
        logger.warning("Turnstile no disponible (%s); se rechaza la sesión web", exc)
        return False
