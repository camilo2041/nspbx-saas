"""Aviso periódico de la posición en la fila de un grupo de atención.

mod_callcenter no anuncia la posición. Al entrar la dice el dialplan
(config_generator._decir_posicion); mientras se espera, este ciclo (solo en
la réplica líder) mira cada pocos segundos quién está esperando en los grupos
con «anunciar posición» y, cada CADA_SEG, le reproduce encima de la música
«Gracias por esperar» + «Hay N personas antes que tú» (uuid_broadcast). El
orden es el de llegada (joined_epoch), que es el que usa el grupo con
`time-base-score=system`.

Lo que ya se le dijo a cada llamada vive en memoria: si cambia la líder, a
lo sumo alguien oye el aviso unos segundos antes.
"""

import asyncio
import logging
import re
import time

from sqlalchemy import select

from app.core.database import async_session
from app.models import Queue
from app.services import esl, voice_prompts
from app.services.queues_sync import _queue_key
from app.services.ajustes import dominios_tenants

logger = logging.getLogger(__name__)

INTERVALO_SEG = 10
PRIMERA_SEG = 40  # al entrar ya se dijo; la primera repetición, después de esto
CADA_SEG = 45
_ESPERANDO = {"Waiting", "Trying"}
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def esperando(salida: str) -> list[dict]:
    """Los que esperan, en orden de llegada, de `callcenter_config queue list members`."""
    lineas = [l for l in (salida or "").splitlines() if "|" in l]
    if not lineas:
        return []
    campos = lineas[0].split("|")
    filas = []
    for linea in lineas[1:]:
        valores = linea.split("|")
        if len(valores) != len(campos):
            continue
        fila = dict(zip(campos, valores))
        if fila.get("state") in _ESPERANDO and _UUID_RE.fullmatch(fila.get("session_uuid") or ""):
            try:
                fila["_llego"] = float(fila.get("joined_epoch") or fila.get("system_epoch") or 0)
            except ValueError:
                fila["_llego"] = 0.0
            filas.append(fila)
    return sorted(filas, key=lambda f: f["_llego"])


def audio_de(delante: int) -> str | None:
    """«Gracias por esperar» + la posición, lo que exista de los dos."""
    partes = [
        voice_prompts.prompt_path("cola_aviso"),
        voice_prompts.prompt_path(f"cola_delante_{delante if delante <= 9 else 'mas'}"),
    ]
    partes = [p for p in partes if p]
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else "file_string://" + "!".join(partes)


class Anunciador:
    def __init__(self):
        self._tarea: asyncio.Task | None = None
        self._ultimo: dict[str, float] = {}

    def start(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle())

    async def stop(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
        self._ultimo.clear()

    async def _bucle(self) -> None:
        while True:
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error anunciando la posición en los grupos")
            await asyncio.sleep(INTERVALO_SEG)

    async def ciclo(self, ahora: float | None = None) -> int:
        """Un repaso de todos los grupos; devuelve cuántos avisos mandó."""
        ahora = ahora or time.time()
        async with async_session() as dueno:
            grupos = (
                await dueno.execute(select(Queue).where(Queue.enabled.is_(True), Queue.announce_position.is_(True)))
            ).scalars().all()
            dominios = await dominios_tenants(dueno) if grupos else {}
        vistos: set[str] = set()
        enviados = 0
        for q in grupos:
            if q.tenant_id not in dominios:
                continue
            try:
                salida = await esl.api(
                    f"callcenter_config queue list members {_queue_key(q.name, dominios[q.tenant_id])}",
                    tenant_id=q.tenant_id,
                )
            except Exception as exc:
                logger.debug("No se pudo ver la fila del grupo %s: %s", q.id, exc)
                continue
            for delante, m in enumerate(esperando(salida)):
                uuid = m["session_uuid"]
                vistos.add(uuid)
                desde = self._ultimo.get(uuid, m["_llego"] - (CADA_SEG - PRIMERA_SEG))
                if ahora - desde < CADA_SEG:
                    continue
                audio = audio_de(delante)
                if audio is None:
                    continue
                self._ultimo[uuid] = ahora
                try:
                    await esl.api(f"uuid_broadcast {uuid} {audio} aleg", tenant_id=q.tenant_id)
                    enviados += 1
                except Exception as exc:
                    logger.debug("No se pudo anunciar la posición a %s: %s", uuid, exc)
        for uuid in list(self._ultimo):
            if uuid not in vistos:
                self._ultimo.pop(uuid, None)
        return enviados


anunciador = Anunciador()
