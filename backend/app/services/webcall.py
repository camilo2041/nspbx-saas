"""Registro efímero de las llamadas web (widget "hablar con un agente").

Un visitante anónimo de un sitio web pide una credencial SIP temporal por
`POST /api/webcall/session`; con ella su navegador se registra en
FreeSWITCH y entra a UNA cola de call center. No hay tabla en Postgres: el
registro vive en memoria de este proceso (uvicorn corre un solo worker),
se limpia solo por expiración y se pierde en un reinicio del backend —
aceptable, una llamada web dura minutos y este contenedor casi no
reinicia; si pasara, el visitante vuelve a tocar el botón.

Este registro es GLOBAL al proceso, no por empresa: hay un solo
FreeSWITCH compartido para toda la plataforma (ver
docs/arquitectura-multitenant.md), y por ahora el widget solo está
cableado a tenant_id=1 (ver app/api/webcall.py). El día que se generalice
a varias empresas con webcall activo, el aislamiento entre ellas lo va a
dar el CONTEXTO de dialplan (`webcall_<slug>`, ver
services/config_generator.py) — cada credencial nace ya sabiendo a qué
contexto pertenece (user_context en el directorio), así que este registro
no necesita saber de qué empresa es cada sesión para mantenerlas separadas.

El aislamiento anti-fraude NO está acá: lo da el contexto de dialplan
`webcall_<slug>` (ver services/config_generator.py), que solo sabe llegar
a esa cola. Aunque se filtre una credencial, no sirve para marcar a ningún
lado más.
"""

import asyncio
import re
import secrets
import time
from dataclasses import dataclass

from app.core.clock import now_local

# El navegador hace INVITE a este destino fijo; el contexto `webcall_<slug>`
# lo mapea a la cola configurada. El visitante no marca nada.
TARGET = "webqueue"

# Patrón de los usuarios invitados. Se valida en el endpoint de directorio
# (services/xml_endpoints.py) antes de devolver una credencial dinámica.
GUEST_RE = re.compile(r"^web\d{6,12}$")

_REGISTER_TTL = 120        # segundos para registrarse antes de reclamar el cupo
_SESSION_MAX = 35 * 60     # tope duro de una sesión web
_RATE_WINDOW = 600         # ventana del rate-limit por IP (segundos)
_RATE_MAX = 5              # sesiones por IP dentro de la ventana

DIAS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class GuestSession:
    username: str
    password: str
    created: float
    ip: str
    registered: bool = False


class WebcallRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, GuestSession] = {}
        self._by_ip: dict[str, list[float]] = {}

    def _prune_locked(self) -> None:
        ahora = time.time()
        for user, s in list(self._sessions.items()):
            edad = ahora - s.created
            if edad > _SESSION_MAX or (not s.registered and edad > _REGISTER_TTL):
                del self._sessions[user]

    async def sweep(self) -> None:
        """Barrido periódico (lo llama el MaintenanceWorker). Libera cupos
        de sesiones abandonadas que el navegador nunca cerró."""
        async with self._lock:
            self._prune_locked()
            corte = time.time() - _RATE_WINDOW
            for ip in list(self._by_ip):
                self._by_ip[ip] = [t for t in self._by_ip[ip] if t > corte]
                if not self._by_ip[ip]:
                    del self._by_ip[ip]

    async def rate_ok(self, ip: str) -> bool:
        async with self._lock:
            ahora = time.time()
            recientes = [t for t in self._by_ip.get(ip, []) if ahora - t < _RATE_WINDOW]
            self._by_ip[ip] = recientes
            return len(recientes) < _RATE_MAX

    async def active_count(self) -> int:
        async with self._lock:
            self._prune_locked()
            return len(self._sessions)

    async def create(self, ip: str) -> GuestSession:
        async with self._lock:
            self._prune_locked()
            username = "web" + "".join(secrets.choice("0123456789") for _ in range(9))
            s = GuestSession(
                username=username,
                password=secrets.token_urlsafe(18),
                created=time.time(),
                ip=ip,
            )
            self._sessions[username] = s
            self._by_ip.setdefault(ip, []).append(time.time())
            return s

    async def get(self, username: str) -> GuestSession | None:
        """Lo usa el endpoint de directorio en cada lookup de FreeSWITCH.
        Un lookup cuenta como "se usó la credencial": marca la sesión como
        registrada para que no se la lleve la expiración corta."""
        async with self._lock:
            self._prune_locked()
            s = self._sessions.get(username)
            if s and not s.registered:
                s.registered = True
            return s

    async def end(self, username: str) -> None:
        async with self._lock:
            self._sessions.pop(username, None)


registry = WebcallRegistry()


def parse_schedule(raw: str | None) -> dict[str, tuple[str, str]]:
    """`raw` es JSON `{"mon": ["08:00","18:00"], ...}`. Claves ausentes =
    cerrado ese día. `None`/vacío = abierto siempre."""
    import json

    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for dia in DIAS:
        v = data.get(dia)
        if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, str) for x in v):
            out[dia] = (v[0], v[1])
    return out


def is_open(raw_schedule: str | None, ahora: object | None = None) -> bool:
    horario = parse_schedule(raw_schedule)
    if not horario:  # sin horario configurado => 24/7
        return True
    momento = ahora or now_local()
    dia = DIAS[momento.weekday()]
    rango = horario.get(dia)
    if not rango:
        return False
    try:
        h, m = momento.hour, momento.minute
        actual = h * 60 + m
        ini_h, ini_m = (int(x) for x in rango[0].split(":"))
        fin_h, fin_m = (int(x) for x in rango[1].split(":"))
        return ini_h * 60 + ini_m <= actual < fin_h * 60 + fin_m
    except (ValueError, AttributeError):
        return True


SESSION_MAX = _SESSION_MAX
