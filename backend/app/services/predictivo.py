"""Marcación proporcional y predictiva (docs/plan-contact-center.md, fase 4).

A diferencia del progresivo (un agente, una llamada), acá las llamadas
salen SIN agente: se marcan más números que agentes listos porque muchos
no contestan. Cuando un cliente contesta, se le asigna el agente que lleva
más tiempo libre y entra a su sala (services/agentes.py). Si no hay ninguno
dentro de `temporizador_abandono` segundos, la llamada es un ABANDONO: el
cliente oye el mensaje de la campaña y se cuelga; el lead vuelve a la cola
con prioridad.

- **Proporcional**: `nivel_marcacion` llamadas por agente listo, fijo.
- **Predictivo**: con la tasa de contacto observada, tantas llamadas en
  curso como permita el objetivo de abandono según una binomial
  (`llamadas_en_curso`). Un factor de prudencia (`ajustar_factor`) corrige
  con el abandono real: el abandono manda.

Las cuentas son funciones puras que usan igual el motor real y el
simulador (services/simulador_predictivo.py), que corre en CI y comprueba
que el abandono queda bajo el objetivo en distintos escenarios.
"""

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core import validacion
from app.core.clock import now_local
from app.core.database import async_session, sesion_de_empresa
from app.models import AgenteVivo, Campaign, CampaignNumber, MetricaCampana, SystemSettings
from app.services import agentes, esl, horario_marcacion, hopper, tope_campanas

logger = logging.getLogger(__name__)

METODOS = ("proporcional", "predictivo")
NIVEL_MIN = 1.0
# Peso de un agente que está por terminar su llamada (ver `a_lanzar`).
FACTOR_PRONTO = 0.5
# En el predictivo los agentes por terminar NO cuentan como libres: el
# simulador mostró que con conversaciones de duración variable esa
# predicción falla seguido y cada acierto fallido es un abandono.
PRONTO_PREDICTIVO = 0.0
CONTACTO_SIN_SOBREMARCAR = 0.5

# Esperas del agente entre llamadas por encima de esto: hay margen para subir.
ESPERA_OBJETIVO_S = 8.0
VENTANA_S = 15 * 60
# Con menos contestadas que esto, el abandono del día no es representativo.
MINIMO_MUESTRA = 20
PRIORIDAD_ABANDONO = 40
REINTENTO_ABANDONO = timedelta(minutes=10)
AHT_INICIAL_S = 120.0
RING_INICIAL_S = 10.0


# --- Las cuentas ------------------------------------------------------------------


def a_lanzar(listos: int, pronto: int, timbrando: int, en_espera: int, nivel: float) -> int:
    """Cuántas llamadas nuevas lanzar ahora.

    `pronto`: agentes en llamada que, por lo que suele durar una, están por
    terminar (VICIdial hace lo mismo). Cuentan solo en la medida en que el
    nivel pasa de 1: así el nivel mínimo es exactamente el progresivo (una
    llamada por agente libre, sin abandonos) y el controlador siempre tiene
    hacia dónde bajar. El simulador lo mostró: contándolos siempre, con
    conversaciones de duración variable, el abandono pasaba del 10 % aun
    en el nivel mínimo. Lo que ya está timbrando o contestado esperando
    agente se descuenta."""
    efectivos = listos + FACTOR_PRONTO * pronto * min(1.0, max(0.0, nivel - 1.0))
    if efectivos <= 0:
        return 0
    return max(0, math.ceil(efectivos * nivel - 1e-9) - timbrando - en_espera)


def tasa_contacto(contestadas: int, intentos: int, previa: float = 0.9, peso: float = 20.0) -> float:
    """Probabilidad de que una llamada la conteste una persona. Con pocos
    datos manda la previa; con muchos, lo observado."""
    return min(0.98, max(0.02, (contestadas + previa * peso) / (intentos + peso)))


def _exceso_esperado(n: int, p: float, libres: float) -> float:
    """E[max(0, X - libres)] con X ~ Binomial(n, p): clientes que
    contestarían sin agente si todos contestaran a la vez."""
    exceso = 0.0
    prob = (1 - p) ** n  # P(X = 0)
    for k in range(n + 1):
        if k > libres:
            exceso += (k - libres) * prob
        if k < n:
            prob *= (n - k) / (k + 1) * p / (1 - p)
    return exceso


def llamadas_en_curso(libres: float, p: float, objetivo_pct: float, nivel_max: float) -> int:
    """Cuántas llamadas tener timbrando para `libres` agentes: la mayor
    cantidad cuyo abandono esperado (exceso / contestadas) no pasa el
    objetivo. Nunca menos que una por agente libre (el progresivo) ni más
    que `nivel_max` por agente.

    Es conservador a propósito: supone que todas contestan a la vez, cuando
    en realidad las respuestas se reparten en el timbre y en ese tiempo se
    liberan agentes. El factor de prudencia (`ajustar_factor`) lo corrige
    con lo observado."""
    if libres <= 0:
        return 0
    minimo = math.ceil(libres - 1e-9)
    if p >= CONTACTO_SIN_SOBREMARCAR:
        # Contesta casi todo el mundo: sobremarcar no gana ocupación y sí
        # abandonos (simulador: <1 punto de ocupación, hasta 5,6 % de
        # abandono con 30 agentes y 80 % de contacto). Una por agente.
        return minimo
    tope = max(minimo, math.floor(libres * max(nivel_max, NIVEL_MIN)))
    mejor = minimo
    for n in range(minimo + 1, tope + 1):
        if _exceso_esperado(n, p, libres) / (n * p) > objetivo_pct / 100.0:
            break
        mejor = n
    return mejor


def a_lanzar_predictivo(listos: int, pronto: int, timbrando: int, en_espera: int, p: float,
                        objetivo_pct: float, nivel_max: float) -> int:
    """Llamadas nuevas para el predictivo. Los clientes que ya esperan
    agente se descuentan de los agentes libres; los agentes por terminar
    cuentan a medias."""
    libres = listos + PRONTO_PREDICTIVO * pronto - en_espera
    return max(0, llamadas_en_curso(libres, p, objetivo_pct, nivel_max) - timbrando)


FACTOR_MIN, FACTOR_MAX, FACTOR_INICIAL = 1.0, 30.0, 1.5


def ajustar_factor(
    factor: float,
    abandono_dia: float | None,
    abandono_reciente: float | None,
    objetivo: float,
    espera_agente: float | None,
) -> float:
    """Prudencia del predictivo: multiplica el objetivo de abandono que usa
    el cálculo (más alto = más conservador). El abandono manda: si el del
    día o el reciente pasan el objetivo, sube 25 %. Si el reciente está
    holgado (menos de la mitad) y los agentes esperan, baja 5 %."""
    pasado = any(a is not None and a > objetivo for a in (abandono_dia, abandono_reciente))
    if pasado:
        nuevo = factor * 1.25
    elif (abandono_reciente is None or abandono_reciente < objetivo * 0.5) and espera_agente is not None \
            and espera_agente > ESPERA_OBJETIVO_S:
        nuevo = factor * 0.95
    else:
        nuevo = factor
    return round(min(max(nuevo, FACTOR_MIN), FACTOR_MAX), 3)


@dataclass
class Ventana:
    """Lo de los últimos 15 minutos de una campaña."""

    # Llamadas cuyo timbre ya terminó (contestaron o no). NO se cuentan al
    # lanzarlas: una llamada que todavía timbra no es un «no contestó». El
    # simulador lo mostró: contándolas al lanzar, al arrancar la jornada la
    # tasa de contacto caía a 0,36 sin ninguna respuesta todavía, el
    # predictivo sobremarcaba, la tasa caía más… y terminaba con 223
    # llamadas timbrando para 30 agentes.
    resueltas: deque = field(default_factory=deque)
    contestadas: deque = field(default_factory=deque)
    abandonadas: deque = field(default_factory=deque)
    esperas_agente: deque = field(default_factory=deque)  # (t, segundos)
    conversaciones: deque = field(default_factory=deque)  # (t, segundos)
    rings: deque = field(default_factory=deque)  # (t, segundos)

    def _limpiar(self, ahora: float) -> None:
        corte = ahora - VENTANA_S
        for cola in (self.resueltas, self.contestadas, self.abandonadas):
            while cola and cola[0] < corte:
                cola.popleft()
        for cola in (self.esperas_agente, self.conversaciones, self.rings):
            while cola and cola[0][0] < corte:
                cola.popleft()

    def abandono(self, ahora: float) -> float | None:
        self._limpiar(ahora)
        if len(self.contestadas) < 5:
            return None
        return 100.0 * len(self.abandonadas) / len(self.contestadas)

    def contacto(self, ahora: float) -> float:
        self._limpiar(ahora)
        return tasa_contacto(len(self.contestadas), len(self.resueltas))

    @staticmethod
    def _promedio(cola, respaldo: float | None) -> float | None:
        return sum(v for _, v in cola) / len(cola) if cola else respaldo

    def espera_agente(self, ahora: float) -> float | None:
        self._limpiar(ahora)
        return self._promedio(self.esperas_agente, None)

    def aht(self, ahora: float) -> float:
        self._limpiar(ahora)
        return self._promedio(self.conversaciones, AHT_INICIAL_S)

    def ring(self, ahora: float) -> float:
        self._limpiar(ahora)
        return self._promedio(self.rings, RING_INICIAL_S)


# --- El motor -----------------------------------------------------------------------


@dataclass
class Llamada:
    uuid: str
    tenant_id: int
    campaign_id: int
    lead_id: int
    estado: str  # timbrando | espera | asignada
    creada: float
    contestada: float | None = None
    limite: float | None = None


async def _sumar(session, campana: Campaign, **contadores: int) -> None:
    """Suma a los contadores del día de la campaña (una fila por día)."""
    hoy = now_local().date()
    valores = {k: v for k, v in contadores.items() if v}
    if not valores:
        return
    stmt = insert(MetricaCampana).values(
        tenant_id=campana.tenant_id, campaign_id=campana.id, fecha=hoy,
        **{k: valores.get(k, 0) for k in ("intentos", "contestadas", "asignadas", "abandonadas")},
    )
    stmt = stmt.on_conflict_do_update(
        constraint="ux_metricas_campana_dia",
        set_={k: getattr(MetricaCampana, k) + v for k, v in valores.items()},
    )
    await session.execute(stmt)


async def metricas_de_hoy(session, campaign_id: int) -> dict:
    fila = (
        await session.execute(
            select(MetricaCampana).where(MetricaCampana.campaign_id == campaign_id,
                                         MetricaCampana.fecha == now_local().date())
        )
    ).scalar_one_or_none()
    datos = {k: getattr(fila, k) if fila else 0 for k in ("intentos", "contestadas", "asignadas", "abandonadas")}
    datos["abandono_pct"] = round(100.0 * datos["abandonadas"] / datos["contestadas"], 2) if datos["contestadas"] else None
    return datos


class Motor:
    def __init__(self, reloj=time.monotonic):
        self.reloj = reloj
        self.llamadas: dict[str, Llamada] = {}
        self.ventanas: dict[int, Ventana] = {}
        # Prudencia de cada campaña predictiva (`ajustar_factor`). En memoria:
        # tras un reinicio vuelve a FACTOR_INICIAL, que es conservador.
        self.factores: dict[int, float] = {}
        self._ultimo_ajuste: dict[int, float] = {}
        self._tarea: asyncio.Task | None = None

    def ventana(self, campaign_id: int) -> Ventana:
        return self.ventanas.setdefault(campaign_id, Ventana())

    def de_campana(self, campaign_id: int, estado: str | None = None) -> list[Llamada]:
        return [ll for ll in self.llamadas.values()
                if ll.campaign_id == campaign_id and (estado is None or ll.estado == estado)]

    # --- Ciclo --------------------------------------------------------------------

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
                logger.exception("Error en el ciclo predictivo")
            await asyncio.sleep(0.5)

    async def ciclo(self) -> int:
        """Una vuelta: asigna o abandona lo que espera, ajusta el nivel y
        lanza lo que haga falta. Devuelve cuántas llamadas lanzó."""
        await self.atender_esperas()
        async with async_session() as dueno:
            campanas = (
                await dueno.execute(
                    select(Campaign.tenant_id, Campaign.id).where(
                        Campaign.status == "running", Campaign.metodo.in_(METODOS)
                    )
                )
            ).all()
        lanzadas = 0
        for tenant_id, campaign_id in campanas:
            async with sesion_de_empresa(tenant_id) as session:
                lanzadas += await self._campana(session, campaign_id)
                await session.commit()
        return lanzadas

    async def _campana(self, session, campaign_id: int) -> int:
        campana = await session.get(Campaign, campaign_id)
        if campana is None or campana.status != "running" or campana.metodo not in METODOS:
            return 0
        ahora = self.reloj()
        ventana = self.ventana(campaign_id)
        vivos = [v for v in (await session.execute(select(AgenteVivo))).scalars() if campaign_id in (v.campanas or [])]
        listos = sum(1 for v in vivos if v.estado == agentes.LISTO and v.audio)
        aht, ring = ventana.aht(ahora), ventana.ring(ahora)
        ahora_dt = datetime.utcnow()
        pronto = sum(
            1 for v in vivos
            if v.estado == agentes.EN_LLAMADA and v.contestada_at
            and (ahora_dt - v.contestada_at).total_seconds() >= max(0.0, aht - ring)
        )
        timbrando = len(self.de_campana(campaign_id, "timbrando"))
        espera = len(self.de_campana(campaign_id, "espera"))
        if campana.metodo == "predictivo":
            factor = await self._ajustar(session, campana, ventana, ahora)
            cuantas = a_lanzar_predictivo(listos, pronto, timbrando, espera, ventana.contacto(ahora),
                                          campana.abandono_objetivo / factor, campana.nivel_max)
            libres = listos - espera
            # El nivel que se ve en la campaña: llamadas en curso por agente libre.
            if libres > 0:
                campana.nivel_actual = round((timbrando + cuantas) / libres, 2)
        else:
            cuantas = a_lanzar(listos, pronto, timbrando, espera, campana.nivel_marcacion)
        activas = len(self.de_campana(campaign_id))
        cuantas = min(cuantas, max(0, campana.max_concurrency - activas))
        if cuantas <= 0:
            return 0

        ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
        if not horario_marcacion.puede_marcar(ajustes, campana.ai_intent, now_local()):
            return 0
        hoy = now_local().date()
        minutos = (await tope_campanas.minutos_hoy(session, [campana.id])).get(campana.id, 0)
        quedan, _ = tope_campanas.disponibles(campana, hoy, minutos)
        if quedan is not None:
            cuantas = min(cuantas, quedan)
        if cuantas <= 0:
            return 0

        lanzadas = 0
        for lead in await hopper.tomar(session, campana, cuantas):
            try:
                call_uuid, tramos, valores = await agentes.preparar_llamada(session, campana, lead, agente_id=None)
            except agentes.ErrorAgente as exc:
                lead.status = "no_llamar" if "no llamar" in exc.mensaje else "failed"
                lead.last_error = exc.mensaje[:500]
                continue
            valores["nspbx_pred"] = "1"
            await esl.bgapi(f"originate {{{agentes._vars(valores)}}}{'|'.join(tramos)} &park()")
            self.llamadas[call_uuid] = Llamada(call_uuid, campana.tenant_id, campana.id, lead.id, "timbrando", ahora)
            lanzadas += 1
        if lanzadas:
            tope_campanas.contar_lanzadas(campana, hoy, lanzadas)
            await _sumar(session, campana, intentos=lanzadas)
        return lanzadas

    async def _ajustar(self, session, campana: Campaign, ventana: Ventana, ahora: float) -> float:
        """Factor de prudencia de la campaña, recalculado cada 10 s."""
        factor = self.factores.get(campana.id, FACTOR_INICIAL)
        if ahora - self._ultimo_ajuste.get(campana.id, -1e9) < 10:
            return factor
        self._ultimo_ajuste[campana.id] = ahora
        hoy = await metricas_de_hoy(session, campana.id)
        abandono_dia = hoy["abandono_pct"] if hoy["contestadas"] >= MINIMO_MUESTRA else None
        factor = ajustar_factor(factor, abandono_dia, ventana.abandono(ahora), campana.abandono_objetivo,
                                ventana.espera_agente(ahora))
        self.factores[campana.id] = factor
        return factor

    # --- Eventos de FreeSWITCH -------------------------------------------------------

    async def recibir(self, ev: dict[str, str]) -> None:
        if not ev.get("variable_nspbx_pred"):
            return
        llamada = self.llamadas.get(ev.get("Unique-ID") or "")
        if llamada is None:
            return
        nombre = ev.get("Event-Name")
        ahora = self.reloj()
        if nombre == "CHANNEL_ANSWER" and llamada.estado == "timbrando":
            llamada.estado = "espera"
            llamada.contestada = ahora
            async with sesion_de_empresa(llamada.tenant_id) as session:
                campana = await session.get(Campaign, llamada.campaign_id)
                llamada.limite = ahora + max(1, campana.temporizador_abandono if campana else 2)
                self.ventana(llamada.campaign_id).resueltas.append(ahora)
                self.ventana(llamada.campaign_id).contestadas.append(ahora)
                self.ventana(llamada.campaign_id).rings.append((ahora, ahora - llamada.creada))
                if campana is not None:
                    await _sumar(session, campana, contestadas=1)
                await session.commit()
            await self._asignar(llamada)
        elif nombre == "CHANNEL_HANGUP_COMPLETE":
            self.llamadas.pop(llamada.uuid, None)
            if llamada.estado == "timbrando":
                self.ventana(llamada.campaign_id).resueltas.append(ahora)
                await self._no_contesto(llamada, ev.get("Hangup-Cause") or "")
            elif llamada.estado == "espera":
                # El cliente colgó antes de que llegara un agente: también es abandono.
                await self._abandono(llamada, colgar=False)
            elif llamada.estado == "asignada" and llamada.contestada is not None:
                self.ventana(llamada.campaign_id).conversaciones.append((ahora, ahora - llamada.contestada))

    async def _no_contesto(self, llamada: Llamada, causa: str) -> None:
        async with sesion_de_empresa(llamada.tenant_id) as session:
            lead = await session.get(CampaignNumber, llamada.lead_id)
            campana = await session.get(Campaign, llamada.campaign_id)
            if lead is not None:
                resultado = agentes._resultado(causa)
                lead.last_error = causa or None
                if lead.attempts > (campana.retries if campana else 0):
                    lead.status = resultado
                else:
                    hopper.reprogramar(lead, campana, resultado)
            await session.commit()

    async def atender_esperas(self) -> None:
        ahora = self.reloj()
        for llamada in [ll for ll in self.llamadas.values() if ll.estado == "espera"]:
            if await self._asignar(llamada):
                continue
            if llamada.limite is not None and ahora >= llamada.limite:
                self.llamadas.pop(llamada.uuid, None)
                await self._abandono(llamada, colgar=True)

    async def _asignar(self, llamada: Llamada) -> bool:
        """Al agente LISTO de la campaña que lleva más tiempo esperando."""
        async with sesion_de_empresa(llamada.tenant_id) as session:
            candidatos = (
                await session.execute(
                    select(AgenteVivo)
                    .where(AgenteVivo.estado == agentes.LISTO, AgenteVivo.audio.is_(True))
                    .order_by(AgenteVivo.desde)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            vivo = next((v for v in candidatos if llamada.campaign_id in (v.campanas or [])), None)
            if vivo is None:
                return False
            lead = await session.get(CampaignNumber, llamada.lead_id)
            sala = agentes.conferencia(vivo.tenant_id, vivo.user_id)
            validacion.exigir(validacion.NOMBRE_RE, llamada.uuid, "uuid")
            # El agente queda en el canal (lo leen el CDR y services/agentes.py
            # al colgar) y el cliente pasa a su sala.
            # Si al agente le están susurrando, el supervisor se mutea antes de
            # que entre el cliente (ver services/supervision.py).
            from app.services.supervision import monitoreo

            await monitoreo.antes_de_cliente(vivo.tenant_id, vivo.user_id)
            await esl.api(f"uuid_setvar {llamada.uuid} nspbx_agente_id {vivo.user_id}")
            await esl.api(f"uuid_transfer {llamada.uuid} conference:{sala}@{agentes.PERFIL_CONFERENCIA} inline")
            ahora_dt = datetime.utcnow()
            self.ventana(llamada.campaign_id).esperas_agente.append((self.reloj(), (ahora_dt - vivo.desde).total_seconds()))
            await agentes._transicion(
                session, vivo, agentes.EN_LLAMADA, ahora_dt, campaign_id=llamada.campaign_id, lead_id=llamada.lead_id,
                call_uuid=llamada.uuid, telefono=lead.phone if lead else None, contestada_at=ahora_dt,
                volver_a_pausa_id=None, codigo_pausa_id=None,
            )
            campana = await session.get(Campaign, llamada.campaign_id)
            if campana is not None:
                await _sumar(session, campana, asignadas=1)
            await session.commit()
        llamada.estado = "asignada"
        return True

    async def _abandono(self, llamada: Llamada, colgar: bool) -> None:
        ahora = self.reloj()
        self.ventana(llamada.campaign_id).abandonadas.append(ahora)
        async with sesion_de_empresa(llamada.tenant_id) as session:
            campana = await session.get(Campaign, llamada.campaign_id)
            lead = await session.get(CampaignNumber, llamada.lead_id)
            if colgar:
                validacion.exigir(validacion.NOMBRE_RE, llamada.uuid, "uuid")
                await esl.api(f"uuid_setvar {llamada.uuid} nspbx_abandonada true")
                audio = campana.audio_abandono if campana else None
                if audio and validacion.RUTA_AUDIO_RE.fullmatch(audio):
                    await esl.api(f"uuid_transfer {llamada.uuid} playback:{audio},hangup inline")
                else:
                    await esl.api(f"uuid_kill {llamada.uuid}")
            if lead is not None:
                # No fue culpa del cliente: vuelve pronto y adelante en la cola.
                lead.status = "pending"
                lead.prioridad = max(lead.prioridad or 0, PRIORIDAD_ABANDONO)
                lead.proximo_intento_at = datetime.utcnow() + REINTENTO_ABANDONO
                lead.last_error = "Abandonada: no había agente libre"
            if campana is not None:
                await _sumar(session, campana, abandonadas=1)
            await session.commit()


motor = Motor()


# --- Mensaje de abandono ----------------------------------------------------------------

VOZ_ABANDONO = "es-CO-SalomeNeural"


def mensaje_por_defecto(empresa: str) -> str:
    return (
        f"Hola, le llamábamos de {empresa}. En este momento todos nuestros asesores están ocupados; "
        "le volveremos a llamar en unos minutos. Muchas gracias."
    )


async def generar_audio_abandono(campana: Campaign, empresa: str) -> str | None:
    """El audio del mensaje de abandono (voz neuronal, services/tts.py) en la
    carpeta de sonidos de los bots. Sin mensaje propio se usa uno genérico:
    quien contesta y no tiene agente tiene que saber quién llamaba. None si
    no se pudo generar (sin red): entonces se cuelga sin mensaje."""
    from pathlib import Path

    from app.core.config import settings
    from app.services import tts

    texto = (campana.mensaje_abandono or "").strip() or mensaje_por_defecto(empresa)
    nombre = f"abandono_c{int(campana.id)}.mp3"
    try:
        audio = await tts.synthesize(texto, VOZ_ABANDONO)
        carpeta = Path(settings.fs_sounds_dir) / "bots"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / nombre).write_bytes(audio)
    except Exception as exc:
        logger.warning("No se pudo generar el mensaje de abandono de la campaña %s: %s", campana.id, exc)
        return None
    return f"/usr/share/freeswitch/sounds/bots/{nombre}"
