"""Contraseñas y tokens de sesión.

Se usa PBKDF2-HMAC-SHA256 de la librería estándar en vez de bcrypt/argon2
para no meter dependencias compiladas en la imagen: el costo de construir
el contenedor sube y el beneficio, con 480.000 iteraciones, es marginal
para un panel interno.

El token es un JWT firmado con HS256. La clave sale de `AUTH_SECRET`; si
no está definida se genera una al azar en el arranque, lo que invalida las
sesiones en cada reinicio — molesto pero seguro. Nunca se usa una clave
por defecto fija: sería la misma en todas las instalaciones y cualquiera
podría firmar un token de admin.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

logger = logging.getLogger(__name__)

ALGORITMO = "HS256"
# Ocho horas: cubre un turno completo sin obligar a volver a entrar a media
# jornada, y no deja sesiones abiertas de un día para el otro.
HORAS_DE_SESION = 8

# Vida del refresh token de la app móvil. A diferencia del JWT de 8h, este
# SÍ se puede revocar (vive en la tabla `refresh_tokens`, no solo firmado),
# así que puede durar semanas sin el mismo riesgo: cerrar sesión o
# desactivar al usuario lo invalida al instante, no hay que esperar a que
# venza. 30 días alcanza para no pedirle contraseña de nuevo a alguien que
# usa la app todos los días, sin dejarla viva indefinidamente en un
# teléfono perdido.
DIAS_DE_REFRESH = 30

_ITERACIONES = 480_000


def _clave() -> str:
    valor = os.getenv("AUTH_SECRET", "").strip()
    if valor:
        return valor
    global _CLAVE_EFIMERA
    if _CLAVE_EFIMERA is None:
        _CLAVE_EFIMERA = secrets.token_urlsafe(48)
        logger.warning(
            "AUTH_SECRET no está definida: se generó una clave temporal. "
            "Las sesiones se cerrarán en cada reinicio del backend."
        )
    return _CLAVE_EFIMERA


_CLAVE_EFIMERA: str | None = None


def hash_password(password: str) -> str:
    """Devuelve `pbkdf2_sha256$iteraciones$sal$hash`, todo en base64."""
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), sal, _ITERACIONES)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"pbkdf2_sha256${_ITERACIONES}${b64(sal)}${b64(dk)}"


def verificar_password(password: str, almacenado: str) -> bool:
    """Compara en tiempo constante para no filtrar el hash por temporización."""
    try:
        algoritmo, iteraciones, sal_b64, hash_b64 = almacenado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(sal_b64), int(iteraciones)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, base64.b64decode(hash_b64))


def crear_token(user_id: int, rol: str, tenant_id: int | None = None) -> tuple[str, int]:
    """Token de sesión. Devuelve `(token, segundos_de_vida)`.

    La empresa (`tid`) viaja FIRMADA dentro del token en vez de buscarse
    en la base en cada petición, y eso rompe un círculo: las tablas están
    protegidas por empresa, así que para consultarlas hay que declarar
    primero cuál es — pero averiguarlo leyendo `users` sería otra
    consulta protegida. Viniendo del token, se sabe antes de tocar la
    base.

    `None` = usuario de la plataforma, sin empresa propia.
    """
    vence = datetime.now(timezone.utc) + timedelta(hours=HORAS_DE_SESION)
    token = jwt.encode(
        {"sub": str(user_id), "rol": rol, "tid": tenant_id, "exp": vence},
        _clave(),
        algorithm=ALGORITMO,
    )
    return token, HORAS_DE_SESION * 3600


def generar_refresh_token() -> tuple[str, str, datetime]:
    """Nuevo refresh token: `(token_en_claro, hash_para_guardar, vencimiento)`.

    Solo el hash va a la base (mismo criterio que `hash_password`): un
    volcado de la tabla no debe alcanzar para hacerse pasar por nadie.
    """
    token = secrets.token_urlsafe(48)
    vence = datetime.now(timezone.utc) + timedelta(days=DIAS_DE_REFRESH)
    return token, hash_refresh_token(token), vence


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def leer_token(token: str) -> dict | None:
    """Devuelve el contenido del token, o None si no sirve.

    Un token vencido, alterado o firmado con otra clave cae acá como None:
    quien lo llama responde 401 sin distinguir el motivo, para no darle
    pistas a quien esté probando tokens.
    """
    try:
        return jwt.decode(token, _clave(), algorithms=[ALGORITMO])
    except jwt.PyJWTError:
        return None
