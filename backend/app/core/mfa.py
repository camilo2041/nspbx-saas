"""Verificación en dos pasos (TOTP, RFC 6238).

Lo que usan Google Authenticator, Microsoft Authenticator, 1Password,
Authy…: un secreto compartido y un código de 6 dígitos que cambia cada 30
segundos. Implementado con la librería estándar (hmac, base32), sin
dependencias nuevas, igual que las contraseñas (core/security.py).

Obligatorio para los roles de MFA_OBLIGATORIO (por omisión plataforma y
admin): son los que pueden cambiar troncales, rutas salientes, topes y
empresas. Con la contraseña robada de uno de ellos se hace fraude; con la
contraseña y sin el teléfono, no.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIODO = 30
DIGITOS = 6
# Se acepta el código del intervalo anterior y del siguiente: el reloj del
# teléfono y el del servidor nunca coinciden al segundo.
VENTANA = 1
CODIGOS_RECUPERACION = 8


def nuevo_secreto() -> str:
    """160 bits al azar en base32 (lo que se escribe a mano en la app)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _clave(secreto: str) -> bytes:
    relleno = "=" * (-len(secreto) % 8)
    return base64.b32decode(secreto.upper() + relleno)


def codigo(secreto: str, paso: int) -> str:
    mac = hmac.new(_clave(secreto), struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[desplazamiento : desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10**DIGITOS).zfill(DIGITOS)


def paso_actual(ahora: float | None = None) -> int:
    return int((ahora if ahora is not None else time.time()) // PERIODO)


def verificar(secreto: str, valor: str, ultimo_paso: int | None = None, ahora: float | None = None) -> int | None:
    """El paso que corresponde a `valor`, o None si no es válido.

    `ultimo_paso` es el del último código aceptado: un código ya usado (o
    uno anterior) se rechaza, para que no sirva capturarlo y reusarlo."""
    valor = (valor or "").strip().replace(" ", "")
    if not secreto or len(valor) != DIGITOS or not valor.isdigit():
        return None
    actual = paso_actual(ahora)
    for paso in range(actual - VENTANA, actual + VENTANA + 1):
        if ultimo_paso is not None and paso <= ultimo_paso:
            continue
        if hmac.compare_digest(codigo(secreto, paso), valor):
            return paso
    return None


def uri(secreto: str, cuenta: str, emisor: str = "NSPBX") -> str:
    """otpauth:// que las apps entienden (pegado o como QR)."""
    etiqueta = quote(f"{emisor}:{cuenta}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(emisor)}&digits={DIGITOS}&period={PERIODO}"


def nuevos_codigos_recuperacion() -> list[str]:
    """Códigos de un solo uso para entrar si se pierde el teléfono."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"  # sin 0/o/1/l/i
    return [
        "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(2))
        for _ in range(CODIGOS_RECUPERACION)
    ]


def hash_recuperacion(codigo_recuperacion: str) -> str:
    return hashlib.sha256(codigo_recuperacion.strip().lower().encode()).hexdigest()


def roles_obligatorios() -> set[str]:
    from app.core.config import settings

    return {r.strip() for r in settings.mfa_obligatorio.split(",") if r.strip()}


def le_falta_mfa(usuario) -> bool:
    """¿Su rol exige MFA y todavía no lo activó?"""
    return usuario.role in roles_obligatorios() and not usuario.mfa_enabled
