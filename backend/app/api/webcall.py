"""Endpoints públicos del widget de llamada web ("hablar con un agente").

Van SIN token de sesión: los consume el navegador de un visitante anónimo
en el sitio web de un cliente. Por eso `/api/webcall/` está en la lista de
exclusión de `app/core/auth.py::_ABIERTAS_PREFIJO`.

Las defensas (en orden de evaluación en `crear_sesion`): activado →
rate-limit por IP → horario de atención → Turnstile → tope global de
llamadas web simultáneas.

FIJO A tenant_id=1 POR AHORA. En el proyecto multiempresa (nspbx-saas)
esto se generalizaría resolviendo la empresa desde un identificador que
venga en la query string del embed (ej. `?empresa=<slug>` en
`webcall.js`/`/webcall`), buscado contra `Tenant.slug` o
`Tenant.subdomain`, y pasando ese `tenant_id` en vez del `1` fijo a
`ajustes_de()` y a las consultas de este router. El contexto de dialplan
ya está preparado para eso: se llama `webcall_<slug>` y no `webcall` a
secas (ver `_append_webcall_context` en config_generator.py), así que
activar el widget en una segunda empresa no chocaría con la primera.

Usa `get_admin_session` (no la sesión normal con RLS) porque estos
endpoints no tienen sesión de usuario ni tenant fijado por token — son la
central pública, análoga a `/fs/directory` y `/fs/dialplan`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limitador
from app.core.database import get_admin_session
from app.models import Queue, SystemSettings, Tenant
from app.services import turn, turnstile, webcall
from app.services.ajustes import ajustes_de

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webcall", tags=["webcall"])

# Empresa a la que está cableado el widget por ahora (ver docstring del
# módulo). "Empresa inicial" en la siembra de multiempresa de app/main.py.
_TENANT_ID = 1


def _cliente_ip(request: Request) -> str:
    # Nunca la primera entrada de X-Forwarded-For: la escribe el visitante.
    return limitador.ip_cliente(request)


class SesionRequest(BaseModel):
    turnstile_token: str | None = None


def _textos(row: SystemSettings) -> dict:
    return {
        "greeting": row.webcall_greeting or "Presione para hablar con un agente",
        "button_text": row.webcall_button_text or "Hablar con un agente",
        "offline_text": row.webcall_offline_text or "Estamos fuera de horario de atención",
    }


@router.get("/config")
async def config(session: AsyncSession = Depends(get_admin_session)):
    """Lo consume `webcall.js` para decidir si dibuja la burbuja y en qué
    estado. No revela nada sensible."""
    row = await ajustes_de(session, tenant_id=_TENANT_ID)
    if not row or not row.webcall_enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "open": webcall.is_open(row.webcall_schedule),
        "site_key": row.webcall_turnstile_site_key or "",
        **_textos(row),
    }


@router.post("/session")
async def crear_sesion(
    payload: SesionRequest, request: Request, session: AsyncSession = Depends(get_admin_session)
):
    row = await ajustes_de(session, tenant_id=_TENANT_ID)
    if not row or not row.webcall_enabled:
        raise HTTPException(status_code=404, detail="El botón de llamada no está activo.")

    ip = _cliente_ip(request)

    if not await webcall.registry.rate_ok(ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá unos minutos.")

    if not webcall.is_open(row.webcall_schedule):
        raise HTTPException(status_code=403, detail=_textos(row)["offline_text"])

    if not await turnstile.verify(row.webcall_turnstile_secret, payload.turnstile_token, ip):
        raise HTTPException(
            status_code=400, detail="No pudimos verificar que seas una persona. Recargá la página."
        )

    queue = await session.get(Queue, row.webcall_queue_id) if row.webcall_queue_id else None
    if not queue or not queue.enabled:
        raise HTTPException(status_code=503, detail="El servicio no está disponible en este momento.")

    tope = row.webcall_max_concurrent or 0
    if tope and await webcall.registry.active_count() >= tope:
        raise HTTPException(
            status_code=503, detail="Todos nuestros agentes están ocupados. Intentá en unos minutos."
        )

    tenant = await session.get(Tenant, _TENANT_ID)
    if not tenant:
        raise HTTPException(status_code=503, detail="El servicio no está disponible en este momento.")

    guest = await webcall.registry.create(ip)
    logger.info("Sesión web creada: %s (ip %s) -> cola %s", guest.username, ip, queue.name)
    return {
        "username": guest.username,
        "password": guest.password,
        "domain": tenant.sip_domain,
        "sip_ws_url": row.sip_ws_url,
        "ice_servers": turn.ice_servers(guest.username),
        "target": webcall.TARGET,
        "expires_in": webcall.SESSION_MAX,
    }


@router.post("/session/{username}/end")
async def terminar_sesion(username: str):
    """El navegador la llama al colgar para liberar el cupo enseguida; el
    barrido del MaintenanceWorker es el respaldo por si no llega."""
    if webcall.GUEST_RE.match(username):
        await webcall.registry.end(username)
    return {"ok": True}
