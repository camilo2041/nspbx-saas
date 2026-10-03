"""Un solo líder entre las réplicas del backend (docs/escala.md).

Con más de una réplica detrás del balanceador, las peticiones HTTP las atiende
cualquiera, pero hay trabajo que tiene que hacer UNA sola:

- marcar (dialer, progresivo, predictivo): dos marcando = el doble de llamadas;
- procesar los eventos de FreeSWITCH: dos procesándolos = cada agente
  cambiaría de estado dos veces;
- repartir webhooks, mandar reportes programados, el mantenimiento.

El líder es quien tiene un `pg_try_advisory_lock` de Postgres, tomado en una
conexión propia. Si el proceso muere o pierde la base, Postgres suelta el
candado solo y otra réplica lo toma en la siguiente vuelta (cada
`CADA_S` segundos). Si es esta réplica la que deja de ver la base, deja de
trabajar como líder en el acto: más vale unos segundos sin marcar que dos
réplicas marcando.

Con una sola réplica no cambia nada: toma el candado al arrancar.
"""

import asyncio
import logging
from typing import Awaitable, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

# Número fijo del candado (cualquiera, pero el mismo en todas las réplicas).
CLAVE = 7_324_001
CADA_S = 5.0
_PING_TIMEOUT_S = 5.0

Accion = Callable[[], Awaitable[None]]


def dsn() -> str:
    """La URL de SQLAlchemy sin el driver (asyncpg la quiere así)."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class Lider:
    def __init__(self, al_ascender: Accion | None = None, al_descender: Accion | None = None, cada_s: float = CADA_S):
        self.al_ascender = al_ascender
        self.al_descender = al_descender
        self.cada_s = cada_s
        self.es_lider = False
        self._conexion = None
        self._tarea: asyncio.Task | None = None

    async def _conectar(self):
        import asyncpg

        if self._conexion is None or self._conexion.is_closed():
            self._conexion = await asyncpg.connect(dsn(), timeout=_PING_TIMEOUT_S)
        return self._conexion

    async def intentar(self) -> bool:
        """Una vuelta: si no es líder, intenta serlo; si lo es, comprueba que
        sigue teniendo la base. Devuelve si es líder al terminar."""
        if self.es_lider:
            try:
                await asyncio.wait_for(self._conexion.fetchval("SELECT 1"), _PING_TIMEOUT_S)
                return True
            except Exception as exc:
                logger.error("El líder perdió la conexión con la base (%s): deja de serlo", exc)
                await self._perder()
                return False
        try:
            conexion = await self._conectar()
            tomado = await asyncio.wait_for(conexion.fetchval("SELECT pg_try_advisory_lock($1)", CLAVE), _PING_TIMEOUT_S)
        except Exception as exc:
            logger.warning("No se pudo intentar el liderazgo: %s", exc)
            await self._cerrar()
            return False
        if tomado:
            self.es_lider = True
            logger.info("Esta réplica es la líder: arranca la marcación y los eventos")
            if self.al_ascender:
                try:
                    await self.al_ascender()
                except Exception:
                    logger.exception("Error al arrancar como líder")
        return self.es_lider

    async def _perder(self) -> None:
        self.es_lider = False
        await self._cerrar()
        if self.al_descender:
            try:
                await self.al_descender()
            except Exception:
                logger.exception("Error al dejar de ser líder")

    async def _cerrar(self) -> None:
        if self._conexion is not None:
            try:
                await self._conexion.close(timeout=2)
            except Exception:
                self._conexion.terminate()
        self._conexion = None

    async def _bucle(self) -> None:
        while True:
            await asyncio.sleep(self.cada_s)
            try:
                await self.intentar()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en la vuelta del líder")

    def start(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle())

    async def stop(self) -> None:
        """Al apagar: suelta el candado ya (la otra réplica no espera a que
        Postgres note la conexión muerta)."""
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
        if self.es_lider:
            self.es_lider = False
            if self.al_descender:
                try:
                    await self.al_descender()
                except Exception:
                    logger.exception("Error al detener los trabajos del líder")
            try:
                await self._conexion.execute("SELECT pg_advisory_unlock($1)", CLAVE)
            except Exception:
                pass
        await self._cerrar()


lider = Lider()
