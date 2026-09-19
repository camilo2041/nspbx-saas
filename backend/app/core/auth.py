"""Autenticación y autorización de la API.

Dos capas separadas a propósito:

1. `sesion_obligatoria` se cuelga de la aplicación entera y exige un token
   válido para TODO lo que cuelgue de /api/. Es una lista de exclusión, no
   de inclusión: una ruta nueva nace protegida y hay que acordarse de
   abrirla, en vez de nacer abierta y depender de que alguien recuerde
   cerrarla. Los olvidos así son la forma habitual de filtrar un panel.

2. `requiere(permiso)` se pone endpoint por endpoint y decide qué puede
   hacer quien ya entró. Ver app/core/permissions.py.
"""

import hmac
import logging

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.config import settings
from app.core.database import async_session, fijar_tenant, get_session
from app.core.security import leer_token
from app.models import Tenant, User

logger = logging.getLogger(__name__)


def verificar_secreto_fs(secret: str | None = None) -> None:
    """Guardia de los endpoints que llama FreeSWITCH server-to-server
    (/fs/directory, /fs/dialplan, /fs/cdr): ninguno puede usar el guardia
    global de sesión porque no hay un usuario detrás, así que se
    autentican con el secreto compartido que FreeSWITCH manda como query
    string (ver freeswitch/conf/autoload_configs/xml_curl.conf.xml y
    json_cdr.conf.xml).

    Vive acá y no en services/xml_endpoints.py porque /fs/cdr, que está
    en api/calls.py, necesita exactamente el mismo control: quedó sin él
    por estar en otro archivo, y cualquiera que alcanzara el puerto del
    backend podía inyectar llamadas falsas en el historial.

    Falla en 403 sin revelar el motivo: para mod_xml_curl es el modo de
    falla seguro (trata el lookup como "no encontrado"), y para el CDR
    hace que FreeSWITCH lo reintente y lo deje en su err-log-dir en vez
    de perderlo.
    """
    if not settings.fs_xml_secret:
        logger.error("FS_XML_SECRET no está configurado: los endpoints /fs/* quedan sin protección")
        raise HTTPException(status_code=403, detail="No configurado")
    if not secret or not hmac.compare_digest(secret, settings.fs_xml_secret):
        raise HTTPException(status_code=403, detail="No autorizado")

# Rutas de /api/ que no llevan token porque se autentican de otra forma o
# porque son el punto de entrada.
#   - /api/auth/login: hay que poder pedir el token sin tenerlo.
#   - /api/appointments/agent/*: las usa el agente de IA con el secreto
#     compartido de Ajustes (cabecera X-Agent-Secret), no con una sesión.
#   - /api/webcall/*: las usa el navegador de un visitante anónimo en el
#     sitio web de un cliente; se defienden con Turnstile + rate-limit +
#     horario + tope global (ver app/api/webcall.py), no con sesión.
# /refresh y /logout se autentican con el refresh token del cuerpo, no con
# el JWT: si exigieran un JWT vigente, el refresh no serviría justo cuando
# hace falta (JWT vencido).
_ABIERTAS = ("/api/auth/login", "/api/auth/refresh", "/api/auth/logout")
_ABIERTAS_PREFIJO = ("/api/appointments/agent/", "/api/webcall/")

_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sesión no válida o expirada",
    headers={"WWW-Authenticate": "Bearer"},
)


def _es_abierta(path: str) -> bool:
    # Todo lo que no sea /api/ queda fuera: los endpoints que consume
    # FreeSWITCH (/fs/cdr, /fs/dialplan, /fs/directory), el websocket del
    # voizbot y /health. Son internos del docker-compose y no pueden
    # presentar un token de usuario.
    if not path.startswith("/api/"):
        return True
    if path in _ABIERTAS:
        return True
    return path.startswith(_ABIERTAS_PREFIJO)


async def sesion_obligatoria(request: HTTPConnection, session: AsyncSession = Depends(get_session)) -> None:
    """Exige token en toda la API y deja el usuario en `request.state`.

    `HTTPConnection` (no `Request`) a propósito: FastAPI también corre
    esta dependencia de app para rutas WebSocket (ej. /ws/logs), que no
    tienen un `Request` HTTP de verdad — pedirlo tipado así hacía que
    CUALQUIER conexión WebSocket reventara con 500 antes de llegar al
    handler, incluso una que se autentica sola por su cuenta (ver
    app/api/logs_ws.py). `HTTPConnection` es la base común a los dos y
    trae `.headers`/`.url`; `.method` es solo de HTTP, de ahí el getattr."""
    if getattr(request, "method", None) == "OPTIONS" or _es_abierta(request.url.path):
        return

    cabecera = request.headers.get("Authorization", "")
    if not cabecera.startswith("Bearer "):
        raise _NO_AUTENTICADO
    datos = leer_token(cabecera[7:].strip())
    if not datos:
        raise _NO_AUTENTICADO

    try:
        user_id = int(datos.get("sub", ""))
    except (TypeError, ValueError):
        raise _NO_AUTENTICADO

    # La empresa se ata a la sesión ANTES de la primera consulta. Las
    # tablas están protegidas por Row-Level Security, así que sin esto la
    # consulta de acá abajo no devolvería ni al propio usuario y todo
    # respondería 401 — un fallo desconcertante, porque el token sería
    # perfectamente válido.
    #
    # El valor sale del token firmado y no de la base, que es lo que
    # evita el círculo (ver security.crear_token). Un token sin `tid` es
    # de la PLATAFORMA: queda sin empresa, y entonces las políticas no
    # devuelven filas de ninguna. Eso es lo correcto — quien administra
    # la plataforma entra por las rutas que usan la sesión del dueño.
    tid = datos.get("tid")
    fijar_tenant(session, tid)
    if tid is None:
        # Usuario de la plataforma: con RLS y sin empresa, la consulta de
        # abajo no lo encontraría. Se busca con la sesión del DUEÑO (sin
        # aislamiento), igual que hace el login — es la única excepción
        # legítima, y el rol `plataforma` solo puede gestionar empresas
        # (ver app/core/permissions.py).
        async with async_session() as admin_sess:
            usuario = (
                (await admin_sess.execute(select(User).where(User.id == user_id)))
                .unique()
                .scalar_one_or_none()
            )
    else:
        usuario = (await session.execute(select(User).where(User.id == user_id))).unique().scalar_one_or_none()
    # Se relee el usuario en cada petición en vez de confiar en el rol que
    # trae el token: si a alguien lo desactivan o le bajan el rol, el
    # cambio hace efecto ya, sin esperar a que venza su sesión.
    if not usuario or not usuario.enabled:
        raise _NO_AUTENTICADO

    # Desactivar una empresa tiene que cortar el acceso de TODOS sus usuarios
    # ya mismo: antes solo dejaba de servirse el dialplan y el panel seguía
    # funcionando con sus sesiones abiertas.
    if usuario.tenant_id is not None:
        empresa = await session.get(Tenant, usuario.tenant_id)
        if not empresa or not empresa.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La empresa está desactivada")

    request.state.usuario = usuario


async def usuario_actual(request: Request) -> User:
    """El usuario de la petición. Solo válido en rutas protegidas."""
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise _NO_AUTENTICADO
    return usuario


def requiere(*permisos: str):
    """Dependencia que exige TODOS los permisos indicados.

        @router.get("", dependencies=[Depends(requiere(permissions.COLAS_GESTIONAR))])
    """

    async def comprobar(usuario: User = Depends(usuario_actual)) -> User:
        faltan = [p for p in permisos if not permissions.puede(usuario.role, p)]
        if faltan:
            logger.info(
                "Acceso denegado: %s (%s) pidió %s", usuario.username, usuario.role, ", ".join(faltan)
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu rol no tiene permiso para esta acción",
            )
        return usuario

    return comprobar


def escribir_requiere(permiso: str):
    """Exige `permiso` solo si la petición modifica algo.

    Se pone una vez a nivel de router y cubre POST/PUT/PATCH/DELETE,
    incluidos los que se agreguen después. Anotar endpoint por endpoint
    funciona igual hasta el día que alguien agrega uno y se olvida.
    """

    async def comprobar(request: Request, usuario: User = Depends(usuario_actual)) -> User:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return usuario
        if not permissions.puede(usuario.role, permiso):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu rol puede consultar esto, pero no modificarlo",
            )
        return usuario

    return comprobar


def requiere_alguno(*permisos: str):
    """Igual que `requiere`, pero basta con uno de los permisos."""

    async def comprobar(usuario: User = Depends(usuario_actual)) -> User:
        if not any(permissions.puede(usuario.role, p) for p in permisos):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu rol no tiene permiso para esta acción",
            )
        return usuario

    return comprobar


def requiere_modulo(modulo: str):
    """Exige que la EMPRESA del usuario tenga el módulo habilitado.

    Es el modelo de "packs" por empresa (ver Tenant.modules): una empresa
    puede tener solo voicebot, solo pbx/call, o el pack completo. Sin esto,
    un módulo no contratado igual se ve en el panel. El usuario de la
    PLATAFORMA (sin empresa) administra empresas y no aplica.
    """

    async def comprobar(usuario: User = Depends(usuario_actual), session: AsyncSession = Depends(get_session)) -> User:
        if usuario.tenant_id is None:
            return usuario
        ten = await session.get(Tenant, usuario.tenant_id)
        if not ten or not ten.has_module(modulo):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu empresa no tiene este módulo activo",
            )
        return usuario

    return comprobar


def licencia_operativa():
    """Bloquea OPERAR (crear, modificar, iniciar) si la licencia de la
    empresa está vencida o suspendida, pero deja VER los datos para que el
    admin sepa el estado. El vencimiento se evalúa en caliente (ver
    app/services/licensing.py)."""
    from app.services.licensing import estado, obtener

    async def comprobar(
        request: Request,
        usuario: User = Depends(usuario_actual),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return usuario
        if usuario.tenant_id is None:
            return usuario  # plataforma: administra, no opera
        lic = await obtener(session, usuario.tenant_id)
        st = estado(lic)
        if st != "ok":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"La licencia de tu empresa está {st}. Renovala para seguir operando.",
            )
        return usuario

    return comprobar
