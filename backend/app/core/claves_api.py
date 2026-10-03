"""Claves de la API pública (/api/v1).

Para integrar sistemas de la empresa (su CRM, su agenda, su ERP) sin
prestarles un usuario del panel. Cada clave:

- es de UNA empresa: al autenticar, la sesión queda atada a esa empresa
  igual que con un usuario, así que RLS y el filtro del código aplican;
- tiene permisos limitados (`ESCOPOS`): una clave para leer llamadas no
  puede cargar números a una campaña;
- vale solo en /api/v1, y /api/v1 solo acepta claves. Un token de sesión no
  entra a la API pública ni una clave al panel: si se filtra una, el daño
  queda dentro de lo que esa clave podía hacer;
- se guarda como SHA-256 (es aleatoria y larga: no hace falta un hash lento),
  se puede revocar y puede vencer;
- tiene un tope de peticiones por minuto, para que una integración con un
  bucle mal hecho no tumbe la API de todos.

Formato: nspbx_<prefijo>_<secreto>. El prefijo identifica la clave en el
panel y en la auditoría sin revelarla.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session, fijar_tenant

ESCOPOS = {
    "llamadas:leer": "Leer el registro de llamadas",
    "citas:leer": "Leer la agenda",
    "citas:escribir": "Crear citas",
    "campanas:escribir": "Cargar números a campañas",
    "consumo:leer": "Leer el consumo mensual",
    "contactos:leer": "Buscar contactos del CRM",
    "contactos:escribir": "Crear y actualizar contactos del CRM",
    "leads:leer": "Consultar el estado y la disposición de los leads",
    "callbacks:escribir": "Agendar volver a llamar a un lead",
}

_PREFIJO_CLAVE = "nspbx_"
_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Clave de API inválida",
    headers={"WWW-Authenticate": "Bearer"},
)


def generar() -> tuple[str, str, str]:
    """(clave completa, prefijo, hash). La clave se muestra una sola vez."""
    prefijo = secrets.token_hex(4)
    clave = f"{_PREFIJO_CLAVE}{prefijo}_{secrets.token_urlsafe(32)}"
    return clave, prefijo, hash_de(clave)


def hash_de(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def _clave_de(request) -> str | None:
    cabecera = request.headers.get("Authorization", "")
    if cabecera.startswith("Bearer "):
        return cabecera[7:].strip()
    return request.headers.get("X-API-Key", "").strip() or None


class _Limitador:
    """Ventana deslizante de un minuto por clave, en memoria del proceso."""

    def __init__(self):
        self._golpes: dict[str, deque] = defaultdict(deque)

    def permitir(self, prefijo: str, limite: int) -> int:
        """0 si pasa; si no, los segundos que faltan para que pase."""
        ahora = time.monotonic()
        golpes = self._golpes[prefijo]
        while golpes and golpes[0] <= ahora - 60:
            golpes.popleft()
        if len(golpes) >= limite:
            return max(1, int(60 - (ahora - golpes[0])) + 1)
        golpes.append(ahora)
        return 0

    def reiniciar(self) -> None:
        self._golpes.clear()


limitador = _Limitador()


async def autenticar(request, session) -> None:
    """Valida la clave de la petición, ata `session` a su empresa y deja la
    clave en `request.state.api_key`. Lanza 401/403/429."""
    from app.models import ApiKey, Tenant

    clave = _clave_de(request)
    if not clave or not clave.startswith(_PREFIJO_CLAVE) or clave.count("_") < 2:
        raise _NO_AUTENTICADO
    prefijo = clave[len(_PREFIJO_CLAVE):].split("_", 1)[0]
    # Sesión del dueño: todavía no se sabe de qué empresa es (como el login).
    async with async_session() as admin:
        fila = (await admin.execute(select(ApiKey).where(ApiKey.prefix == prefijo))).scalar_one_or_none()
        if fila is None or not hmac.compare_digest(fila.key_hash, hash_de(clave)):
            raise _NO_AUTENTICADO
        ahora = datetime.utcnow()
        if fila.revoked_at is not None or (fila.expires_at is not None and fila.expires_at <= ahora):
            raise _NO_AUTENTICADO
        empresa = await admin.get(Tenant, fila.tenant_id)
        if not empresa or not empresa.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La empresa está desactivada")
        espera = limitador.permitir(prefijo, settings.api_limite_por_minuto)
        if espera:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas peticiones con esta clave",
                headers={"Retry-After": str(espera)},
            )
        # Una escritura por minuto como mucho, no una por petición.
        if fila.last_used_at is None or fila.last_used_at < ahora - timedelta(minutes=1):
            fila.last_used_at = ahora
            await admin.commit()
        admin.expunge(fila)
    fijar_tenant(session, fila.tenant_id)
    request.state.api_key = fila


def requiere_scope(scope: str):
    """Dependencia de los endpoints de /api/v1."""
    assert scope in ESCOPOS, scope

    async def comprobar(request: Request):
        fila = getattr(request.state, "api_key", None)
        if fila is None:
            raise _NO_AUTENTICADO
        if scope not in fila.scope_list:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"La clave no tiene el permiso {scope}")
        return fila

    return comprobar
