"""Mensajes entre las réplicas del backend, por LISTEN/NOTIFY de Postgres.

Con varias réplicas, lo que pasa en una (un evento de FreeSWITCH en la líder,
un agente que pasa a listo en la que atendió su petición, un permiso que se
cambia) lo tienen que ver los tableros conectados a cualquiera. No hace falta
otro servicio (Redis, etc.): Postgres ya está y NOTIFY llega a todos los que
escuchan el canal.

- Cada réplica tiene un id; los mensajes propios que vuelven por el canal se
  ignoran (ya se entregaron localmente).
- `emitir_pronto` no bloquea (se llama desde código síncrono, p. ej. al
  publicar un cambio de agente): encola y una tarea los manda en orden.
- NOTIFY acepta hasta 8000 bytes por mensaje: lo que no entra se descarta con
  un aviso en el log (los mensajes de tiempo real son de unos cientos).
- Si se corta la conexión, se reconecta sola. Mientras tanto, cada réplica
  sigue funcionando con lo suyo.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

CANAL = "nspbx_bus"
MAX_BYTES = 7800
_COLA = 5000

Manejador = Callable[[dict], Awaitable[None] | None]


class Bus:
    def __init__(self):
        self.replica = uuid.uuid4().hex[:12]
        self.manejadores: dict[str, Manejador] = {}
        self._conexion = None
        self._cola: asyncio.Queue | None = None
        self._tareas: list[asyncio.Task] = []
        self.activo = False

    def registrar(self, tipo: str, manejador: Manejador) -> None:
        self.manejadores[tipo] = manejador

    # --- Envío ------------------------------------------------------------------

    def emitir_pronto(self, tipo: str, datos: Any) -> None:
        if not self.activo or self._cola is None:
            return
        try:
            self._cola.put_nowait((tipo, datos))
        except asyncio.QueueFull:
            logger.warning("Bus lleno: se descarta un mensaje %s", tipo)

    async def _enviar(self) -> None:
        while True:
            tipo, datos = await self._cola.get()
            cuerpo = json.dumps({"r": self.replica, "t": tipo, "d": datos}, ensure_ascii=False, default=str)
            if len(cuerpo.encode()) > MAX_BYTES:
                logger.warning("Mensaje %s de %d bytes: no entra en NOTIFY, se descarta", tipo, len(cuerpo))
                continue
            try:
                conexion = await self._asegurar()
                await conexion.execute("SELECT pg_notify($1, $2)", CANAL, cuerpo)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("No se pudo publicar en el bus (%s): %s", tipo, exc)

    # --- Recepción ---------------------------------------------------------------

    def _al_recibir(self, _conexion, _pid, _canal, cuerpo: str) -> None:
        try:
            msg = json.loads(cuerpo)
        except ValueError:
            return
        if msg.get("r") == self.replica:
            return
        manejador = self.manejadores.get(msg.get("t"))
        if manejador is None:
            return
        try:
            resultado = manejador(msg.get("d"))
            if asyncio.iscoroutine(resultado):
                asyncio.ensure_future(resultado)
        except Exception:
            logger.exception("Mensaje del bus no procesado: %s", msg.get("t"))

    async def _asegurar(self):
        import asyncpg

        from app.services.lider import dsn

        if self._conexion is None or self._conexion.is_closed():
            self._conexion = await asyncpg.connect(dsn(), timeout=5)
            await self._conexion.add_listener(CANAL, self._al_recibir)
        return self._conexion

    async def _vigilar(self) -> None:
        while True:
            try:
                await self._asegurar()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Bus sin conexión, se reintenta: %s", exc)
            await asyncio.sleep(5)

    # --- Ciclo de vida -----------------------------------------------------------------

    async def start(self) -> None:
        self._cola = asyncio.Queue(maxsize=_COLA)
        self.activo = True
        try:
            await self._asegurar()
        except Exception as exc:
            logger.warning("El bus arranca sin conexión: %s", exc)
        self._tareas = [asyncio.create_task(self._enviar()), asyncio.create_task(self._vigilar())]

    async def stop(self) -> None:
        self.activo = False
        for t in self._tareas:
            t.cancel()
        for t in self._tareas:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tareas = []
        if self._conexion is not None:
            try:
                await self._conexion.close(timeout=2)
            except Exception:
                self._conexion.terminate()
        self._conexion = None


bus = Bus()
