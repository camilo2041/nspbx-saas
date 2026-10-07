"""Registro de las llamadas web (widget "hablar con un agente").

Un visitante anónimo de un sitio web pide una credencial SIP temporal por
`POST /api/webcall/session`; con ella su navegador se registra en
FreeSWITCH y entra a UNA cola de call center. Las sesiones viven en la tabla
`webcall_sesiones` (antes, en memoria de un solo proceso: con varias
réplicas del backend, el directorio de FreeSWITCH le preguntaba a una que no
la había creado y el visitante no podía registrarse). Se limpian solas por
expiración (`sweep`, desde el MaintenanceWorker).

Cada sesión recuerda su empresa (`tenant_id`): de ahí salen el dominio y
el contexto `webcall_<slug>` que le arma el directorio (ver
services/xml_endpoints.py) y el tope de llamadas simultáneas, que es por
empresa.

El aislamiento anti-fraude NO está acá: lo da el contexto de dialplan
`webcall_<slug>` (ver services/config_generator.py), que solo sabe llegar
a esa cola. Aunque se filtre una credencial, no sirve para marcar a ningún
lado más.
"""

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
    tenant_id: int
    registered: bool = False


class WebcallRegistry:
    """Sesiones en Postgres, con la sesión del dueño: el endpoint de
    directorio y el widget no tienen usuario ni empresa fijada."""

    @staticmethod
    def _vigente(ahora: float):
        from sqlalchemy import and_, or_

        from app.models import SesionWebcall as S

        return and_(
            S.terminada.is_(False),
            S.creada > ahora - _SESSION_MAX,
            or_(S.registrada.is_(True), S.creada > ahora - _REGISTER_TTL),
        )

    async def sweep(self) -> None:
        """Barrido periódico (lo llama el MaintenanceWorker). Borra lo que ya
        no está vigente ni cuenta para el límite por IP."""
        from sqlalchemy import delete, not_

        from app.core.database import async_session
        from app.models import SesionWebcall as S

        ahora = time.time()
        async with async_session() as session:
            await session.execute(
                delete(S).where(not_(self._vigente(ahora)), S.creada < ahora - _RATE_WINDOW)
            )
            await session.commit()

    async def rate_ok(self, ip: str) -> bool:
        from sqlalchemy import func, select

        from app.core.database import async_session
        from app.models import SesionWebcall as S

        async with async_session() as session:
            n = (
                await session.execute(
                    select(func.count()).select_from(S).where(S.ip == ip, S.creada > time.time() - _RATE_WINDOW)
                )
            ).scalar_one()
        return n < _RATE_MAX

    async def active_count(self, tenant_id: int) -> int:
        from sqlalchemy import func, select

        from app.core.database import async_session
        from app.models import SesionWebcall as S

        async with async_session() as session:
            return (
                await session.execute(
                    select(func.count()).select_from(S).where(S.tenant_id == tenant_id, self._vigente(time.time()))
                )
            ).scalar_one()

    async def create(self, ip: str, tenant_id: int) -> GuestSession:
        from app.core.database import async_session
        from app.models import SesionWebcall

        s = GuestSession(
            username="web" + "".join(secrets.choice("0123456789") for _ in range(9)),
            password=secrets.token_urlsafe(18),
            created=time.time(),
            ip=ip[:64],
            tenant_id=tenant_id,
        )
        async with async_session() as session:
            session.add(SesionWebcall(username=s.username, tenant_id=tenant_id, password=s.password, ip=s.ip,
                                      creada=s.created))
            await session.commit()
        return s

    async def get(self, username: str) -> GuestSession | None:
        """Lo usa el endpoint de directorio en cada lookup de FreeSWITCH.
        Un lookup cuenta como "se usó la credencial": marca la sesión como
        registrada para que no se la lleve la expiración corta."""
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models import SesionWebcall as S

        async with async_session() as session:
            fila = (
                await session.execute(select(S).where(S.username == username, self._vigente(time.time())))
            ).scalar_one_or_none()
            if fila is None:
                return None
            if not fila.registrada:
                fila.registrada = True
                await session.commit()
            return GuestSession(fila.username, fila.password, fila.creada, fila.ip, fila.tenant_id, True)

    async def end(self, username: str) -> None:
        from sqlalchemy import update

        from app.core.database import async_session
        from app.models import SesionWebcall as S

        async with async_session() as session:
            await session.execute(update(S).where(S.username == username).values(terminada=True))
            await session.commit()


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
