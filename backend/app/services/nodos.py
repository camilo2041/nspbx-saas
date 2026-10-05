"""Servidores FreeSWITCH y a cuál va cada empresa (opción A de docs/escala.md §4).

- El servidor **principal** es el de siempre (FS_ESL_HOST / Ajustes). Su id es
  `None`: una empresa sin servidor asignado está en el principal, y con un
  solo servidor nada cambia.
- Los **adicionales** están en `nodos_freeswitch`; cada empresa apunta a uno
  con `tenants.nodo_id`.
- Esto se consulta en CADA comando a FreeSWITCH, así que se cachea y se
  refresca cada `REFRESCO_S`, o en el acto cuando la plataforma cambia un
  servidor o la asignación de una empresa (en esta réplica y, por el bus, en
  las demás).
"""

import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

logger = logging.getLogger(__name__)

REFRESCO_S = 30.0


@dataclass(frozen=True)
class Destino:
    host: str
    port: int
    password: str


@dataclass(frozen=True)
class Nodo:
    id: int
    nombre: str
    destino: Destino
    sip_host: str
    capacidad_agentes: int
    activo: bool


class Directorio:
    def __init__(self):
        self.nodos: dict[int, Nodo] = {}
        self.empresa_nodo: dict[int, int] = {}
        self._cargado = 0.0

    async def refrescar(self, forzar: bool = False) -> None:
        if not forzar and time.monotonic() - self._cargado < REFRESCO_S:
            return
        from app.core.database import async_session
        from app.models import NodoFreeswitch, Tenant

        async with async_session() as dueno:
            nodos = (await dueno.execute(select(NodoFreeswitch))).scalars().all()
            asignadas = (await dueno.execute(select(Tenant.id, Tenant.nodo_id).where(Tenant.nodo_id.is_not(None)))).all()
        self.nodos = {
            n.id: Nodo(n.id, n.nombre, Destino(n.esl_host, n.esl_port, n.esl_password or ""), n.sip_host,
                       n.capacidad_agentes, n.activo)
            for n in nodos
        }
        self.empresa_nodo = {tid: nid for tid, nid in asignadas}
        self._cargado = time.monotonic()

    def invalidar(self, avisar: bool = True) -> None:
        self._cargado = 0.0
        if avisar:
            from app.services.bus import bus

            bus.emitir_pronto("nodos", {})

    async def nodo_de(self, tenant_id: int | None) -> int | None:
        """El servidor de la empresa (None = principal). Un servidor
        desactivado no recibe nada: sus empresas vuelven al principal."""
        if tenant_id is None:
            return None
        await self.refrescar()
        nid = self.empresa_nodo.get(tenant_id)
        if nid is None:
            return None
        nodo = self.nodos.get(nid)
        return nid if nodo and nodo.activo else None

    def destino(self, nodo_id: int | None) -> Destino:
        if nodo_id is not None and nodo_id in self.nodos:
            return self.nodos[nodo_id].destino
        from app.core.runtime_settings import runtime_settings

        return Destino(runtime_settings.fs_esl_host, runtime_settings.fs_esl_port, runtime_settings.fs_esl_password)

    async def todos(self) -> list[int | None]:
        """El principal y los adicionales activos."""
        await self.refrescar()
        return [None, *sorted(i for i, n in self.nodos.items() if n.activo)]

    def nombre(self, nodo_id: int | None) -> str:
        return self.nodos[nodo_id].nombre if nodo_id in self.nodos else "principal"


directorio = Directorio()


def _registrar_en_bus() -> None:
    from app.services.bus import bus

    bus.registrar("nodos", lambda _d: directorio.invalidar(avisar=False))


_registrar_en_bus()
