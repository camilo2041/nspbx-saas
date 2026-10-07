"""Calidad automática: cada noche la IA propone la evaluación de una muestra
de llamadas grabadas, y alguien las revisa.

Con «calidad automática» encendida (Ajustes de Calidad: N llamadas por
agente, tope por noche), a partir de la HORA local la réplica líder toma las
llamadas contestadas y grabadas del día anterior que nadie evaluó, elige
hasta N al azar por agente y le pide a la IA su evaluación
(services/calidad.sugerir: transcribe con Deepgram si hace falta y califica
con el modelo de lenguaje). Quedan como «por revisar» (`revisada=False`):
no cuentan en los promedios ni las ve el agente hasta que un supervisor
las confirma o las corrige.

El tope por noche es el freno de gasto: cada llamada es una transcripción
y una consulta al modelo.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core.clock import business_tz, now_local
from app.core.database import async_session, sesion_de_empresa
from app.models import CallLog, EvaluacionLlamada, SystemSettings
from app.services import calidad

logger = logging.getLogger(__name__)

HORA = 2  # hora local desde la que corre el muestreo del día anterior
CANDIDATAS_MAX = 2000


def _utc(momento: datetime) -> datetime:
    from datetime import timezone

    return momento.astimezone(timezone.utc).replace(tzinfo=None)


async def muestrear(tenant_id: int, dia: date, por_agente: int, tope: int, azar: random.Random | None = None) -> int:
    """Propone las evaluaciones de `dia` para una empresa. Devuelve cuántas creó."""
    azar = azar or random.Random()
    tz = business_tz()
    ini = _utc(datetime.combine(dia, datetime.min.time()).replace(tzinfo=tz))
    fin = _utc(datetime.combine(dia + timedelta(days=1), datetime.min.time()).replace(tzinfo=tz))
    creadas = 0
    async with sesion_de_empresa(tenant_id) as session:
        evaluadas = select(EvaluacionLlamada.call_id)
        candidatas = (
            await session.execute(
                select(CallLog)
                .where(CallLog.started_at >= ini, CallLog.started_at < fin, CallLog.recording_path.is_not(None),
                       CallLog.billsec >= 30, CallLog.id.not_in(evaluadas))
                .order_by(CallLog.id)
                .limit(CANDIDATAS_MAX)
            )
        ).scalars().all()
        por: dict[int, list[CallLog]] = {}
        for c in candidatas:
            agente = await calidad.agente_de(session, c)
            if agente is not None:
                por.setdefault(agente, []).append(c)
        elegidas = []
        for agente, llamadas in sorted(por.items()):
            for c in azar.sample(llamadas, min(por_agente, len(llamadas))):
                elegidas.append((agente, c))
        azar.shuffle(elegidas)
        lista = await calidad.criterios(session, tenant_id)
        for agente, c in elegidas[:tope]:
            try:
                s = await calidad.sugerir(session, c, lista)
            except calidad.ErrorCalidad as exc:
                logger.info("Calidad automática: llamada %s sin evaluar (%s)", c.id, exc.mensaje)
                if exc.codigo == 400:
                    break  # falta una API key: las demás tampoco van a poder
                continue
            except Exception:
                logger.exception("Calidad automática: error evaluando la llamada %s", c.id)
                continue
            session.add(EvaluacionLlamada(
                tenant_id=tenant_id, call_id=c.id, agente_id=agente, evaluador_id=None, puntajes=s["puntajes"],
                total_pct=s["total_pct"], comentario=s["comentario"] or None, origen="ia", revisada=False,
                created_at=datetime.utcnow(),
            ))
            await session.commit()
            creadas += 1
    return creadas


class Muestreo:
    def __init__(self):
        self._tarea: asyncio.Task | None = None

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

    async def _bucle(self) -> None:
        while True:
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en la calidad automática")
            await asyncio.sleep(600)

    async def ciclo(self, ahora: datetime | None = None) -> dict[int, int]:
        """Las empresas que todavía no muestrearon hoy, si ya es la hora."""
        ahora = ahora or now_local()
        if ahora.hour < HORA:
            return {}
        hoy = ahora.date()
        async with async_session() as dueno:
            pendientes = (
                await dueno.execute(
                    select(SystemSettings).where(SystemSettings.calidad_auto_por_agente > 0,
                                                 (SystemSettings.calidad_auto_ultima.is_(None))
                                                 | (SystemSettings.calidad_auto_ultima < hoy))
                )
            ).scalars().all()
            # Se marca antes de empezar: si algo falla a medias no se repite
            # la noche (ni el gasto) en la siguiente vuelta.
            trabajo = []
            for a in pendientes:
                if a.tenant_id is None:
                    continue
                a.calidad_auto_ultima = hoy
                trabajo.append((a.tenant_id, max(1, min(a.calidad_auto_por_agente, 20)), max(1, min(a.calidad_auto_tope, 500))))
            await dueno.commit()
        hechas = {}
        for tenant_id, por_agente, tope in trabajo:
            try:
                hechas[tenant_id] = await muestrear(tenant_id, hoy - timedelta(days=1), por_agente, tope)
                logger.info("Calidad automática: %d evaluaciones por revisar en la empresa %s", hechas[tenant_id], tenant_id)
            except Exception:
                logger.exception("Calidad automática: falló la empresa %s", tenant_id)
        return hechas


muestreo = Muestreo()
