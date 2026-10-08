"""Cifrado de secretos guardados en la base (claves de proveedores,
contraseñas de troncales y extensiones, secreto de MFA).

Sin esto, un volcado de la base —un respaldo filtrado, un acceso de
lectura a Postgres, un error que imprima una fila— entregaba en claro las
claves de ElevenLabs/Deepgram/LLM de cada empresa y las contraseñas de sus
troncales, que es lo que permite hacer fraude a nombre de ellas.

- AES-256-GCM con la clave de DATA_ENCRYPTION_KEY (32 bytes en base64).
  Es una clave PROPIA y no se deriva de AUTH_SECRET: el runbook de
  credencial filtrada manda rotar AUTH_SECRET, y eso dejaría ilegibles
  todos los secretos guardados.
- Formato: "enc:v1:" + base64(nonce de 12 bytes + texto cifrado). Un valor
  sin ese prefijo es de antes del cifrado: se lee tal cual, y el arranque
  lo cifra (`cifrar_pendientes`).
- Rotación: con DATA_ENCRYPTION_KEY_ANTERIOR, lo cifrado con la clave vieja
  se sigue leyendo y el arranque lo vuelve a cifrar con la nueva.
- Guardar la clave junto con la de los respaldos off-site: sin ella, una
  base restaurada tiene estos secretos ilegibles (hay que volver a
  cargarlos), aunque todo lo demás funcione.
"""

import base64
import binascii
import logging
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

PREFIJO = "enc:v1:"
_NONCE = 12


def _clave_de(texto: str | None) -> bytes | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        # validate=True: sin esto, los caracteres inválidos se descartan en
        # silencio y una clave mal copiada se "acepta" con otro valor.
        clave = base64.b64decode(texto + "=" * (-len(texto) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise RuntimeError("DATA_ENCRYPTION_KEY no es base64 válido") from None
    if len(clave) != 32:
        raise RuntimeError(f"DATA_ENCRYPTION_KEY debe tener 32 bytes (tiene {len(clave)})")
    return clave


def clave_actual() -> bytes | None:
    return _clave_de(os.getenv("DATA_ENCRYPTION_KEY"))


def _claves_para_leer() -> list[bytes]:
    return [c for c in (clave_actual(), _clave_de(os.getenv("DATA_ENCRYPTION_KEY_ANTERIOR"))) if c]


def nueva_clave() -> str:
    """Para generar DATA_ENCRYPTION_KEY (lo usa scripts/setup.sh)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def cifrar(valor: str | None) -> str | None:
    """Sin clave configurada devuelve el valor tal cual: solo pasa en
    desarrollo, porque en producción el arranque exige la clave (ver
    core/arranque.py)."""
    if valor is None or valor == "" or valor.startswith(PREFIJO):
        return valor
    clave = clave_actual()
    if clave is None:
        return valor
    nonce = secrets.token_bytes(_NONCE)
    datos = AESGCM(clave).encrypt(nonce, valor.encode(), None)
    return PREFIJO + base64.b64encode(nonce + datos).decode()


def descifrar(valor: str | None) -> str | None:
    if not valor or not valor.startswith(PREFIJO):
        return valor
    try:
        crudo = base64.b64decode(valor[len(PREFIJO):])
    except (binascii.Error, ValueError):
        logger.error("Secreto cifrado corrupto en la base")
        return None
    if len(crudo) <= _NONCE:
        logger.error("Secreto cifrado corrupto en la base")
        return None
    for clave in _claves_para_leer():
        try:
            return AESGCM(clave).decrypt(crudo[:_NONCE], crudo[_NONCE:], None).decode()
        except (InvalidTag, ValueError):
            continue
    # Clave equivocada o perdida: se devuelve None (como si no estuviera
    # cargado) y no el texto cifrado, que algún cliente podría mandar como
    # si fuera la clave.
    logger.error("No se pudo descifrar un secreto: DATA_ENCRYPTION_KEY no coincide con la que lo cifró")
    return None


def cifrado_con_clave_actual(valor: str | None) -> bool:
    if not valor or not valor.startswith(PREFIJO):
        return False
    clave = clave_actual()
    if clave is None:
        return False
    try:
        crudo = base64.b64decode(valor[len(PREFIJO):])
        if len(crudo) <= _NONCE:
            return False
        AESGCM(clave).decrypt(crudo[:_NONCE], crudo[_NONCE:], None)
        return True
    except (InvalidTag, binascii.Error, ValueError):
        return False


class TextoCifrado(TypeDecorator):
    """Columna de texto que se guarda cifrada y se lee en claro.

    No sirve para comparar en un WHERE (cada cifrado usa un nonce al azar):
    se compara en Python después de leer, como ya hace el secreto del
    agente de IA."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return cifrar(value)

    def process_result_value(self, value, dialect):
        return descifrar(value)


# Columnas cifradas: (tabla, columna). Las usa `cifrar_pendientes` y la
# revisión 0002.
COLUMNAS = [
    ("trunks", "password"),
    ("extensions", "password"),
    ("system_settings", "fs_esl_password"),
    ("system_settings", "elevenlabs_api_key"),
    ("system_settings", "agent_webhook_secret"),
    ("system_settings", "ai_llm_api_key"),
    ("system_settings", "deepgram_api_key"),
    ("system_settings", "ari_password"),
    ("system_settings", "webcall_turnstile_secret"),
    ("users", "mfa_secret"),
    ("webhooks", "secreto"),
    ("campaigns", "crm_secreto"),
    ("nodos_freeswitch", "esl_password"),
    ("licencia_local", "token"),
]


def cifrar_pendientes(conexion) -> int:
    """Cifra con la clave actual lo que esté en claro o con la anterior.
    Idempotente; corre en cada arranque (ver main.migrar). Conexión
    síncrona del dueño. Devuelve cuántos valores reescribió."""
    from sqlalchemy import text

    if clave_actual() is None:
        return 0
    total = 0
    for tabla, columna in COLUMNAS:
        filas = conexion.execute(
            text(f"SELECT id, {columna} FROM {tabla} WHERE {columna} IS NOT NULL AND {columna} <> ''")
        ).all()
        for id_, valor in filas:
            if cifrado_con_clave_actual(valor):
                continue
            claro = descifrar(valor)
            if claro is None:
                continue  # ilegible: se deja como está y ya quedó el error en el log
            conexion.execute(
                text(f"UPDATE {tabla} SET {columna} = :v WHERE id = :i"),
                {"v": cifrar(claro), "i": id_},
            )
            total += 1
    if total:
        logger.info("Cifrado de secretos: %d valores cifrados con la clave actual", total)
    return total


# --- Lo que devuelve la API ------------------------------------------------

MASCARA = "••••••"


def enmascarar(valor: str | None) -> str | None:
    """"••••••abcd": se ve que hay algo cargado y cuál, sin entregarlo."""
    if not valor:
        return valor
    return MASCARA + (valor[-4:] if len(valor) > 8 else "")


def es_mascara(valor: str | None) -> bool:
    """El panel reenvía lo que recibió: si es la máscara, no se cambió."""
    return bool(valor) and valor.startswith(MASCARA)
