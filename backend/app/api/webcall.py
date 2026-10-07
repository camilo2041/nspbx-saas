"""Endpoints públicos del widget de llamada web ("hablar con un agente").

Van SIN token de sesión: los consume el navegador de un visitante anónimo
en el sitio web de un cliente. Por eso `/api/webcall/` está en la lista de
exclusión de `app/core/auth.py::_ABIERTAS_PREFIJO`.

Las defensas (en orden de evaluación en `crear_sesion`): activado →
rate-limit por IP → horario de atención → Turnstile → tope global de
llamadas web simultáneas.

La empresa sale de `?empresa=<slug>` (el `data-empresa` del snippet de
`webcall.js`, que lo pasa al iframe `/webcall`). Sin ese parámetro es la
empresa 1: así siguen andando los snippets que se pegaron antes de que
hubiera uno por empresa. Cada empresa tiene su propio contexto de dialplan
`webcall_<slug>` (ver `_append_webcall_context` en config_generator.py) y
la credencial temporal recuerda de qué empresa es (ver
`fs_directory` en xml_endpoints.py).

Usa `get_admin_session` (no la sesión normal con RLS) porque estos
endpoints no tienen sesión de usuario ni tenant fijado por token — son la
central pública, análoga a `/fs/directory` y `/fs/dialplan`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limitador
from app.core.database import get_admin_session
from app.models import Queue, SystemSettings, Tenant
from app.services import turn, turnstile, webcall
from app.services.ajustes import ajustes_de

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webcall", tags=["webcall"])

# Empresa de los snippets viejos, sin `data-empresa` ("Empresa inicial" en
# la siembra de multiempresa de app/main.py).
_TENANT_POR_DEFECTO = 1


async def _empresa(
    empresa: str | None = Query(None, max_length=40), session: AsyncSession = Depends(get_admin_session)
) -> Tenant | None:
    """La empresa dueña del widget, o None si no existe o está desactivada
    (para el visitante es lo mismo que tener el botón apagado)."""
    if empresa:
        consulta = select(Tenant).where(Tenant.slug == empresa.strip().lower())
        tenant = (await session.execute(consulta)).scalar_one_or_none()
    else:
        tenant = await session.get(Tenant, _TENANT_POR_DEFECTO)
    return tenant if tenant and tenant.enabled else None


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
async def config(
    tenant: Tenant | None = Depends(_empresa), session: AsyncSession = Depends(get_admin_session)
):
    """Lo consume `webcall.js` para decidir si dibuja la burbuja y en qué
    estado. No revela nada sensible."""
    row = await ajustes_de(session, tenant_id=tenant.id) if tenant else None
    if not row or not row.webcall_enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "open": await _abierto(row),
        "site_key": row.webcall_turnstile_site_key or "",
        **_textos(row),
    }


async def _abierto(row) -> bool:
    """Su horario, más los festivos y fechas especiales de la empresa."""
    from app.services import festivos

    await festivos.refrescar()
    return festivos.abierto(row.webcall_schedule, row.tenant_id)


@router.post("/session")
async def crear_sesion(
    payload: SesionRequest,
    request: Request,
    tenant: Tenant | None = Depends(_empresa),
    session: AsyncSession = Depends(get_admin_session),
):
    row = await ajustes_de(session, tenant_id=tenant.id) if tenant else None
    if not row or not row.webcall_enabled:
        raise HTTPException(status_code=404, detail="El botón de llamada no está activo.")

    ip = _cliente_ip(request)

    if not await webcall.registry.rate_ok(ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Esperá unos minutos.")

    if not await _abierto(row):
        raise HTTPException(status_code=403, detail=_textos(row)["offline_text"])

    if not await turnstile.verify(row.webcall_turnstile_secret, payload.turnstile_token, ip):
        raise HTTPException(
            status_code=400, detail="No pudimos verificar que seas una persona. Recargá la página."
        )

    queue = await session.get(Queue, row.webcall_queue_id) if row.webcall_queue_id else None
    if not queue or not queue.enabled or queue.tenant_id != tenant.id:
        raise HTTPException(status_code=503, detail="El servicio no está disponible en este momento.")

    tope = row.webcall_max_concurrent or 0
    if tope and await webcall.registry.active_count(tenant.id) >= tope:
        raise HTTPException(
            status_code=503, detail="Todos nuestros agentes están ocupados. Intentá en unos minutos."
        )

    guest = await webcall.registry.create(ip, tenant.id)
    logger.info("Sesión web creada: %s (ip %s) -> %s, cola %s", guest.username, ip, tenant.slug, queue.name)
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
