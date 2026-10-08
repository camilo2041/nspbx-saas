"""Licencia firmada de una instalación local (docs/plan-fase-k.md).

La central arma un documento JSON con la empresa (nombre, tipo, módulos) y
su licencia (plan, estado, vencimiento, topes) y lo firma con su clave
PRIVADA Ed25519. La instalación local lo verifica con la clave PÚBLICA y
solo entonces lo aplica: una base editada a mano, o un documento retocado,
no pasan la verificación.

El documento se firma tal como viaja (texto canónico: claves ordenadas, sin
espacios). La instalación guarda ese mismo texto y su firma, y los vuelve a
verificar cada vez que los usa.

Fechas: siempre en UTC con sufijo Z. Cada lado las pasa a su hora local
al comparar (la central y el cliente pueden estar en zonas distintas).
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from app.core.clock import business_tz

VERSION_DOCUMENTO = 1
# Sin 0/O ni 1/I/L: el código se dicta por teléfono.
_ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
VIGENCIA_CODIGO = timedelta(days=7)
# Topes de la licencia que viajan en el documento (los de services/licensing.py).
RECURSOS = (
    "max_extensions", "max_trunks", "max_concurrent_calls", "max_campaigns", "max_outbound_minutes_day",
    "max_outbound_cps",
)


class LicenciaInvalida(Exception):
    """Firma que no corresponde, documento mal formado o clave ausente."""


# --- Claves ---------------------------------------------------------------------------


def generar_par() -> tuple[str, str]:
    """(privada, pública) en base64 de sus 32 bytes crudos."""
    privada = Ed25519PrivateKey.generate()
    crudo_priv = privada.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    crudo_pub = privada.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(crudo_priv).decode(), base64.b64encode(crudo_pub).decode()


def _privada(clave_b64: str) -> Ed25519PrivateKey:
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(clave_b64, validate=True))
    except Exception:
        raise LicenciaInvalida("LICENCIA_CLAVE_PRIVADA no es una clave Ed25519 válida (32 bytes en base64)")


def _publica(clave_b64: str) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(clave_b64, validate=True))
    except Exception:
        raise LicenciaInvalida("LICENCIA_CLAVE_PUBLICA no es una clave Ed25519 válida (32 bytes en base64)")


def publica_de(privada_b64: str) -> str:
    crudo = _privada(privada_b64).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(crudo).decode()


# --- Firma ----------------------------------------------------------------------------


def canonico(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def firmar(doc: dict, privada_b64: str) -> dict:
    """{"documento": texto canónico, "firma": base64}."""
    if not privada_b64:
        raise LicenciaInvalida("Esta central no tiene LICENCIA_CLAVE_PRIVADA: no puede emitir licencias")
    texto = canonico(doc)
    firma = _privada(privada_b64).sign(texto.encode())
    return {"documento": texto, "firma": base64.b64encode(firma).decode()}


def verificar(texto: str, firma_b64: str, publica_b64: str) -> dict:
    """El documento si la firma corresponde; si no, LicenciaInvalida."""
    if not publica_b64:
        raise LicenciaInvalida("Falta LICENCIA_CLAVE_PUBLICA: no hay con qué verificar la licencia")
    try:
        firma = base64.b64decode(firma_b64 or "", validate=True)
    except Exception:
        raise LicenciaInvalida("La firma de la licencia no es base64")
    try:
        _publica(publica_b64).verify(firma, (texto or "").encode())
    except InvalidSignature:
        raise LicenciaInvalida("La firma de la licencia no corresponde: el documento fue alterado o no es de la central")
    try:
        doc = json.loads(texto)
    except ValueError:
        raise LicenciaInvalida("La licencia no es JSON")
    if not isinstance(doc, dict) or doc.get("version") != VERSION_DOCUMENTO:
        raise LicenciaInvalida("Versión de licencia desconocida: actualiza la instalación")
    for clave in ("instalacion_id", "empresa", "licencia", "emitida", "valida_hasta"):
        if clave not in doc:
            raise LicenciaInvalida(f"A la licencia le falta «{clave}»")
    return doc


# --- Fechas ---------------------------------------------------------------------------


def a_utc_iso(dt: datetime | None) -> str | None:
    """Fecha naive en hora del negocio (como se guardan) → ISO UTC con Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=business_tz())
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def de_utc_iso(texto: str | None) -> datetime | None:
    """ISO UTC → naive en hora del negocio de ESTE servidor."""
    if not texto:
        return None
    dt = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(business_tz()).replace(tzinfo=None)


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# --- Códigos y tokens -----------------------------------------------------------------


def nuevo_codigo() -> str:
    """NSPBX-XXXX-XXXX-XXXX: se dicta y se escribe sin confundir letras."""
    grupos = ["".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(4)) for _ in range(3)]
    return "NSPBX-" + "-".join(grupos)


def normalizar_codigo(codigo: str) -> str:
    limpio = "".join(c for c in (codigo or "").upper() if c.isalnum())
    if limpio.startswith("NSPBX"):
        limpio = limpio[5:]
    return limpio


def hash_secreto(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def hash_codigo(codigo: str) -> str:
    return hash_secreto("codigo:" + normalizar_codigo(codigo))


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


# --- Documento ------------------------------------------------------------------------


def documento(instalacion, empresa, lic, gracia_horas: int, limites: dict[str, int | None]) -> dict:
    """El documento de la licencia de `instalacion` (sin firmar).

    Una instalación suspendida o revocada recibe su licencia con estado
    `suspended`: la aplica como cualquier otra y deja de operar."""
    emitida = ahora_utc()
    estado = lic.status if lic else "trial"
    if instalacion.estado in ("suspendida", "revocada"):
        estado = "suspended"
    return {
        "version": VERSION_DOCUMENTO,
        "instalacion_id": instalacion.id,
        "empresa": {
            "nombre": empresa.name,
            "slug": empresa.slug,
            "business_type": empresa.business_type,
            "modules": empresa.modules_list,
        },
        "licencia": {
            "plan": lic.plan if lic else "trial",
            "status": estado,
            "expires_at": a_utc_iso(lic.expires_at) if lic else None,
            **{r: limites.get(r) for r in RECURSOS},
        },
        "emitida": emitida.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valida_hasta": (emitida + timedelta(hours=gracia_horas)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
