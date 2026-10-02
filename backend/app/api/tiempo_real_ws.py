"""Llamadas en vivo de la empresa, por WebSocket (ver services/tiempo_real.py).

Como /ws/logs, vive fuera de /api/ y el token viaja en la query string (un
WebSocket de navegador no manda cabeceras). Cada mensaje sale SOLO a los
suscriptores de la empresa de la llamada; el usuario de la plataforma no
tiene empresa y no recibe nada.

Mensajes: `inicial` (las llamadas en curso al conectar), `llamada` (un
cambio: nueva, timbra, contesta, puente, espera, retoma, cuelga),
`reinicio` (se perdió la conexión con FreeSWITCH; el tablero se vacía) y
`ping`.

La sesión se vuelve a validar cada minuto: si cierran las sesiones del
usuario, le quitan el permiso o desactivan la empresa, el socket se corta.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.logs_ws import _usuario_del_token
from app.core import permissions
from app.core.database import app_session
from app.services.tiempo_real import tiempo_real

logger = logging.getLogger(__name__)

router = APIRouter()

PERMISO = permissions.LLAMADAS_VER_TODAS
_PING_S = 25
_REVALIDAR_S = 60


async def autorizar(token: str | None) -> int | None:
    """La empresa cuyas llamadas puede ver este token, o None."""
    async with app_session() as session:
        usuario = await _usuario_del_token(token, session)
    if usuario is None or usuario.tenant_id is None:
        return None
    if not permissions.puede(usuario.role, PERMISO, usuario.tenant_id):
        return None
    return usuario.tenant_id


@router.websocket("/ws/tiempo-real")
async def tiempo_real_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token")
    tenant_id = await autorizar(token)
    if tenant_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    cola = tiempo_real.suscribir(tenant_id)
    try:
        await websocket.send_json({"tipo": "inicial", "llamadas": tiempo_real.llamadas(tenant_id)})
        loop = asyncio.get_running_loop()
        revalidar_en = loop.time() + _REVALIDAR_S
        while True:
            try:
                mensaje = await asyncio.wait_for(cola.get(), timeout=_PING_S)
            except asyncio.TimeoutError:
                mensaje = {"tipo": "ping"}
            if loop.time() >= revalidar_en:
                if await autorizar(token) != tenant_id:
                    await websocket.close(code=4401)
                    return
                revalidar_en = loop.time() + _REVALIDAR_S
            await websocket.send_json(mensaje)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        tiempo_real.desuscribir(tenant_id, cola)
