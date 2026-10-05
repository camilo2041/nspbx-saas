"""Supervisor: agentes y campañas en vivo, monitoreo y wallboard.

docs/plan-contact-center.md, fase 5. Lo esencial:

- **Foto en vivo.** Sale de `agentes_vivos` (el motor de agentes la lleva al
  día), del motor predictivo (llamadas timbrando y clientes esperando) y de
  `metricas_campana`. Los segundos «en el estado» los calcula el servidor:
  el reloj del navegador del supervisor no tiene por qué coincidir.
- **Monitoreo por conferencia.** El agente vive en su sala (ver
  services/agentes.py), así que escuchar, susurrar e intervenir son entrar a
  esa sala con distintos permisos de audio:
    - escuchar: entra muteado;
    - susurrar: el agente lo oye y el cliente no (`relate <sup> <cliente>
      nospeak`, por cada cliente que entre a la sala);
    - intervenir: los tres hablan.
  El supervisor SIEMPRE entra muteado y el backend le abre el micrófono
  después de fijar las relaciones: si fuera al revés, el cliente alcanzaría
  a oír el primer instante de un susurro.
  La pata del supervisor lleva el token de esta escucha en la cabecera
  X-NSPBX-Agente: el softphone del panel la contesta sola solo con ese
  token (igual que la sesión del agente).
- **Wallboard.** Para una TV sin usuario: un token de solo lectura que vence
  y se revoca; se guarda su hash, no el token.

Todo lo que cambia algo pasa por la API (`/api/supervision/...`), así que
queda en la auditoría con quién, a quién y cuándo (core/auditoria.py).
"""

import asyncio
import hashlib
import logging
import secrets
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core import validacion
from app.core.database import async_session
from app.models import AgenteVivo, Campaign, CampaignNumber, CodigoPausa, MetricaCampana, MonitoreoVivo, User
from app.core.clock import now_local
from app.services import agentes, esl, predictivo

logger = logging.getLogger(__name__)

MODOS = ("escuchar", "susurrar", "intervenir")
CABECERA_TOKEN = agentes.CABECERA_TOKEN
# Cuántas veces se busca al cliente en la sala tras contestar: entra a la
# conferencia un instante después del evento.
_REINTENTOS_CLIENTE = 6
_PAUSA_REINTENTO_S = 0.5


class ErrorSupervision(Exception):
    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# --- Foto en vivo ---------------------------------------------------------------------


def _segundos(desde: datetime | None, ahora: datetime) -> int | None:
    return max(0, int((ahora - desde).total_seconds())) if desde else None


async def agentes_en_vivo(session) -> list[dict]:
    ahora = datetime.utcnow()
    vivos = (await session.execute(select(AgenteVivo))).scalars().all()
    if not vivos:
        return []
    usuarios = {
        u.id: u for u in (await session.execute(select(User).where(User.id.in_([v.user_id for v in vivos])))).unique().scalars()
    }
    pausas = {p.id: p for p in (await session.execute(select(CodigoPausa))).scalars()}
    campanas = dict((await session.execute(select(Campaign.id, Campaign.name))).all())
    monitores = await monitoreo.por_agente(session)
    filas = []
    for v in vivos:
        u = usuarios.get(v.user_id)
        pausa = pausas.get(v.codigo_pausa_id) if v.estado == agentes.PAUSA and v.codigo_pausa_id else None
        en_estado = _segundos(v.desde, ahora)
        mon = monitores.get(v.user_id)
        filas.append({
            "user_id": v.user_id,
            "nombre": (u.full_name or u.username) if u else f"#{v.user_id}",
            "extension": v.extension,
            "estado": v.estado,
            "desde": v.desde.isoformat() if v.desde else None,
            "en_estado_s": en_estado,
            "audio": bool(v.audio),
            "pausa": {"id": pausa.id, "nombre": pausa.nombre, "max_minutos": pausa.max_minutos} if pausa else None,
            # Pasó el máximo del código de pausa: el supervisor lo ve en rojo.
            "pausa_excedida": bool(pausa and pausa.max_minutos and en_estado is not None and en_estado > pausa.max_minutos * 60),
            "pausa_pendiente": v.pausa_pendiente_id is not None,
            "campanas": [{"id": c, "nombre": campanas.get(c, f"#{c}")} for c in (v.campanas or [])],
            "campaign_id": v.campaign_id,
            "campana": campanas.get(v.campaign_id) if v.campaign_id else None,
            "telefono": v.telefono,
            "lead_id": v.lead_id,
            "hablado_s": _segundos(v.contestada_at, ahora) if v.estado == agentes.EN_LLAMADA else None,
            "monitoreo": {"supervisor_id": mon.supervisor_id, "modo": mon.modo} if mon else None,
        })
    orden = {agentes.EN_LLAMADA: 0, agentes.TIMBRANDO: 1, agentes.DISPO: 2, agentes.PREVIA: 3, agentes.LISTO: 4, agentes.PAUSA: 5}
    filas.sort(key=lambda f: (orden.get(f["estado"], 9), f["nombre"].lower()))
    return filas


async def campanas_en_vivo(session, agentes_vivos: list[dict] | None = None) -> list[dict]:
    """Campañas con agentes: en curso, o con alguien conectado."""
    agentes_vivos = agentes_vivos if agentes_vivos is not None else await agentes_en_vivo(session)
    con_gente = {c["id"] for a in agentes_vivos for c in a["campanas"]}
    campanas = (
        await session.execute(
            select(Campaign)
            .where(Campaign.metodo.in_(agentes.METODOS_AGENTE), or_(Campaign.status == "running", Campaign.id.in_(con_gente or [0])))
            .order_by(Campaign.name)
        )
    ).scalars().all()
    if not campanas:
        return []
    ids = [c.id for c in campanas]
    ahora_dt = datetime.utcnow()
    listos_hopper = dict(
        (
            await session.execute(
                select(CampaignNumber.campaign_id, func.count())
                .where(
                    CampaignNumber.campaign_id.in_(ids),
                    CampaignNumber.status == "pending",
                    or_(CampaignNumber.proximo_intento_at.is_(None), CampaignNumber.proximo_intento_at <= ahora_dt),
                )
                .group_by(CampaignNumber.campaign_id)
            )
        ).all()
    )
    hoy = {
        m.campaign_id: m
        for m in (
            await session.execute(
                select(MetricaCampana).where(MetricaCampana.campaign_id.in_(ids), MetricaCampana.fecha == now_local().date())
            )
        ).scalars()
    }
    filas = []
    for c in campanas:
        suyos = [a for a in agentes_vivos if any(x["id"] == c.id for x in a["campanas"])]
        por_estado = {e: 0 for e in (agentes.LISTO, agentes.PAUSA, agentes.PREVIA, agentes.TIMBRANDO, agentes.EN_LLAMADA, agentes.DISPO)}
        for a in suyos:
            # Un agente en llamada cuenta en la campaña de esa llamada, no en todas las suyas.
            if a["estado"] in (agentes.TIMBRANDO, agentes.EN_LLAMADA, agentes.DISPO) and a["campaign_id"] not in (None, c.id):
                continue
            por_estado[a["estado"]] = por_estado.get(a["estado"], 0) + 1
        m = hoy.get(c.id)
        datos = {
            "id": c.id,
            "nombre": c.name,
            "metodo": c.metodo,
            "status": c.status,
            "agentes": {"conectados": len(suyos), **{k.lower(): v for k, v in por_estado.items()}},
            "hopper": listos_hopper.get(c.id, 0),
            "nivel_marcacion": c.nivel_marcacion,
            "nivel_max": c.nivel_max,
            "nivel_actual": c.nivel_actual,
            "abandono_objetivo": c.abandono_objetivo,
            "max_concurrency": c.max_concurrency,
            "hoy": {
                "intentos": m.intentos if m else 0,
                "contestadas": m.contestadas if m else 0,
                "asignadas": m.asignadas if m else 0,
                "abandonadas": m.abandonadas if m else 0,
                "abandono_pct": round(100.0 * m.abandonadas / m.contestadas, 2) if m and m.contestadas else None,
            },
            "llamadas": None,
            "ultimos_15": None,
        }
        if c.metodo in predictivo.METODOS:
            foto = predictivo.instantanea(c.id)
            datos["llamadas"] = {"timbrando": foto["timbrando"], "en_espera": foto["en_espera"]}
            datos["ultimos_15"] = foto["ultimos_15"]
        filas.append(datos)
    return filas


async def resumen(session, tenant_id: int) -> dict:
    """Lo del wallboard: cifras grandes de toda la operación."""
    from app.services.tiempo_real import tiempo_real

    vivos = await agentes_en_vivo(session)
    campanas = await campanas_en_vivo(session, vivos)
    por_estado: dict[str, int] = {}
    for a in vivos:
        por_estado[a["estado"]] = por_estado.get(a["estado"], 0) + 1
    contestadas = sum(c["hoy"]["contestadas"] for c in campanas)
    abandonadas = sum(c["hoy"]["abandonadas"] for c in campanas)
    llamadas = tiempo_real.llamadas(tenant_id)
    return {
        "generado_at": datetime.utcnow().isoformat(),
        "agentes": {
            "conectados": len(vivos),
            "listos": por_estado.get(agentes.LISTO, 0),
            "en_llamada": por_estado.get(agentes.EN_LLAMADA, 0) + por_estado.get(agentes.TIMBRANDO, 0),
            "en_pausa": por_estado.get(agentes.PAUSA, 0),
            "disposicion": por_estado.get(agentes.DISPO, 0) + por_estado.get(agentes.PREVIA, 0),
            "pausas_excedidas": sum(1 for a in vivos if a["pausa_excedida"]),
        },
        "llamadas": {
            "activas": sum(1 for ll in llamadas if ll.get("estado") == "hablando"),
            "timbrando": sum((c["llamadas"] or {}).get("timbrando", 0) for c in campanas),
            "en_espera": sum((c["llamadas"] or {}).get("en_espera", 0) for c in campanas),
        },
        "hoy": {
            "intentos": sum(c["hoy"]["intentos"] for c in campanas),
            "contestadas": contestadas,
            "abandonadas": abandonadas,
            "abandono_pct": round(100.0 * abandonadas / contestadas, 2) if contestadas else None,
        },
        "campanas": [
            {
                "id": c["id"], "nombre": c["nombre"], "metodo": c["metodo"], "status": c["status"],
                "agentes": c["agentes"], "hoy": c["hoy"], "llamadas": c["llamadas"],
                "abandono_objetivo": c["abandono_objetivo"],
            }
            for c in campanas
        ],
        # Solo nombre y estado: una TV en un pasillo no muestra teléfonos.
        "agentes_lista": [
            {"nombre": a["nombre"], "estado": a["estado"], "en_estado_s": a["en_estado_s"],
             "pausa": a["pausa"]["nombre"] if a["pausa"] else None, "pausa_excedida": a["pausa_excedida"]}
            for a in vivos
        ],
    }


# --- Acciones sobre el agente ---------------------------------------------------------------


async def _vivo(session, user_id: int) -> AgenteVivo:
    vivo = await agentes.vivo_de(session, user_id)
    if vivo is None:
        raise ErrorSupervision("Ese agente no está conectado", 404)
    return vivo


async def forzar_pausa(session, user_id: int, codigo_pausa_id: int | None) -> AgenteVivo:
    """Si está en llamada, la pausa queda pendiente: la llamada no se corta."""
    vivo = await _vivo(session, user_id)
    try:
        await agentes.pausar(session, vivo, codigo_pausa_id)
    except agentes.ErrorAgente as exc:
        raise ErrorSupervision(exc.mensaje, exc.codigo) from exc
    return vivo


async def sacar(session, user_id: int, cortar_llamada: bool = False) -> None:
    vivo = await _vivo(session, user_id)
    if vivo.estado in agentes.EN_CURSO and not cortar_llamada:
        raise ErrorSupervision("El agente está en una llamada: confirma que quieres cortarla")
    await monitoreo.cerrar_sala(session, vivo.user_id)
    await agentes.salir(session, vivo, "supervisor", forzar=True)


# --- Monitoreo ---------------------------------------------------------------------------------


@dataclass
class Monitor:
    uuid: str
    tenant_id: int
    supervisor_id: int
    agente_id: int
    modo: str
    token: str
    contestado: bool = False
    creado: datetime = field(default_factory=datetime.utcnow)

    @property
    def sala(self) -> str:
        return agentes.conferencia(self.tenant_id, self.agente_id)


def leer_miembros(texto: str) -> list[dict]:
    """Salida de `conference <sala> list`: id;registro;uuid;nombre;número;flags;…"""
    miembros = []
    for linea in (texto or "").splitlines():
        partes = linea.split(";")
        if len(partes) < 6 or not partes[0].strip().isdigit():
            continue
        miembros.append({"id": partes[0].strip(), "uuid": partes[2].strip(), "flags": partes[5].strip()})
    return miembros


def _snap(f: MonitoreoVivo) -> Monitor:
    return Monitor(f.uuid, f.tenant_id, f.supervisor_id, f.agente_id, f.modo, f.token, bool(f.contestado), f.created_at)


class Monitoreo:
    """Las escuchas en curso viven en la tabla `monitoreos` (una por agente y
    una por supervisor, garantizado por la base aunque dos réplicas reciban
    el pedido a la vez)."""

    async def _fila(self, session, **filtro) -> MonitoreoVivo | None:
        q = select(MonitoreoVivo)
        for clave, valor in filtro.items():
            q = q.where(getattr(MonitoreoVivo, clave) == valor)
        return (await session.execute(q.limit(1))).scalar_one_or_none()

    async def de_supervisor(self, session, supervisor_id: int) -> Monitor | None:
        f = await self._fila(session, supervisor_id=supervisor_id)
        return _snap(f) if f else None

    async def de_agente(self, session, agente_id: int) -> Monitor | None:
        f = await self._fila(session, agente_id=agente_id)
        return _snap(f) if f else None

    async def por_agente(self, session) -> dict[int, Monitor]:
        return {f.agente_id: _snap(f) for f in (await session.execute(select(MonitoreoVivo))).scalars()}

    async def iniciar(self, session, supervisor: User, agente_id: int, modo: str) -> Monitor:
        if modo not in MODOS:
            raise ErrorSupervision("Modo inválido", 400)
        if supervisor.tenant_id is None:
            raise ErrorSupervision("El monitoreo es de cada empresa", 403)
        if agente_id == supervisor.id:
            raise ErrorSupervision("No puedes monitorearte a ti mismo", 400)
        vivo = await _vivo(session, agente_id)
        if not vivo.audio:
            raise ErrorSupervision("El audio del agente no está conectado: no hay sala que escuchar")
        actual = await self.de_supervisor(session, supervisor.id)
        if actual is not None and actual.agente_id == agente_id:
            await self.cambiar_modo(session, actual, modo)
            return actual
        if actual is not None:
            await self.detener(session, actual)
        if await self.de_agente(session, agente_id) is not None:
            raise ErrorSupervision("Otro supervisor ya está monitoreando a este agente")
        if not supervisor.extension:
            raise ErrorSupervision("Necesitas una extensión asignada para monitorear", 400)
        extension = validacion.exigir(validacion.EXTENSION_RE, supervisor.extension.number, "Extensión")
        dominio = await agentes._dominio(session, supervisor.tenant_id)
        nombre_agente = (await session.execute(select(User.full_name).where(User.id == agente_id))).scalar_one_or_none()
        fila = MonitoreoVivo(tenant_id=supervisor.tenant_id, uuid=str(uuidlib.uuid4()), supervisor_id=supervisor.id,
                             agente_id=agente_id, modo=modo, token=secrets.token_hex(16), contestado=False)
        session.add(fila)
        try:
            await session.flush()
        except IntegrityError:
            # Otro supervisor lo tomó en el mismo instante (quizá en otra réplica).
            await session.rollback()
            raise ErrorSupervision("Otro supervisor ya está monitoreando a este agente")
        monitor = _snap(fila)
        variables = agentes._vars({
            "origination_uuid": monitor.uuid,
            "nspbx_tenant_id": str(supervisor.tenant_id),
            "nspbx_supervisor": str(supervisor.id),
            f"sip_h_{CABECERA_TOKEN}": monitor.token,
            "origination_caller_id_name": f"Monitoreo {nombre_agente or agente_id}"[:60],
            "origination_caller_id_number": "0",
            "call_timeout": "30",
        })
        # Entra muteado; el modo se aplica al contestar (ver docstring).
        await esl.bgapi(
            f"originate {{{variables}}}user/{extension}@{dominio} "
            f"&conference({monitor.sala}@{agentes.PERFIL_CONFERENCIA}+flags{{mute}})"
        )
        return monitor

    async def cambiar_modo(self, session, monitor: Monitor, modo: str) -> None:
        if modo not in MODOS:
            raise ErrorSupervision("Modo inválido", 400)
        fila = await self._fila(session, uuid=monitor.uuid)
        if fila is None:
            raise ErrorSupervision("Esa escucha ya terminó", 404)
        fila.modo = monitor.modo = modo
        await session.flush()
        if fila.contestado:
            await self.aplicar(monitor)

    async def detener(self, session, monitor: Monitor) -> None:
        fila = await self._fila(session, uuid=monitor.uuid)
        if fila is not None:
            await session.delete(fila)
            await session.flush()
        await agentes._matar(monitor.uuid)

    async def cerrar_sala(self, session, agente_id: int) -> None:
        monitor = await self.de_agente(session, agente_id)
        if monitor is not None:
            await self.detener(session, monitor)

    async def _sigue(self, monitor: Monitor) -> Monitor | None:
        async with _sesion(monitor.tenant_id) as session:
            f = await self._fila(session, uuid=monitor.uuid)
            return _snap(f) if f else None

    async def _miembros(self, sala: str) -> list[dict]:
        validacion.exigir(validacion.NOMBRE_RE, sala, "sala")
        return leer_miembros(await esl.api(f"conference {sala} list"))

    async def aplicar(self, monitor: Monitor, esperar_cliente: bool = False) -> bool:
        """Fija el audio del supervisor según el modo. Con `esperar_cliente`
        no hace nada (y devuelve False) mientras el cliente no esté en la
        sala: así el supervisor sigue muteado hasta que se lo relaciona."""
        miembros = await self._miembros(monitor.sala)
        yo = next((m for m in miembros if m["uuid"] == monitor.uuid), None)
        if yo is None:
            return False
        async with _sesion(monitor.tenant_id) as session:
            vivo = await agentes.vivo_de(session, monitor.agente_id, bloquear=False)
        agente_uuid = vivo.audio_uuid if vivo else None
        clientes = [m for m in miembros if m["uuid"] not in (monitor.uuid, agente_uuid)]
        if esperar_cliente and not clientes:
            return False
        sala = monitor.sala
        relacion = "nospeak" if monitor.modo == "susurrar" else "clear"
        for cli in clientes:
            await esl.api(f"conference {sala} relate {yo['id']} {cli['id']} {relacion}")
        if monitor.modo == "escuchar":
            await esl.api(f"conference {sala} mute {yo['id']}")
        else:
            await esl.api(f"conference {sala} unmute {yo['id']}")
        return True

    async def _aplicar_seguro(self, monitor: Monitor, esperar_cliente: bool = False) -> bool:
        try:
            return await self.aplicar(monitor, esperar_cliente)
        except Exception as exc:
            logger.warning("No se pudo aplicar el monitoreo %s: %s", monitor.uuid, exc)
            return False

    async def esperar_y_aplicar(self, monitor: Monitor) -> None:
        """Tras entrar un cliente: reintenta hasta verlo en la sala. Si nunca
        aparece (colgó antes), aplica igual para no dejar mudo al supervisor."""
        for _ in range(_REINTENTOS_CLIENTE):
            actual = await self._sigue(monitor)
            if actual is None:
                return
            if await self._aplicar_seguro(actual, esperar_cliente=True):
                return
            await asyncio.sleep(_PAUSA_REINTENTO_S)
        actual = await self._sigue(monitor)
        if actual is not None:
            await self._aplicar_seguro(actual)

    async def antes_de_cliente(self, tenant_id: int, agente_id: int, session=None) -> asyncio.Task | None:
        """Un cliente va a entrar a la sala de un agente al que se le está
        susurrando: se mutea al supervisor ANTES de que entre y se le vuelve a
        abrir cuando el cliente ya quedó sin oírlo. Con `session`, usa la de
        quien llama (el predictivo: una transacción por asignación)."""
        if session is not None:
            monitor = await self.de_agente(session, agente_id)
        else:
            async with _sesion(tenant_id) as propia:
                monitor = await self.de_agente(propia, agente_id)
        if monitor is None or not monitor.contestado or monitor.modo != "susurrar":
            return None
        try:
            yo = next((m for m in await self._miembros(monitor.sala) if m["uuid"] == monitor.uuid), None)
            if yo is not None:
                await esl.api(f"conference {monitor.sala} mute {yo['id']}")
        except Exception as exc:
            logger.warning("No se pudo mutear al supervisor %s: %s", monitor.uuid, exc)
        return asyncio.create_task(self.esperar_y_aplicar(monitor))

    async def recibir(self, ev: dict[str, str]) -> None:
        nombre = ev.get("Event-Name")
        uuid = ev.get("Unique-ID") or ""
        try:
            tid = int(ev.get("variable_nspbx_tenant_id") or 0)
        except ValueError:
            return
        if ev.get("variable_nspbx_supervisor"):
            if not tid or nombre not in ("CHANNEL_ANSWER", "CHANNEL_HANGUP_COMPLETE"):
                return
            async with _sesion(tid) as session:
                fila = await self._fila(session, uuid=uuid)
                if fila is None:
                    return
                if nombre == "CHANNEL_HANGUP_COMPLETE":
                    await session.delete(fila)
                    await session.commit()
                    return
                fila.contestado = True
                monitor = _snap(fila)
                await session.commit()
            await self._aplicar_seguro(monitor)
            return
        # Marcación manual y progresiva: el cliente entra a la sala al
        # contestar. (El predictivo avisa desde su motor, antes de pasarlo.)
        if nombre == "CHANNEL_ANSWER" and ev.get("variable_nspbx_agente_id") and not ev.get("variable_nspbx_pred") and tid:
            try:
                agente_id = int(ev["variable_nspbx_agente_id"])
            except ValueError:
                return
            await self.antes_de_cliente(tid, agente_id)

    async def limpiar_todo(self) -> None:
        """Al tomar el liderazgo: las escuchas de antes no tienen eventos
        confiables (sus patas se cortan con la sala del agente)."""
        async with async_session() as dueno:
            await dueno.execute(delete(MonitoreoVivo))
            await dueno.commit()


def _sesion(tenant_id: int):
    from app.core.database import sesion_de_empresa

    return sesion_de_empresa(tenant_id)


monitoreo = Monitoreo()


# --- Wallboard -------------------------------------------------------------------------------------

DURACION_MAX_WALLBOARD = timedelta(days=90)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def nuevo_token() -> tuple[str, str]:
    """(token para mostrar una vez, hash para guardar)."""
    token = "wb_" + secrets.token_urlsafe(32)
    return token, hash_token(token)
