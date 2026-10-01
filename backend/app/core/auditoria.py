"""Registro de auditoría e identificador de petición.

Responde "¿quién hizo esto, cuándo, desde dónde y con qué resultado?"
después de un incidente. Sin esto, la mayoría de los demás controles no se
pueden investigar.

Un middleware ASGI hace dos cosas en cada petición:

1. Le da un `request_id` (o respeta el que llegue en X-Request-ID si es
   razonable), lo devuelve en la respuesta y lo pone en cada línea de log
   que se escriba mientras se atiende. Con eso, un error que reporta un
   usuario se encuentra en los logs.

2. Si la petición MODIFICA algo (POST/PUT/PATCH/DELETE bajo /api/) o es una
   lectura sensible (descargar una grabación), deja una fila en `audit_log`
   con quién, empresa, acción, recurso, campos enviados (sin secretos),
   resultado, IP, navegador y request_id.

Es un middleware y no una llamada en cada endpoint por la misma razón que
la sesión obligatoria es una lista de exclusión: un endpoint nuevo queda
auditado solo, sin que nadie tenga que acordarse.

La tabla es de solo agregar: el rol de la aplicación no tiene UPDATE ni
DELETE sobre ella, y un trigger rechaza cualquier UPDATE, incluso del
dueño (ver main._parches_auditoria).
"""

import contextvars
import json
import logging
import re
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

request_id_actual: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_METODOS_QUE_MODIFICAN = {"POST", "PUT", "PATCH", "DELETE"}
# Lecturas que también se auditan: escuchar o bajar una grabación es acceder
# a un dato personal (la voz de un tercero).
_LECTURAS_SENSIBLES = re.compile(r"^/api/calls/\d+/recording$")
# No se auditan: el widget anónimo de llamada web (mucho volumen, sin
# usuario) y la renovación de sesión de la app móvil (rutinaria).
_EXCLUIDAS = ("/api/webcall/", "/api/auth/refresh")
# Claves cuyo valor nunca se guarda.
_CLAVE_SECRETA = re.compile(r"pass|secret|token|clave|api_?key|apikey|auth|firma|signature|pem|private", re.I)
_MAX_VALOR = 200
_MAX_CUERPO = 64 * 1024


class FiltroRequestId(logging.Filter):
    """Pone `request_id` en cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_actual.get()
        return True


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Formato con request_id. `LOG_FORMATO=json` lo emite como JSON, una
    línea por evento, para un recolector de logs."""
    import os

    manejador = logging.StreamHandler()
    manejador.addFilter(FiltroRequestId())
    if os.getenv("LOG_FORMATO", "").lower() == "json":
        manejador.setFormatter(_FormatoJson())
    else:
        manejador.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
        )
    raiz = logging.getLogger()
    raiz.handlers[:] = [manejador]
    raiz.setLevel(nivel)


class _FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z",
            "nivel": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "mensaje": record.getMessage(),
        }
        if record.exc_info:
            datos["error"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def ocultar_secretos(valor, profundidad: int = 0):
    """Copia de `valor` con los secretos reemplazados por "***" y los textos
    largos recortados."""
    if profundidad > 4:
        return "…"
    if isinstance(valor, dict):
        return {
            str(k)[:60]: ("***" if _CLAVE_SECRETA.search(str(k)) else ocultar_secretos(v, profundidad + 1))
            for k, v in list(valor.items())[:50]
        }
    if isinstance(valor, list):
        resto = len(valor) - 20
        salida = [ocultar_secretos(v, profundidad + 1) for v in valor[:20]]
        return salida + ([f"… y {resto} más"] if resto > 0 else [])
    if isinstance(valor, str):
        return valor if len(valor) <= _MAX_VALOR else valor[:_MAX_VALOR] + "…"
    return valor


def _detalle(cuerpo: bytes, tipo: str):
    if not cuerpo:
        return None
    if "multipart/form-data" in tipo:
        return {"archivo": f"{len(cuerpo)} bytes"}
    try:
        return ocultar_secretos(json.loads(cuerpo[:_MAX_CUERPO]))
    except (ValueError, UnicodeDecodeError):
        return {"cuerpo": f"{len(cuerpo)} bytes"}


def _resultado(estado: int) -> str:
    if estado < 400:
        return "ok"
    if estado in (401, 402, 403, 404):
        return "denegado"
    if estado < 500:
        return "rechazado"
    return "error"


def _accion(scope: dict) -> str:
    """"PUT /api/trunks/{trunk_id}": la plantilla de la ruta, no la URL, para
    poder agrupar por acción."""
    ruta = scope.get("route")
    plantilla = getattr(ruta, "path", None) or scope.get("path", "")
    return f"{scope.get('method', '?')} {plantilla}"[:120]


def _recurso(scope: dict) -> str | None:
    params = scope.get("path_params") or {}
    if not params:
        return None
    return ",".join(f"{k}={v}" for k, v in params.items())[:120]


def _ip(scope: dict, cabeceras: dict) -> str:
    from app.core.config import settings

    directa = (scope.get("client") or ("?",))[0]
    saltos = settings.proxies_confiables
    if saltos <= 0:
        return directa
    partes = [p.strip() for p in cabeceras.get("x-forwarded-for", "").split(",") if p.strip()]
    return partes[-saltos][:64] if len(partes) >= saltos else directa


async def registrar(
    *,
    accion: str,
    tenant_id: int | None = None,
    usuario_id: int | None = None,
    actor: str | None = None,
    recurso: str | None = None,
    detalle=None,
    resultado: str = "ok",
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> None:
    """Agrega una fila al registro. Nunca hace fallar a quien la llama: si
    la base no responde, queda un ERROR en el log con todo el contenido."""
    from app.core.database import async_session
    from app.models import AuditLog

    fila = AuditLog(
        tenant_id=tenant_id,
        user_id=usuario_id,
        actor=(actor or "")[:100] or None,
        action=accion[:120],
        resource=recurso,
        detail=detalle,
        result=resultado,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:200] or None,
        request_id=request_id or request_id_actual.get(),
    )
    try:
        async with async_session() as session:
            session.add(fila)
            await session.commit()
    except Exception:
        logger.exception(
            "No se pudo guardar la auditoría: %s %s %s %s", accion, actor, recurso, resultado
        )


class MiddlewareAuditoria:
    """ASGI puro (no BaseHTTPMiddleware): lee el cuerpo a medida que la
    aplicación lo consume, sin consumirlo antes ni cargarlo dos veces."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cabeceras = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        entrante = cabeceras.get("x-request-id", "")
        rid = entrante if _REQUEST_ID_RE.fullmatch(entrante) else uuid.uuid4().hex
        token = request_id_actual.set(rid)

        path = scope.get("path", "")
        metodo = scope.get("method", "")
        auditar = path.startswith("/api/") and not path.startswith(_EXCLUIDAS) and (
            metodo in _METODOS_QUE_MODIFICAN or (metodo == "GET" and _LECTURAS_SENSIBLES.match(path))
        )
        cuerpo = bytearray()
        estado = {"codigo": 500}

        async def recibir():
            mensaje = await receive()
            if auditar and mensaje.get("type") == "http.request" and len(cuerpo) < _MAX_CUERPO:
                cuerpo.extend(mensaje.get("body", b"")[: _MAX_CUERPO - len(cuerpo)])
            return mensaje

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                estado["codigo"] = mensaje["status"]
                mensaje.setdefault("headers", [])
                mensaje["headers"] = list(mensaje["headers"]) + [(b"x-request-id", rid.encode())]
            await send(mensaje)

        try:
            await self.app(scope, recibir, enviar)
        finally:
            try:
                if auditar:
                    await self._auditar(scope, cabeceras, bytes(cuerpo), estado["codigo"], rid)
            finally:
                request_id_actual.reset(token)

    async def _auditar(self, scope, cabeceras, cuerpo, codigo, rid):
        estado_req = scope.get("state") or {}
        usuario = estado_req.get("usuario")
        detalle = _detalle(cuerpo, cabeceras.get("content-type", ""))
        tenant_id = usuario_id = None
        actor = None
        if usuario is not None:
            tenant_id, usuario_id, actor = usuario.tenant_id, usuario.id, f"{usuario.username} ({usuario.role})"
        else:
            # Login y rutas sin sesión: quien lo intentó, si se sabe.
            intento = estado_req.get("auditoria_usuario")
            if intento is not None:
                tenant_id, usuario_id, actor = intento.tenant_id, intento.id, intento.username
            elif isinstance(detalle, dict) and isinstance(detalle.get("username"), str):
                actor = detalle["username"]
        await registrar(
            accion=_accion(scope),
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            actor=actor,
            recurso=_recurso(scope),
            detalle=detalle,
            resultado=_resultado(codigo),
            ip=_ip(scope, cabeceras),
            user_agent=cabeceras.get("user-agent"),
            request_id=rid,
        )
