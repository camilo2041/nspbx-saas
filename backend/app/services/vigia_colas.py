"""Vigía de los grupos de atención: foto en vivo, aviso de posición y
devolución de llamada. Corre solo en la réplica líder, cada INTERVALO_SEG.

En cada vuelta, por cada grupo activo, le pregunta a mod_callcenter quién
espera (`queue list members`) y cómo están sus agentes (`queue list agents`):

1. **Foto** (tablero en vivo de Supervisión y del wallboard): cuántos
   esperan, la espera más larga, agentes libres / ocupados / en pausa, y de
   la última hora (del historial) ofrecidas, atendidas, abandonadas y nivel
   de servicio. Se manda por el bus a las demás réplicas.
2. **Aviso periódico** a quien espera (`uuid_broadcast` sobre la música):
   con «anunciar posición», «Gracias por esperar» + la posición; con
   «devolución», además «marca 1 y te devolvemos la llamada». Cada CADA_SEG.
3. **Devoluciones**: quien marcó 1 queda anotado (el CDR trae
   `nspbx_pide_devolucion`, api/calls.py). Cuando hay un agente libre y nadie
   que llegó antes sigue esperando, la central lo llama
   (`loopback/<número>/<contexto>`, por las reglas de salida de la empresa) y
   al contestar lo pone de primero en la fila (`devolver_<grupo>_<número>`,
   config_generator._append_devolucion). Hasta INTENTOS_MAX intentos.
"""

import asyncio
import calendar
import logging
import re
import time
import uuid as uuidlib
from datetime import datetime, timedelta

from sqlalchemy import case, func, select

from app.core.database import async_session
from app.models import CallLog, Devolucion, Queue, Tenant
from app.services import esl, voice_prompts
from app.services.ajustes import dominios_tenants
from app.services.posicion_colas import CADA_SEG, PRIMERA_SEG, esperando
from app.services.queues_sync import _queue_key

logger = logging.getLogger(__name__)

INTERVALO_SEG = 5
HISTORIAL_CADA_SEG = 30
UMBRAL_SERVICIO_S = 20
VIGENCIA_FOTO_S = 30
INTENTOS_MAX = 3
REINTENTO = timedelta(minutes=2)
TIMBRADO_DEVOLUCION_S = 40
NUMERO_RE = re.compile(r"^\+?[0-9]{7,15}$")

_OCUPADO = {"In a queue call", "Receiving", "Idle"}


def agentes_de(salida: str) -> dict:
    """Libres, ocupados y en pausa de `callcenter_config queue list agents`."""
    lineas = [l for l in (salida or "").splitlines() if "|" in l]
    cuenta = {"libres": 0, "ocupados": 0, "pausa": 0, "total": 0}
    if not lineas:
        return cuenta
    campos = lineas[0].split("|")
    for linea in lineas[1:]:
        fila = dict(zip(campos, linea.split("|")))
        estado, situacion = fila.get("status", ""), fila.get("state", "")
        if estado == "Logged Out" or not estado:
            continue
        cuenta["total"] += 1
        if estado == "On Break":
            cuenta["pausa"] += 1
        elif situacion in _OCUPADO:
            cuenta["ocupados"] += 1
        elif estado.startswith("Available") and situacion == "Waiting":
            cuenta["libres"] += 1
        else:
            cuenta["ocupados"] += 1
    return cuenta


def audio_de(delante: int | None, ofrecer_devolucion: bool) -> str | None:
    """Lo que se le dice a quien espera: «Gracias por esperar», la posición
    (si el grupo la anuncia) y la oferta de devolución (si la tiene)."""
    claves = ["cola_aviso"]
    if delante is not None:
        claves.append(f"cola_delante_{delante if delante <= 9 else 'mas'}")
    if ofrecer_devolucion:
        claves.append("cola_devolucion_oferta")
    partes = [p for p in (voice_prompts.prompt_path(k) for k in claves) if p]
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else "file_string://" + "!".join(partes)


class Vigia:
    def __init__(self):
        self._tarea: asyncio.Task | None = None
        self._ultimo_aviso: dict[str, float] = {}
        self._fotos: dict[int, tuple[float, list[dict]]] = {}  # tenant -> (monotonic, grupos)
        self._historial: dict[int, dict] = {}  # queue_id -> cifras de la última hora
        self._historial_at = 0.0
        self._devolviendo: dict[int, tuple[int, str]] = {}  # devolución -> (grupo, uuid del canal que la llama)
        self._recien_ascendida = True
        self._en_vuelo: set[asyncio.Task] = set()  # las que esperan el resultado del originate

    # --- Ciclo de vida -------------------------------------------------------------------

    def start(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._recien_ascendida = True
            self._tarea = asyncio.create_task(self._bucle())

    async def stop(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
        self._ultimo_aviso.clear()
        self._fotos.clear()

    async def _bucle(self) -> None:
        while True:
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error en el vigía de los grupos")
            await asyncio.sleep(INTERVALO_SEG)

    # --- Fotos ---------------------------------------------------------------------------

    def foto(self, tenant_id: int) -> list[dict]:
        """La última foto de los grupos de la empresa (esta réplica o la líder)."""
        f = self._fotos.get(tenant_id)
        if f is None or time.monotonic() - f[0] > VIGENCIA_FOTO_S:
            return []
        return f[1]

    def desde_otra_replica(self, datos: dict) -> None:
        try:
            self._fotos[int(datos["tenant"])] = (time.monotonic(), list(datos.get("grupos") or []))
        except (KeyError, TypeError, ValueError):
            return

    async def _actualizar_historial(self, dueno, ahora_utc: datetime) -> None:
        """Cifras de la última hora por grupo (cada HISTORIAL_CADA_SEG)."""
        if time.monotonic() - self._historial_at < HISTORIAL_CADA_SEG:
            return
        self._historial_at = time.monotonic()
        filas = (
            await dueno.execute(
                select(
                    CallLog.tenant_id, CallLog.cola, func.count(),
                    func.sum(case((CallLog.cola_resultado == "atendida", 1), else_=0)),
                    func.sum(case((CallLog.cola_resultado == "abandonada", 1), else_=0)),
                    func.sum(case(((CallLog.cola_resultado == "atendida") & (CallLog.cola_espera_s <= UMBRAL_SERVICIO_S), 1), else_=0)),
                )
                .where(CallLog.cola.is_not(None), CallLog.started_at >= ahora_utc - timedelta(hours=1))
                .group_by(CallLog.tenant_id, CallLog.cola)
            )
        ).all()
        self._historial = {
            (tid, cola): {
                "ofrecidas": int(n), "atendidas": int(at or 0), "abandonadas": int(ab or 0),
                "nivel_servicio_pct": round(100.0 * int(en or 0) / int(n), 1) if n else None,
            }
            for tid, cola, n, at, ab, en in filas
        }

    # --- La vuelta -----------------------------------------------------------------------

    async def ciclo(self, ahora: float | None = None) -> dict:
        """Un repaso de todos los grupos. Devuelve {avisos, devoluciones}."""
        from app.services.bus import bus

        ahora = ahora or time.time()
        ahora_utc = datetime.utcnow()
        # El calendario de las empresas (festivos y fechas especiales) que usa el
        # marcador de campañas, que también corre en la líder.
        try:
            from app.services import festivos

            await festivos.refrescar()
        except Exception:
            logger.exception("No se pudo refrescar el calendario de festivos")
        if self._recien_ascendida:
            # Las que quedaron «llamando» de una líder anterior vuelven a la fila.
            self._recien_ascendida = False
            async with async_session() as dueno:
                from sqlalchemy import update

                await dueno.execute(update(Devolucion).where(Devolucion.estado == "llamando").values(estado="pendiente"))
                await dueno.commit()
        async with async_session() as dueno:
            grupos = (await dueno.execute(select(Queue).where(Queue.enabled.is_(True)))).scalars().all()
            if not grupos:
                return {"avisos": 0, "devoluciones": 0}
            dominios = await dominios_tenants(dueno)
            await self._actualizar_historial(dueno, ahora_utc)
            pendientes = (
                await dueno.execute(
                    select(Devolucion).where(Devolucion.estado == "pendiente",
                                             (Devolucion.proximo_at.is_(None)) | (Devolucion.proximo_at <= ahora_utc))
                    .order_by(Devolucion.pedida_at)
                )
            ).scalars().all()
            contextos = {t.id: t.dialplan_context for t in (await dueno.execute(select(Tenant))).scalars()}
        por_grupo: dict[int, list[Devolucion]] = {}
        for d in pendientes:
            por_grupo.setdefault(d.queue_id, []).append(d)

        fotos: dict[int, list[dict]] = {}
        vistos: set[str] = set()
        avisos = devueltas = 0
        en_curso = {canal for _, canal in self._devolviendo.values()}
        for q in grupos:
            if q.tenant_id not in dominios:
                continue
            qkey = _queue_key(q.name, dominios[q.tenant_id])
            try:
                miembros = esperando(await esl.api(f"callcenter_config queue list members {qkey}", tenant_id=q.tenant_id))
                agentes = agentes_de(await esl.api(f"callcenter_config queue list agents {qkey}", tenant_id=q.tenant_id))
            except Exception as exc:
                logger.debug("No se pudo ver el grupo %s: %s", q.id, exc)
                continue
            devolucion = bool(getattr(q, "devolucion", False))

            # 2. Avisos a quien espera.
            if q.announce_position or devolucion:
                for delante, m in enumerate(miembros):
                    uuid = m["session_uuid"]
                    vistos.add(uuid)
                    desde = self._ultimo_aviso.get(uuid, m["_llego"] - (CADA_SEG - PRIMERA_SEG))
                    if ahora - desde < CADA_SEG:
                        continue
                    ofrecer = devolucion and uuid not in en_curso and bool(NUMERO_RE.fullmatch(m.get("cid_number") or ""))
                    audio = audio_de(delante if q.announce_position else None, ofrecer)
                    if audio is None:
                        continue
                    self._ultimo_aviso[uuid] = ahora
                    try:
                        await esl.api(f"uuid_broadcast {uuid} {audio} aleg", tenant_id=q.tenant_id)
                        avisos += 1
                    except Exception as exc:
                        logger.debug("No se pudo avisar a %s: %s", uuid, exc)

            # 3. Devoluciones: con un agente libre y sin nadie que haya llegado antes esperando.
            cola_devol = por_grupo.get(q.id, [])
            libres = agentes["libres"] - sum(1 for grupo, _ in self._devolviendo.values() if grupo == q.id)
            if devolucion and cola_devol and libres > 0:
                d = cola_devol[0]
                # Respeta el turno: nadie que haya llegado antes de pedirla sigue esperando.
                antes = [m for m in miembros if m["session_uuid"] not in en_curso and m["_llego"] < _epoch(d.pedida_at)]
                if d.id not in self._devolviendo and not antes:
                    if await self._devolver(d, q, contextos.get(q.tenant_id)):
                        devueltas += 1

            # 1. Foto.
            fotos.setdefault(q.tenant_id, []).append({
                "id": q.id, "nombre": q.name, "numero": q.extension,
                "esperando": len(miembros),
                "espera_max_s": int(ahora - miembros[0]["_llego"]) if miembros and miembros[0]["_llego"] else 0,
                "agentes": agentes,
                "devoluciones_pendientes": len(cola_devol),
                "ultima_hora": self._historial.get((q.tenant_id, q.name)) or {
                    "ofrecidas": 0, "atendidas": 0, "abandonadas": 0, "nivel_servicio_pct": None},
            })

        for uuid in list(self._ultimo_aviso):
            if uuid not in vistos:
                self._ultimo_aviso.pop(uuid, None)
        marca = time.monotonic()
        for tid, lista in fotos.items():
            self._fotos[tid] = (marca, lista)
            bus.emitir_pronto("colas", {"tenant": tid, "grupos": lista})
        return {"avisos": avisos, "devoluciones": devueltas}

    # --- Devolver una llamada --------------------------------------------------------------

    async def _devolver(self, d: Devolucion, q: Queue, contexto: str | None) -> bool:
        if not contexto or not NUMERO_RE.fullmatch(d.numero or ""):
            await _marcar(d.id, "fallida", "Número no válido para devolver la llamada")
            return False
        canal = str(uuidlib.uuid4())
        variables = [
            f"origination_uuid={canal}",
            f"nspbx_tenant_id={int(d.tenant_id)}",
            f"nspbx_devolucion_id={int(d.id)}",
            "ignore_early_media=true",
            f"call_timeout={TIMBRADO_DEVOLUCION_S}",
        ]
        if d.did and NUMERO_RE.fullmatch(d.did):
            # Al cliente le aparece el número que había marcado.
            variables.append(f"origination_caller_id_number={d.did}")
        comando = (
            f"originate {{{','.join(variables)}}}loopback/{d.numero}/{contexto} "
            f"devolver_{q.extension}_{d.numero} XML {contexto}"
        )
        self._devolviendo[d.id] = (q.id, canal)
        await _marcar(d.id, "llamando", None, intento=True)
        tarea = asyncio.create_task(self._esperar_resultado(d.id, d.tenant_id, d.intentos + 1, comando))
        self._en_vuelo.add(tarea)
        tarea.add_done_callback(self._en_vuelo.discard)
        return True

    async def _esperar_resultado(self, devolucion_id: int, tenant_id: int, intento: int, comando: str) -> None:
        try:
            await esl.bgapi_wait(comando, timeout=TIMBRADO_DEVOLUCION_S + 20, tenant_id=tenant_id)
        except Exception as exc:
            motivo = str(exc).replace("-ERR", "").strip()[:150] or "no contestó"
            if intento >= INTENTOS_MAX:
                await _marcar(devolucion_id, "fallida", f"No contestó en {intento} intentos ({motivo})")
            else:
                await _marcar(devolucion_id, "pendiente", f"Intento {intento}: {motivo}",
                              proximo=datetime.utcnow() + REINTENTO)
        else:
            await _marcar(devolucion_id, "hecha", "Contestó y entró de primero a la fila")
        finally:
            self._devolviendo.pop(devolucion_id, None)


def _epoch(utc: datetime) -> float:
    """pedida_at es UTC sin zona; joined_epoch de FreeSWITCH es epoch."""
    return float(calendar.timegm(utc.timetuple()))


async def _marcar(devolucion_id: int, estado: str, detalle: str | None, intento: bool = False,
                  proximo: datetime | None = None) -> None:
    async with async_session() as s:
        d = await s.get(Devolucion, devolucion_id)
        if d is None:
            return
        d.estado = estado
        if detalle is not None:
            d.detalle = detalle
        if intento:
            d.intentos += 1
        d.proximo_at = proximo
        if estado in ("hecha", "fallida"):
            d.hecha_at = datetime.utcnow()
        await s.commit()


async def anotar(session, variables: dict, tenant_id: int, caller: str | None) -> Devolucion | None:
    """El CDR de quien marcó 1 (sin commit). Una sola pendiente por número y grupo."""
    try:
        queue_id = int(variables.get("nspbx_pide_devolucion") or 0)
    except ValueError:
        return None
    numero = (caller or "").strip()
    if not queue_id or not NUMERO_RE.fullmatch(numero):
        logger.info("Devolución pedida sin un número válido (%r): no se puede devolver", numero)
        return None
    q = await session.get(Queue, queue_id)
    if q is None or q.tenant_id != tenant_id:
        return None
    ya = (
        await session.execute(
            select(Devolucion.id).where(Devolucion.tenant_id == tenant_id, Devolucion.queue_id == queue_id,
                                        Devolucion.numero == numero, Devolucion.estado.in_(("pendiente", "llamando")))
        )
    ).first()
    if ya:
        return None
    did = next((v for v in (variables.get("sip_req_user"), variables.get("sip_to_user")) if v and NUMERO_RE.fullmatch(v)), None)
    d = Devolucion(tenant_id=tenant_id, queue_id=queue_id, numero=numero, did=did, pedida_at=datetime.utcnow())
    session.add(d)
    return d


vigia = Vigia()


def _registrar_en_bus() -> None:
    from app.services.bus import bus

    bus.registrar("colas", vigia.desde_otra_replica)


_registrar_en_bus()
