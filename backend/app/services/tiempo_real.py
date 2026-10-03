"""Llamadas en vivo: eventos de FreeSWITCH → estado por empresa → WebSocket.

FreeSWITCH avisa por ESL cada cambio de un canal (se crea, timbra, contesta,
se puentea, pasa a espera, cuelga). Acá se lleva el estado vivo de cada
canal, se decide de qué empresa es y se publica SOLO a los suscriptores de
esa empresa (ver api/tiempo_real_ws.py). Es la base del supervisor, el
wallboard y el marcador predictivo (docs/plan-contact-center.md, fase 1).

La empresa de un canal sale, en este orden, de:
1. `nspbx_tenant_id` (lo fijan el marcador, el clic para llamar y el dialplan
   del voizbot);
2. el dominio SIP (`domain_name`), el de las extensiones de la empresa;
3. el contexto del dialplan (`Caller-Context`), uno por empresa.
Un canal sin empresa identificable no se publica a nadie: más vale un
tablero incompleto que mostrarle a una empresa las llamadas de otra.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import unquote

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Lo que se pide a FreeSWITCH en la conexión de eventos (ver esl.py).
EVENTOS = (
    "CHANNEL_CREATE",
    "CHANNEL_PROGRESS",
    "CHANNEL_PROGRESS_MEDIA",
    "CHANNEL_ANSWER",
    "CHANNEL_BRIDGE",
    "CHANNEL_HOLD",
    "CHANNEL_UNHOLD",
    "CHANNEL_HANGUP_COMPLETE",
)

# Un canal del que no llegó el cuelgue (se cortó la conexión de eventos en
# ese momento) no puede quedar en el tablero para siempre.
_VIDA_MAXIMA_S = 6 * 3600
_COLA_POR_SUSCRIPTOR = 500


def leer_evento(texto: str) -> dict[str, str]:
    """Cabeceras de un evento en formato `plain` (valores con %-encoding)."""
    evento: dict[str, str] = {}
    for linea in texto.split("\n"):
        clave, sep, valor = linea.partition(":")
        if sep:
            evento[clave.strip()] = unquote(valor.strip())
    return evento


@dataclass
class Resolutor:
    """Dominio SIP y contexto de dialplan → empresa. Se refresca solo."""

    por_dominio: dict[str, int] = field(default_factory=dict)
    por_contexto: dict[str, int] = field(default_factory=dict)
    activas: set[int] = field(default_factory=set)
    _cargado: float = 0.0

    async def refrescar(self, forzar: bool = False) -> None:
        if not forzar and time.monotonic() - self._cargado < 60:
            return
        from app.core.database import async_session
        from app.models import SystemSettings, Tenant

        async with async_session() as s:
            empresas = (await s.execute(select(Tenant))).scalars().all()
            dominios_ajustes = {
                r.tenant_id: r.fs_domain for r in (await s.execute(select(SystemSettings))).scalars().all() if r.fs_domain
            }
        self.por_dominio = {t.sip_domain.lower(): t.id for t in empresas if t.sip_domain}
        for tid, dominio in dominios_ajustes.items():
            self.por_dominio.setdefault(dominio.lower(), tid)
        self.por_contexto = {t.dialplan_context: t.id for t in empresas}
        self.activas = {t.id for t in empresas if t.enabled}
        self._cargado = time.monotonic()

    def empresa(self, ev: dict[str, str]) -> int | None:
        tid = None
        crudo = ev.get("variable_nspbx_tenant_id")
        if crudo:
            try:
                tid = int(crudo)
            except ValueError:
                tid = None
        if tid is None:
            dominio = (ev.get("variable_domain_name") or "").lower()
            tid = self.por_dominio.get(dominio)
        if tid is None:
            tid = self.por_contexto.get(ev.get("Caller-Context") or "")
        return tid if tid in self.activas else None


def _ts(ev: dict[str, str]) -> float:
    try:
        return int(ev.get("Event-Date-Timestamp") or 0) / 1_000_000 or time.time()
    except ValueError:
        return time.time()


class TiempoReal:
    def __init__(self, resolutor: Resolutor | None = None):
        self.resolutor = resolutor or Resolutor()
        self._canales: dict[str, dict] = {}  # uuid → estado (con "tenant_id")
        self._subs: dict[int, set[asyncio.Queue]] = {}

    # --- Suscriptores -----------------------------------------------------
    def suscribir(self, tenant_id: int) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=_COLA_POR_SUSCRIPTOR)
        self._subs.setdefault(tenant_id, set()).add(cola)
        return cola

    def desuscribir(self, tenant_id: int, cola: asyncio.Queue) -> None:
        subs = self._subs.get(tenant_id)
        if subs:
            subs.discard(cola)
            if not subs:
                self._subs.pop(tenant_id, None)

    def publicar(self, tenant_id: int, mensaje: dict) -> None:
        """A los suscriptores de esta réplica y, por el bus, a los de las
        demás (services/bus.py)."""
        self._entregar(tenant_id, mensaje)
        from app.services.bus import bus

        bus.emitir_pronto("tr", {"tenant": tenant_id, "m": mensaje})

    def desde_otra_replica(self, datos: dict) -> None:
        """Un mensaje que publicó otra réplica: se entrega acá y, si es de una
        llamada, se refleja en el estado local (para la foto inicial de los
        que se conectan a esta réplica)."""
        try:
            tenant_id, mensaje = int(datos["tenant"]), datos["m"]
        except (KeyError, TypeError, ValueError):
            return
        if mensaje.get("tipo") == "llamada":
            llamada = mensaje.get("llamada") or {}
            uuid = llamada.get("uuid")
            if uuid and mensaje.get("evento") == "cuelga":
                self._canales.pop(uuid, None)
            elif uuid:
                self._canales[uuid] = {**llamada, "tenant_id": tenant_id, "_visto": time.monotonic()}
        elif mensaje.get("tipo") == "reinicio":
            for u in [u for u, c in self._canales.items() if c["tenant_id"] == tenant_id]:
                self._canales.pop(u, None)
        self._entregar(tenant_id, mensaje)

    def _entregar(self, tenant_id: int, mensaje: dict) -> None:
        for cola in list(self._subs.get(tenant_id, ())):
            if cola.full():
                # Un cliente lento no frena a los demás ni hace crecer la
                # memoria: se le descarta lo más viejo.
                try:
                    cola.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            cola.put_nowait(mensaje)

    def llamadas(self, tenant_id: int) -> list[dict]:
        self._purgar()
        return [self._publico(c) for c in self._canales.values() if c["tenant_id"] == tenant_id]

    def reiniciar(self) -> None:
        """Se perdió la conexión de eventos: lo que había ya no es confiable."""
        empresas = {c["tenant_id"] for c in self._canales.values()}
        self._canales.clear()
        for tid in empresas:
            self.publicar(tid, {"tipo": "reinicio", "llamadas": []})

    # --- Eventos ----------------------------------------------------------
    async def recibir(self, ev: dict[str, str]) -> None:
        nombre = ev.get("Event-Name")
        uuid = ev.get("Unique-ID")
        if nombre not in EVENTOS or not uuid:
            return
        canal = self._canales.get(uuid)
        if canal is None or canal["tenant_id"] is None:
            await self.resolutor.refrescar()
            tid = self.resolutor.empresa(ev)
            if canal is None:
                if nombre == "CHANNEL_HANGUP_COMPLETE":
                    return
                canal = self._nuevo(uuid, ev, tid)
                self._canales[uuid] = canal
            else:
                canal["tenant_id"] = tid
        ahora = _ts(ev)
        evento = {
            "CHANNEL_CREATE": "nueva",
            "CHANNEL_PROGRESS": "timbra",
            "CHANNEL_PROGRESS_MEDIA": "timbra",
            "CHANNEL_ANSWER": "contesta",
            "CHANNEL_BRIDGE": "puente",
            "CHANNEL_HOLD": "espera",
            "CHANNEL_UNHOLD": "retoma",
            "CHANNEL_HANGUP_COMPLETE": "cuelga",
        }[nombre]
        if evento == "timbra":
            if canal["timbre_at"] is None:
                canal["timbre_at"] = ahora
            if canal["estado"] == "iniciando":
                canal["estado"] = "timbrando"
        elif evento == "contesta":
            canal["estado"] = "hablando"
            canal["contesta_at"] = ahora
        elif evento == "puente":
            canal["estado"] = "hablando"
            canal["otra_pata"] = ev.get("Other-Leg-Unique-ID") or canal["otra_pata"]
        elif evento == "espera":
            canal["estado"] = "espera"
        elif evento == "retoma":
            canal["estado"] = "hablando"
        elif evento == "cuelga":
            self._canales.pop(uuid, None)
            canal["estado"] = "colgada"
            canal["causa"] = ev.get("Hangup-Cause")
        canal["cambio_at"] = ahora
        if canal["tenant_id"] is not None:
            self.publicar(canal["tenant_id"], {"tipo": "llamada", "evento": evento, "llamada": self._publico(canal)})

    @staticmethod
    def _nuevo(uuid: str, ev: dict[str, str], tid: int | None) -> dict:
        ahora = _ts(ev)
        return {
            "tenant_id": tid,
            # Reloj local, no el de FreeSWITCH: la purga no puede depender de
            # que los dos relojes coincidan.
            "_visto": time.monotonic(),
            "uuid": uuid,
            "direccion": "entrante" if ev.get("Call-Direction") == "inbound" else "saliente",
            "de": ev.get("Caller-Caller-ID-Number") or ev.get("variable_effective_caller_id_number"),
            "nombre": ev.get("Caller-Caller-ID-Name"),
            "a": ev.get("Caller-Destination-Number") or ev.get("variable_sip_to_user"),
            "campana_id": ev.get("variable_nspbx_campaign_id"),
            "estado": "iniciando",
            "inicio_at": ahora,
            "timbre_at": None,
            "contesta_at": None,
            "cambio_at": ahora,
            "otra_pata": None,
            "causa": None,
        }

    @staticmethod
    def _publico(canal: dict) -> dict:
        datos = {k: v for k, v in canal.items() if k not in ("tenant_id", "_visto")}
        timbre, contesta = canal["timbre_at"], canal["contesta_at"]
        datos["ring_ms"] = int((contesta - timbre) * 1000) if timbre and contesta and contesta >= timbre else None
        return datos

    def _purgar(self) -> None:
        corte = time.monotonic() - _VIDA_MAXIMA_S
        for uuid in [u for u, c in self._canales.items() if c["_visto"] < corte]:
            self._canales.pop(uuid, None)


tiempo_real = TiempoReal()


def _registrar_en_bus() -> None:
    from app.services.bus import bus

    bus.registrar("tr", tiempo_real.desde_otra_replica)


_registrar_en_bus()


async def mantener_conexion(cada_s: float = 5.0) -> None:
    """Mantiene abierta la conexión de eventos de ESL: si FreeSWITCH se
    reinicia o se cae la conexión, se reconecta sola."""
    from app.services import esl

    while True:
        try:
            await esl.asegurar_eventos()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Eventos de FreeSWITCH no disponibles: %s", exc)
        await asyncio.sleep(cada_s)
