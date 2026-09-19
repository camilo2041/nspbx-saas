"""Consola de logs en vivo — la versión web de pararse en `fs_cli` con
`/log <nivel>` (para quien viene de Asterisk: el equivalente de
`asterisk -rvvvvv`).

Vive fuera de /api/ (como el websocket del voizbot) porque un WebSocket
de navegador no puede mandar la cabecera Authorization en el handshake:
el token viaja por query string y se valida acá a mano, con el mismo
criterio que `sesion_obligatoria`/`requiere` usan para el resto de la
API — nada de exponer esto sin sesión, es el tráfico SIP completo de la
central.
"""

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alcance, permissions
from app.core.config import settings
from app.core.database import async_session, fijar_tenant, get_session
from app.core.runtime_settings import runtime_settings
from app.core.security import leer_token
from app.models import User
from app.services import esl

logger = logging.getLogger(__name__)

router = APIRouter()

_FIRMAS_PUSH = re.compile(r"/fs/push/[0-9a-f]{64}/")


def _ocultar_secretos(linea: str) -> str:
    """Tapa las claves antes de mandar el log al navegador.

    El log de FreeSWITCH es global (todas las empresas) y trae las URL que
    llama el dialplan y las consultas de mod_xml_curl, que incluyen
    FS_XML_SECRET. Con ese secreto /fs/directory devuelve la contraseña SIP
    de TODAS las empresas: un administrador de una sola empresa podía leerlo
    aquí y pasar a controlar las demás. Se ocultan también la clave de ESL y
    las firmas de push (que solo valen para una extensión, pero no hay por
    qué mostrarlas).
    """
    for secreto in (settings.fs_xml_secret, settings.fs_esl_password, runtime_settings.fs_esl_password):
        if secreto and len(secreto) >= 6:
            linea = linea.replace(secreto, "***")
    return _FIRMAS_PUSH.sub("/fs/push/***/", linea)


async def _usuario_del_token(token: str | None, session: AsyncSession) -> User | None:
    if not token:
        return None
    datos = leer_token(token)
    if not datos:
        return None
    try:
        user_id = int(datos.get("sub", ""))
    except (TypeError, ValueError):
        return None
    # Mismo criterio que sesion_obligatoria (ver app/core/auth.py): con
    # Row-Level Security activado, una consulta sin la empresa fijada en
    # la sesión no encuentra NINGUNA fila, ni siquiera la del propio
    # usuario — este WebSocket se autentica solo (no pasa por
    # sesion_obligatoria, ver el docstring de arriba) y antes de este
    # arreglo nunca fijaba el tenant, así que la consola de logs siempre
    # rechazaba la conexión (403) aunque el token fuera válido.
    tid = datos.get("tid")
    if tid is None:
        async with async_session() as admin_sess:
            usuario = (
                (await admin_sess.execute(select(User).where(User.id == user_id))).unique().scalar_one_or_none()
            )
    else:
        fijar_tenant(session, tid)
        usuario = (await session.execute(select(User).where(User.id == user_id))).unique().scalar_one_or_none()
    if not usuario or not usuario.enabled:
        return None
    return usuario


@router.websocket("/ws/logs")
async def logs_websocket(websocket: WebSocket, session: AsyncSession = Depends(get_session)):
    usuario = await _usuario_del_token(websocket.query_params.get("token"), session)
    # Mismo permiso que troncales/extensiones: quien puede ver esto puede
    # ver el tráfico SIP completo, así que es tan sensible como las
    # credenciales de una troncal.
    if not usuario or not (
        permissions.puede(usuario.role, permissions.TELEFONIA_GESTIONAR)
        or permissions.puede(usuario.role, permissions.EMPRESAS_GESTIONAR)
    ):
        await websocket.close(code=4401)
        return

    # El log de FreeSWITCH mezcla el tráfico SIP de TODAS las empresas (números,
    # nombres, contraseñas en cabeceras de depuración). Un administrador de
    # empresa solo lo ve si es la única de la instalación (ver core/alcance.py).
    if not await alcance.es_operador_global(usuario, session):
        await websocket.close(code=4403)
        return

    level = websocket.query_params.get("level", "info")
    await websocket.accept()
    try:
        async for linea in esl.stream_logs(level):
            await websocket.send_text(_ocultar_secretos(linea))
    except WebSocketDisconnect:
        pass
    except (OSError, ConnectionError, asyncio.TimeoutError) as exc:
        # FreeSWITCH no alcanzable (todavía arrancando, reiniciándose o
        # caído). Es esperable y el navegador reintenta cada 2s, así que
        # se registra UNA línea corta y no un traceback: con la consola
        # abierta durante un arranque en frío esto llenaba el log con
        # ~10 tracebacks seguidos, y con FreeSWITCH caído un rato los
        # errores de verdad quedaban enterrados debajo.
        logger.warning("Consola de logs: FreeSWITCH no disponible (%s)", exc.__class__.__name__)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    except Exception:
        # Cualquier otra cosa sí es inesperada y se quiere el traceback.
        logger.exception("Consola de logs: error en el stream para %s", usuario.username)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
