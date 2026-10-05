"""Agentes humanos: sesión, estados, marcación y disposición.

docs/plan-contact-center.md, fase 3. Lo esencial:

- **Sesión clavada.** Al entrar, el backend llama a la extensión del agente
  y la deja en su conferencia `agente_<empresa>_<usuario>` toda la jornada.
  El softphone del panel la contesta solo, pero únicamente si la llamada
  trae el token de esta sesión (cabecera X-NSPBX-Agente): nadie más puede
  abrirle el micrófono al agente mandando una llamada con esa cabecera.
- **El cliente entra a la sala del agente.** Al marcar, la pata del cliente
  se origina con `&conference(...)`: cuando contesta, el agente lo oye al
  instante, sin timbre propio. Es lo que en la fase 4 permite el predictivo.
- **Estados.** LISTO, PAUSA (con código), PREVIA (viendo un lead antes de
  marcar), TIMBRANDO, EN_LLAMADA y DISPO. Cada cambio cierra un tramo y abre
  otro en `estados_agente`: de ahí salen todos los tiempos del agente.
- **Eventos.** La contestación y el cuelgue llegan por ESL
  (services/tiempo_real.py → `recibir`). El uuid de cada pata lo fija el
  backend al originar (`origination_uuid`), así se sabe de antemano qué
  evento es de quién.

Todo corre en sesiones atadas a la empresa (RLS + filtro de la aplicación).
"""

import asyncio
from dataclasses import dataclass
import logging
import os
import secrets
import uuid as uuidlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select, update

from app.core import validacion
from app.core.clock import now_local
from app.core.config import settings
from app.core.database import async_session, sesion_de_empresa
from app.models import (
    AgenteVivo,
    CallLog,
    Callback,
    CampanaAgente,
    Campaign,
    CampaignNumber,
    CodigoPausa,
    Disposicion,
    EstadoAgente,
    Lista,
    NoLlamar,
    Nota,
    SesionAgente,
    SystemSettings,
    Tenant,
    Trunk,
    User,
)
from app.services import crm, esl, horario_marcacion, hopper, integraciones, salientes

logger = logging.getLogger(__name__)

LISTO, PAUSA, PREVIA, TIMBRANDO, EN_LLAMADA, DISPO = "LISTO", "PAUSA", "PREVIA", "TIMBRANDO", "EN_LLAMADA", "DISPO"
EN_CURSO = (TIMBRANDO, EN_LLAMADA)
METODOS_AGENTE = ("manual", "vista_previa", "progresivo", "proporcional", "predictivo")
METODOS = ("voizbot", *METODOS_AGENTE)
CATEGORIAS = ("venta", "contacto", "no_contacto", "callback", "promesa", "no_llamar")
PERFIL_CONFERENCIA = "nspbx_agente"
CABECERA_TOKEN = "X-NSPBX-Agente"
PRIORIDAD_CALLBACK = 50

PAUSAS_EJEMPLO = (
    # código, nombre, pagada, máximo de minutos
    ("BREAK", "Descanso", True, 15),
    ("ALMUERZO", "Almuerzo", False, 60),
    ("CAPACITACION", "Capacitación", True, None),
    ("REUNION", "Reunión", True, None),
    ("ADMIN", "Tareas administrativas", True, None),
    ("TECNICA", "Problema técnico", True, None),
    ("PERSONAL", "Personal", False, 10),
)

DISPOSICIONES_EJEMPLO = (
    # código, nombre, categoría, contacto humano, color
    ("VENTA", "Venta", "venta", True, "#16a34a"),
    ("POTENCIAL", "Cliente potencial", "contacto", True, "#0ea5e9"),
    ("NO_INTERESADO", "No interesado", "contacto", True, "#64748b"),
    ("RECHAZADO", "Rechazado", "contacto", True, "#dc2626"),
    ("CALLBACK", "Volver a llamar", "callback", True, "#f59e0b"),
    ("SEGUIMIENTO", "Seguimiento", "callback", True, "#a855f7"),
    ("PROMESA_PAGO", "Promesa de pago", "promesa", True, "#16a34a"),
    ("NO_CONTESTA", "No contesta / buzón", "no_contacto", False, "#94a3b8"),
    ("OCUPADO", "Ocupado", "no_contacto", False, "#94a3b8"),
    ("EQUIVOCADO", "Número equivocado", "contacto", False, "#64748b"),
    ("NO_LLAMAR", "No volver a llamar", "no_llamar", True, "#991b1b"),
)


class ErrorAgente(Exception):
    """Lo que el agente intentó no se puede ahora. `codigo` es el HTTP."""

    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


def conferencia(tenant_id: int, user_id: int) -> str:
    return f"agente_{int(tenant_id)}_{int(user_id)}"


# --- Catálogos ---------------------------------------------------------------------


async def asegurar_catalogos(session, tenant_id: int) -> None:
    """Pausas y disposiciones de ejemplo, la primera vez que la empresa las
    usa. Después son suyas: las edita en Contact center."""
    if not (await session.execute(select(CodigoPausa.id).limit(1))).first():
        for i, (codigo, nombre, pagada, maximo) in enumerate(PAUSAS_EJEMPLO):
            session.add(CodigoPausa(tenant_id=tenant_id, codigo=codigo, nombre=nombre, pagada=pagada,
                                    max_minutos=maximo, activo=True, orden=i))
    if not (await session.execute(select(Disposicion.id).limit(1))).first():
        for i, (codigo, nombre, categoria, humano, color) in enumerate(DISPOSICIONES_EJEMPLO):
            session.add(Disposicion(tenant_id=tenant_id, codigo=codigo, nombre=nombre, categoria=categoria,
                                    contacto_humano=humano, color=color, activa=True, orden=i))
    await session.flush()


# --- Bitácora y estado ---------------------------------------------------------------


async def vivo_de(session, user_id: int, bloquear: bool = True) -> AgenteVivo | None:
    query = select(AgenteVivo).where(AgenteVivo.user_id == user_id)
    if bloquear:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def _tramo_abierto(session, vivo: AgenteVivo) -> EstadoAgente | None:
    return (
        await session.execute(
            select(EstadoAgente)
            .where(EstadoAgente.sesion_id == vivo.sesion_id, EstadoAgente.fin.is_(None))
            .order_by(EstadoAgente.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _transicion(session, vivo: AgenteVivo, estado: str, ahora: datetime | None = None, **campos) -> None:
    """Cierra el tramo actual y abre el nuevo. `campos` actualiza también
    el estado vivo (pausa, campaña, lead, llamada)."""
    ahora = ahora or datetime.utcnow()
    abierto = await _tramo_abierto(session, vivo)
    if abierto is not None:
        abierto.fin = ahora
    for clave, valor in campos.items():
        setattr(vivo, clave, valor)
    vivo.estado = estado
    vivo.desde = ahora
    session.add(
        EstadoAgente(
            tenant_id=vivo.tenant_id,
            user_id=vivo.user_id,
            sesion_id=vivo.sesion_id,
            estado=estado,
            codigo_pausa_id=vivo.codigo_pausa_id if estado == PAUSA else None,
            campaign_id=vivo.campaign_id,
            lead_id=vivo.lead_id,
            call_uuid=vivo.call_uuid,
            inicio=ahora,
        )
    )
    _publicar(vivo)


def foto(vivo: AgenteVivo) -> dict:
    return {
        "user_id": vivo.user_id,
        "estado": vivo.estado,
        "desde": vivo.desde,
        "codigo_pausa_id": vivo.codigo_pausa_id,
        "campanas": vivo.campanas or [],
        "audio": vivo.audio,
        "campaign_id": vivo.campaign_id,
        "lead_id": vivo.lead_id,
        "telefono": vivo.telefono,
        "contestada_at": vivo.contestada_at,
        "pausa_pendiente_id": vivo.pausa_pendiente_id,
    }


def _publicar(vivo: AgenteVivo) -> None:
    """Al bus de tiempo real (lo verá el supervisor en la fase 5)."""
    from app.services.tiempo_real import tiempo_real

    datos = foto(vivo)
    for clave in ("desde", "contestada_at"):
        if datos[clave] is not None:
            datos[clave] = datos[clave].isoformat()
    tiempo_real.publicar(vivo.tenant_id, {"tipo": "agente", "agente": datos})


def _sin_llamada() -> dict:
    return {"campaign_id": None, "lead_id": None, "call_uuid": None, "telefono": None, "contestada_at": None}


# --- FreeSWITCH -------------------------------------------------------------------------


async def _dominio(session, tenant_id: int) -> str:
    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    empresa = await session.get(Tenant, tenant_id)
    dominio = (ajustes.fs_domain if ajustes and ajustes.fs_domain else None) or (empresa.sip_domain if empresa else "")
    return validacion.exigir(validacion.HOST_RE, dominio, "Dominio SIP")


def _vars(valores: dict[str, str]) -> str:
    """Bloque {k=v,...} con los valores escapados (ver esl.originate)."""
    return ",".join(f"{k}={quote(str(v), safe='')}" for k, v in valores.items())


async def _originar_audio(session, vivo: AgenteVivo) -> None:
    extension = validacion.exigir(validacion.EXTENSION_RE, vivo.extension or "", "Extensión")
    dominio = await _dominio(session, vivo.tenant_id)
    # Sin el softphone conectado la llamada de la sesión no llega a ningún
    # lado y el agente quedaba «Sin audio» sin saber por qué.
    try:
        contacto = await esl.api(f"sofia_contact */{extension}@{dominio}")
    except Exception as exc:  # sin ESL no se puede comprobar: se intenta igual
        logger.warning("No se pudo comprobar el registro de %s: %s", extension, exc)
        contacto = ""
    if "user_not_registered" in contacto:
        raise ErrorAgente(
            f"Tu extensión {extension} no está conectada: conecta el softphone (arriba a la derecha) y vuelve a intentarlo"
        )
    vivo.audio_uuid = str(uuidlib.uuid4())
    vivo.token_audio = secrets.token_hex(16)
    vivo.audio = False
    variables = _vars({
        "origination_uuid": vivo.audio_uuid,
        "nspbx_tenant_id": str(vivo.tenant_id),
        "nspbx_agente_audio": str(vivo.user_id),
        f"sip_h_{CABECERA_TOKEN}": vivo.token_audio,
        "origination_caller_id_name": "Sesion de agente",
        "origination_caller_id_number": "0",
        "call_timeout": "40",
    })
    # endconf: si el agente se va, la sala se cierra y nadie queda hablando solo.
    await esl.bgapi(
        f"originate {{{variables}}}user/{extension}@{dominio} "
        f"&conference({conferencia(vivo.tenant_id, vivo.user_id)}@{PERFIL_CONFERENCIA}+flags{{endconf}})"
    )


async def _matar(uuid: str | None) -> str:
    if not uuid:
        return ""
    try:
        validacion.exigir(validacion.NOMBRE_RE, uuid, "uuid")
        return await esl.api(f"uuid_kill {uuid}")
    except Exception as exc:
        logger.warning("No se pudo colgar %s: %s", uuid, exc)
        return f"-ERR {exc}"


def _ruta_grabacion(tenant_id: int, call_uuid: str) -> str:
    """Misma carpeta que las demás grabaciones (config_generator)."""
    hoy = now_local()
    relativa = f"t{int(tenant_id)}/{hoy:%Y/%m/%d}"
    try:
        os.makedirs(Path(settings.recordings_dir) / relativa, exist_ok=True)
    except OSError as exc:
        logger.warning("No se pudo crear la carpeta de grabaciones %s: %s", relativa, exc)
    return f"{settings.fs_recordings_dir.rstrip('/')}/{relativa}/llamada_{call_uuid}.wav"


# --- Sesión ----------------------------------------------------------------------------


async def campanas_asignadas(session, user_id: int) -> list[Campaign]:
    return list(
        (
            await session.execute(
                select(Campaign)
                .join(CampanaAgente, CampanaAgente.campaign_id == Campaign.id)
                .where(CampanaAgente.user_id == user_id, Campaign.metodo.in_(METODOS_AGENTE))
                .order_by(Campaign.name)
            )
        ).scalars()
    )


async def entrar(session, usuario: User, campaign_ids: list[int]) -> AgenteVivo:
    if usuario.tenant_id is None:
        raise ErrorAgente("La consola de agente es de cada empresa", 403)
    existente = await vivo_de(session, usuario.id)
    if existente is not None:
        return existente
    if not usuario.extension:
        raise ErrorAgente("Necesitas una extensión asignada para trabajar como agente", 400)
    asignadas = {c.id for c in await campanas_asignadas(session, usuario.id)}
    elegidas = sorted({int(c) for c in campaign_ids})
    if not elegidas:
        raise ErrorAgente("Elige al menos una campaña", 400)
    if not set(elegidas) <= asignadas:
        raise ErrorAgente("No estás asignado a esa campaña", 403)
    await asegurar_catalogos(session, usuario.tenant_id)
    sesion = SesionAgente(tenant_id=usuario.tenant_id, user_id=usuario.id, campanas=elegidas,
                          extension=usuario.extension.number)
    session.add(sesion)
    await session.flush()
    vivo = AgenteVivo(tenant_id=usuario.tenant_id, user_id=usuario.id, sesion_id=sesion.id, estado=PAUSA,
                      campanas=elegidas, extension=usuario.extension.number, audio=False)
    session.add(vivo)
    await session.flush()
    await _transicion(session, vivo, PAUSA, codigo_pausa_id=None)
    await _originar_audio(session, vivo)
    return vivo


async def reconectar_audio(session, vivo: AgenteVivo) -> None:
    if vivo.audio:
        return
    await _matar(vivo.audio_uuid)
    await _originar_audio(session, vivo)


async def salir(session, vivo: AgenteVivo, motivo: str = "normal", forzar: bool = False) -> None:
    if not forzar and vivo.estado in EN_CURSO:
        raise ErrorAgente("Termina la llamada antes de salir")
    if not forzar and vivo.estado == DISPO:
        raise ErrorAgente("Elige la disposición de la última llamada antes de salir")
    if vivo.estado == PREVIA:
        await _soltar_lead(session, vivo)
    if vivo.estado in EN_CURSO:
        await _matar(vivo.call_uuid)
    ahora = datetime.utcnow()
    abierto = await _tramo_abierto(session, vivo)
    if abierto is not None:
        abierto.fin = ahora
    sesion = await session.get(SesionAgente, vivo.sesion_id)
    if sesion is not None:
        sesion.fin = ahora
        sesion.motivo_fin = motivo
    await _matar(vivo.audio_uuid)
    vivo.estado = "FUERA"
    _publicar(vivo)
    await session.delete(vivo)


async def listo(session, vivo: AgenteVivo) -> None:
    if vivo.estado == LISTO:
        return
    if vivo.estado not in (PAUSA,):
        raise ErrorAgente("Ahora no puedes pasar a listo")
    if not vivo.audio:
        raise ErrorAgente("Tu audio no está conectado: contesta la llamada de tu sesión o reconéctala")
    await _transicion(session, vivo, LISTO, codigo_pausa_id=None, volver_a_pausa_id=None)


async def pausar(session, vivo: AgenteVivo, codigo_pausa_id: int | None) -> None:
    if codigo_pausa_id is not None:
        codigo = await session.get(CodigoPausa, codigo_pausa_id)
        if codigo is None or codigo.tenant_id != vivo.tenant_id or not codigo.activo:
            raise ErrorAgente("Código de pausa inexistente", 400)
    if vivo.estado in (*EN_CURSO, DISPO):
        # Se aplica al disponer: una llamada no se corta por pedir pausa.
        vivo.pausa_pendiente_id = codigo_pausa_id or 0
        _publicar(vivo)
        return
    if vivo.estado == PREVIA:
        await _soltar_lead(session, vivo)
    await _transicion(session, vivo, PAUSA, codigo_pausa_id=codigo_pausa_id, **_sin_llamada())


# --- Marcar ------------------------------------------------------------------------------


async def _campana_del_agente(session, vivo: AgenteVivo, campaign_id: int) -> Campaign:
    if campaign_id not in (vivo.campanas or []):
        raise ErrorAgente("No estás trabajando en esa campaña", 403)
    campana = await session.get(Campaign, campaign_id)
    if campana is None or campana.tenant_id != vivo.tenant_id or campana.metodo not in METODOS_AGENTE:
        raise ErrorAgente("Campaña no encontrada", 404)
    return campana


async def _lead_manual(session, campana: Campaign, telefono: str) -> CampaignNumber:
    """El número escrito a mano queda como lead de la campaña (con su
    contacto): así tiene disposición, historial y reciclaje como los demás."""
    lead = (
        await session.execute(
            select(CampaignNumber).where(CampaignNumber.campaign_id == campana.id, CampaignNumber.phone == telefono)
        )
    ).scalars().first()
    if lead is not None:
        return lead
    lista = (
        await session.execute(
            select(Lista).where(Lista.campaign_id == campana.id, Lista.origen == "manual", Lista.nombre == "Marcación manual")
        )
    ).scalars().first()
    if lista is None:
        lista = Lista(tenant_id=campana.tenant_id, campaign_id=campana.id, nombre="Marcación manual", origen="manual")
        session.add(lista)
        await session.flush()
    contacto = await crm.asegurar(session, campana.tenant_id, telefono, None, "manual",
                                  await crm.por_claves(session, [crm.clave_telefono(telefono)]))
    await session.flush()
    lead = CampaignNumber(tenant_id=campana.tenant_id, campaign_id=campana.id, phone=telefono, status="pending",
                          lista_id=lista.id, contacto_id=contacto.id if contacto else None)
    session.add(lead)
    await session.flush()
    return lead


async def marcar(session, vivo: AgenteVivo, campaign_id: int, telefono: str | None = None,
                 lead_id: int | None = None, tomado: bool = False) -> str:
    """Llama al cliente y lo mete en la sala del agente. Devuelve el uuid.
    `tomado`: el lead ya salió del hopper (que cuenta el intento)."""
    if vivo.estado not in (LISTO, PAUSA, PREVIA):
        raise ErrorAgente("Ya estás en una llamada")
    if not vivo.audio:
        raise ErrorAgente("Tu audio no está conectado: contesta la llamada de tu sesión o reconéctala")
    campana = await _campana_del_agente(session, vivo, campaign_id)
    ya_reservado = tomado
    if vivo.estado == PREVIA:
        if lead_id is None or lead_id != vivo.lead_id:
            raise ErrorAgente("Marca el lead que estás viendo o sáltalo")
        ya_reservado = True
    if lead_id is not None:
        lead = await session.get(CampaignNumber, lead_id)
        if lead is None or lead.tenant_id != vivo.tenant_id or lead.campaign_id != campana.id:
            raise ErrorAgente("Lead no encontrado", 404)
        if lead.agente_id not in (None, vivo.user_id):
            raise ErrorAgente("Ese lead está reservado para otro agente", 403)
    else:
        if not telefono:
            raise ErrorAgente("Escribe el número", 400)
        validacion.exigir(validacion.TELEFONO_RE, telefono, "Teléfono")
        lead = await _lead_manual(session, campana, telefono)

    call_uuid, tramos, valores = await preparar_llamada(session, campana, lead, agente_id=vivo.user_id)
    await esl.bgapi(
        f"originate {{{_vars(valores)}}}{'|'.join(tramos)} "
        f"&conference({conferencia(vivo.tenant_id, vivo.user_id)}@{PERFIL_CONFERENCIA})"
    )

    ahora = datetime.utcnow()
    if not ya_reservado:
        lead.attempts += 1
    lead.status = "dialing"
    lead.ultimo_intento_at = ahora
    # Si marcó a mano desde una pausa, vuelve a esa pausa al terminar.
    volver = vivo.codigo_pausa_id if vivo.estado == PAUSA else vivo.volver_a_pausa_id
    await _transicion(session, vivo, TIMBRANDO, ahora, campaign_id=campana.id, lead_id=lead.id,
                      call_uuid=call_uuid, telefono=lead.phone, contestada_at=None,
                      volver_a_pausa_id=volver, codigo_pausa_id=None)
    return call_uuid


@dataclass
class ContextoLlamada:
    """Lo que es de la empresa y la campaña, no del número: se calcula una vez
    por tanda (el predictivo lanza decenas por vuelta; recalcular la política
    de salientes por cada número era la mitad del tiempo de la vuelta)."""

    politica: object
    troncal: Trunk
    tramos_de: list[Trunk]
    slug: str
    # El hopper ya descartó los de no llamar en la misma transacción.
    dnc_verificado: bool = False


async def contexto_llamada(session, campana: Campaign, dnc_verificado: bool = False) -> ContextoLlamada:
    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    if not horario_marcacion.puede_marcar(ajustes, campana.ai_intent, now_local()):
        raise ErrorAgente("Fuera de la franja de marcación de la campaña")
    troncal = await session.get(Trunk, campana.trunk_id) if campana.trunk_id else None
    if troncal is None or troncal.tenant_id != campana.tenant_id or not troncal.enabled:
        raise ErrorAgente("La campaña no tiene una troncal habilitada")
    from app.services.config_generator import orden_troncales

    troncales = (await session.execute(select(Trunk).where(Trunk.tenant_id == campana.tenant_id))).scalars().all()
    empresa = await session.get(Tenant, campana.tenant_id)
    return ContextoLlamada(
        politica=await salientes.politica_de(session, campana.tenant_id),
        troncal=troncal,
        tramos_de=orden_troncales(troncales, principal_id=troncal.id),
        slug=empresa.slug,
        dnc_verificado=dnc_verificado,
    )


async def revisar_campana(session, campana: Campaign) -> tuple[str | None, ContextoLlamada | None]:
    """Lo que impide marcar en TODA la campaña (licencia, troncal, franja,
    salientes cortadas), antes de tomar números. Antes esto se descubría al
    preparar cada llamada y el número quedaba «fallido»: sin troncal, una
    campaña quemaba su base entera sin marcar a nadie. Devuelve (motivo,
    None) o (None, contexto para reusar en la tanda)."""
    from app.services import licensing

    st = licensing.estado(await licensing.obtener(session, campana.tenant_id))
    if st != "ok":
        return f"La licencia de la empresa está {st}", None
    try:
        contexto = await contexto_llamada(session, campana, dnc_verificado=True)
    except ErrorAgente as exc:
        return exc.mensaje, None
    if contexto.politica.bloqueo:
        return contexto.politica.bloqueo, None
    return None, contexto


async def preparar_llamada(session, campana: Campaign, lead: CampaignNumber, agente_id: int | None,
                           contexto: ContextoLlamada | None = None) -> tuple[str, list[str], dict]:
    """Comprueba que se puede llamar (política de salientes, no llamar,
    franja de marcación, troncal) y arma la pata del cliente: uuid, tramos
    por troncal y variables del canal. La usan la marcación del agente y el
    predictivo (services/predictivo.py): las mismas reglas para todos."""
    contexto = contexto or await contexto_llamada(session, campana)
    motivo = salientes.motivo_bloqueo(lead.phone, contexto.politica)
    if motivo:
        raise ErrorAgente(motivo)
    if not contexto.dnc_verificado and await crm.en_no_llamar(session, lead.phone):
        raise ErrorAgente("Ese número está en la lista de no llamar")
    troncal = contexto.troncal
    validacion.exigir(validacion.TELEFONO_RE, lead.phone, "Teléfono")
    tramos = [f"sofia/gateway/{contexto.slug}_{t.name}/{lead.phone}" for t in contexto.tramos_de]

    call_uuid = str(uuidlib.uuid4())
    valores = {
        "origination_uuid": call_uuid,
        "ignore_early_media": "true",
        "call_timeout": "30",
        "nspbx_tenant_id": str(campana.tenant_id),
        "nspbx_saliente": str(campana.tenant_id),
        "nspbx_campaign_id": str(campana.id),
        "nspbx_lead_id": str(lead.id),
        "nspbx_customer": lead.phone,
    }
    if agente_id is not None:
        valores["nspbx_agente_id"] = str(agente_id)
    cid = troncal.caller_id_number or troncal.username
    if cid:
        valores["origination_caller_id_number"] = cid
    if campana.grabacion == "todas":
        ruta = _ruta_grabacion(campana.tenant_id, call_uuid)
        valores["nspbx_recording"] = ruta
        valores["RECORD_STEREO"] = "false"
        valores["execute_on_answer"] = f"record_session {ruta}"
    return call_uuid, tramos, valores


async def colgar(session, vivo: AgenteVivo) -> None:
    if vivo.estado not in EN_CURSO:
        raise ErrorAgente("No hay una llamada en curso")
    respuesta = await _matar(vivo.call_uuid)
    if "No such channel" in respuesta:
        # El cuelgue ya pasó y su evento se perdió: se resuelve acá.
        await _al_colgar(session, vivo, "NORMAL_CLEARING")


# --- Vista previa -----------------------------------------------------------------------


async def siguiente(session, vivo: AgenteVivo) -> CampaignNumber | None:
    """El próximo lead de una campaña de vista previa, reservado para este
    agente. None si no hay ninguno ahora."""
    if vivo.estado not in (LISTO, PAUSA):
        raise ErrorAgente("Termina lo que estás haciendo antes de pedir otro lead")
    if not vivo.audio:
        raise ErrorAgente("Tu audio no está conectado: contesta la llamada de tu sesión o reconéctala")
    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    for campaign_id in vivo.campanas or []:
        campana = await session.get(Campaign, campaign_id)
        if campana is None or campana.metodo != "vista_previa" or campana.status != "running":
            continue
        if not horario_marcacion.puede_marcar(ajustes, campana.ai_intent, now_local()):
            continue
        tomados = await hopper.tomar(session, campana, 1, agente_id=vivo.user_id)
        if tomados:
            lead = tomados[0]
            volver = vivo.codigo_pausa_id if vivo.estado == PAUSA else None
            await _transicion(session, vivo, PREVIA, campaign_id=campana.id, lead_id=lead.id, call_uuid=None,
                              telefono=lead.phone, contestada_at=None, volver_a_pausa_id=volver,
                              codigo_pausa_id=None)
            return lead
    return None


async def _soltar_lead(session, vivo: AgenteVivo) -> None:
    """El lead en vista previa vuelve a la cola, sin gastar el intento."""
    if vivo.lead_id is None:
        return
    lead = await session.get(CampaignNumber, vivo.lead_id)
    if lead is not None and lead.status == "dialing":
        lead.status = "pending"
        lead.attempts = max(0, lead.attempts - 1)


async def saltar(session, vivo: AgenteVivo) -> None:
    if vivo.estado != PREVIA:
        raise ErrorAgente("No estás viendo ningún lead")
    await _soltar_lead(session, vivo)
    await _volver(session, vivo)


async def _volver(session, vivo: AgenteVivo) -> None:
    """Después de una llamada o un lead: pausa pedida, pausa previa o listo."""
    pendiente = vivo.pausa_pendiente_id
    volver = vivo.volver_a_pausa_id
    vivo.pausa_pendiente_id = None
    vivo.volver_a_pausa_id = None
    if pendiente is not None:
        await _transicion(session, vivo, PAUSA, codigo_pausa_id=pendiente or None, **_sin_llamada())
    elif volver is not None:
        await _transicion(session, vivo, PAUSA, codigo_pausa_id=volver, **_sin_llamada())
    elif not vivo.audio:
        await _transicion(session, vivo, PAUSA, codigo_pausa_id=await _pausa_tecnica(session), **_sin_llamada())
    else:
        await _transicion(session, vivo, LISTO, codigo_pausa_id=None, **_sin_llamada())


async def _pausa_tecnica(session) -> int | None:
    return (await session.execute(select(CodigoPausa.id).where(CodigoPausa.codigo == "TECNICA"))).scalar_one_or_none()


# --- Eventos de FreeSWITCH ------------------------------------------------------------------


def _resultado(causa: str) -> str:
    causa = (causa or "").upper()
    if "USER_BUSY" in causa:
        return "busy"
    if causa in ("NO_ANSWER", "NO_USER_RESPONSE", "ORIGINATOR_CANCEL", "NORMAL_CLEARING", "ALLOTTED_TIMEOUT"):
        return "noanswer"
    return "failed"


async def _al_colgar(session, vivo: AgenteVivo, causa: str) -> None:
    if vivo.estado == EN_LLAMADA:
        await _transicion(session, vivo, DISPO)
        return
    if vivo.estado != TIMBRANDO:
        return
    # No contestaron: el lead se recicla solo (como en el marcador) y el
    # agente sigue, sin disposición que elegir.
    lead = await session.get(CampaignNumber, vivo.lead_id) if vivo.lead_id else None
    campana = await session.get(Campaign, vivo.campaign_id) if vivo.campaign_id else None
    if lead is not None:
        resultado = _resultado(causa)
        lead.last_error = causa or None
        if lead.attempts > (campana.retries if campana else 0):
            lead.status = resultado
        else:
            hopper.reprogramar(lead, campana, resultado)
    await _volver(session, vivo)


async def recibir(ev: dict[str, str]) -> None:
    """Eventos de canal (los manda services/tiempo_real.py)."""
    nombre = ev.get("Event-Name")
    if nombre not in ("CHANNEL_ANSWER", "CHANNEL_HANGUP_COMPLETE"):
        return
    uuid = ev.get("Unique-ID") or ""
    try:
        tid = int(ev.get("variable_nspbx_tenant_id") or 0)
    except ValueError:
        return
    es_audio = bool(ev.get("variable_nspbx_agente_audio"))
    es_cliente = bool(ev.get("variable_nspbx_agente_id"))
    if not tid or not (es_audio or es_cliente):
        return
    async with sesion_de_empresa(tid) as session:
        columna = AgenteVivo.audio_uuid if es_audio else AgenteVivo.call_uuid
        vivo = (await session.execute(select(AgenteVivo).where(columna == uuid).with_for_update())).scalar_one_or_none()
        if vivo is None:
            return
        if es_audio:
            if nombre == "CHANNEL_ANSWER":
                vivo.audio = True
                _publicar(vivo)
            else:
                vivo.audio = False
                vivo.audio_uuid = None
                if vivo.estado in EN_CURSO:
                    # Sin el agente no hay con quién hablar: se corta y, al
                    # volver, el agente dispone la llamada.
                    vivo.pausa_pendiente_id = await _pausa_tecnica(session) or 0
                    await _matar(vivo.call_uuid)
                elif vivo.estado in (LISTO, PREVIA):
                    if vivo.estado == PREVIA:
                        await _soltar_lead(session, vivo)
                    await _transicion(session, vivo, PAUSA, codigo_pausa_id=await _pausa_tecnica(session),
                                      **_sin_llamada())
                else:
                    _publicar(vivo)
        else:
            if nombre == "CHANNEL_ANSWER" and vivo.estado == TIMBRANDO:
                await _transicion(session, vivo, EN_LLAMADA, contestada_at=datetime.utcnow())
                await integraciones.emitir_seguro(session, vivo.tenant_id, "llamada.contestada", integraciones.datos_llamada(vivo))
            elif nombre == "CHANNEL_HANGUP_COMPLETE":
                await _al_colgar(session, vivo, ev.get("Hangup-Cause") or "")
        await session.commit()


# --- Disposición ---------------------------------------------------------------------------


async def disponer(
    session,
    vivo: AgenteVivo,
    usuario: User,
    disposicion_id: int,
    nota: str | None = None,
    callback_at: datetime | None = None,
    callback_propio: bool = True,
) -> None:
    if vivo.estado != DISPO:
        raise ErrorAgente("No hay una llamada que disponer")
    disp = await session.get(Disposicion, disposicion_id)
    if disp is None or disp.tenant_id != vivo.tenant_id or not disp.activa:
        raise ErrorAgente("Disposición inexistente", 400)
    lead = await session.get(CampaignNumber, vivo.lead_id) if vivo.lead_id else None
    campana = await session.get(Campaign, vivo.campaign_id) if vivo.campaign_id else None
    ahora = datetime.utcnow()
    if disp.categoria == "callback":
        if callback_at is None:
            raise ErrorAgente("Indica cuándo volver a llamar", 400)
        callback_at = callback_at.replace(tzinfo=None)
        if callback_at <= ahora:
            raise ErrorAgente("La fecha del callback tiene que ser futura", 400)
        if callback_at > ahora + timedelta(days=180):
            raise ErrorAgente("El callback no puede ser a más de 6 meses", 400)

    if lead is not None:
        lead.disposicion_id = disp.id
        lead.last_error = None
        if disp.categoria in ("venta", "contacto", "promesa"):
            lead.status = "done"
        elif disp.categoria == "no_contacto":
            resultado = "busy" if disp.codigo == "OCUPADO" else "noanswer"
            if lead.attempts > (campana.retries if campana else 0):
                lead.status = resultado
            else:
                hopper.reprogramar(lead, campana, resultado, ahora)
        elif disp.categoria == "callback":
            lead.status = "pending"
            lead.proximo_intento_at = callback_at
            lead.agente_id = usuario.id if callback_propio else None
            lead.prioridad = max(lead.prioridad or 0, PRIORIDAD_CALLBACK)
            # Un callback no gasta el intento: es una cita, no un fracaso.
            lead.attempts = max(0, lead.attempts - 1)
            session.add(Callback(
                tenant_id=vivo.tenant_id, lead_id=lead.id, campaign_id=lead.campaign_id, contacto_id=lead.contacto_id,
                agente_id=usuario.id if callback_propio else None, cuando=callback_at, estado="pendiente",
                nota=(nota or "").strip() or None, creado_por=usuario.id,
            ))
            await integraciones.emitir_seguro(session, vivo.tenant_id, "callback.creado", {
                "lead_id": lead.id, "campana_id": lead.campaign_id, "contacto_id": lead.contacto_id, "telefono": lead.phone,
                "cuando": callback_at.isoformat() + "Z", "agente_id": usuario.id if callback_propio else None,
                "nota": (nota or "").strip() or None,
            })
        elif disp.categoria == "no_llamar":
            lead.status = "no_llamar"
            clave = crm.clave_telefono(lead.phone)
            existe = (await session.execute(select(NoLlamar).where(NoLlamar.telefono_clave == clave))).scalar_one_or_none()
            if existe is None:
                session.add(NoLlamar(tenant_id=vivo.tenant_id, telefono=lead.phone, telefono_clave=clave,
                                     motivo=f"Disposición del agente: {disp.nombre}",
                                     creado_por=usuario.full_name or usuario.username))
            await integraciones.emitir_seguro(session, vivo.tenant_id, "lead.no_llamar", {
                "telefono": lead.phone, "lead_id": lead.id, "campana_id": lead.campaign_id, "contacto_id": lead.contacto_id,
                "motivo": f"Disposición del agente: {disp.nombre}", "origen": "agente", "agente_id": usuario.id,
            })
        # Los callbacks anteriores de este lead quedan cumplidos.
        await session.execute(
            update(Callback)
            .where(Callback.lead_id == lead.id, Callback.estado == "pendiente", Callback.cuando <= ahora + timedelta(minutes=5))
            .values(estado="hecho")
        )
        if nota and nota.strip() and lead.contacto_id:
            session.add(Nota(tenant_id=vivo.tenant_id, contacto_id=lead.contacto_id, user_id=usuario.id,
                             autor=usuario.full_name or usuario.username, texto=nota.strip()[:4000]))

    # La disposición queda en el tramo de la llamada y en el historial.
    if vivo.call_uuid:
        await session.execute(
            update(EstadoAgente)
            .where(EstadoAgente.sesion_id == vivo.sesion_id, EstadoAgente.call_uuid == vivo.call_uuid)
            .values(disposicion_id=disp.id)
        )
        await session.execute(update(CallLog).where(CallLog.uuid == vivo.call_uuid).values(disposicion_id=disp.id))
    await integraciones.emitir_seguro(session, vivo.tenant_id, "llamada.disposicionada", integraciones.datos_llamada(
        vivo, telefono=lead.phone if lead else None, contacto_id=lead.contacto_id if lead else None,
        disposicion={"id": disp.id, "codigo": disp.codigo, "nombre": disp.nombre, "categoria": disp.categoria},
        nota=(nota or "").strip() or None, callback_at=callback_at.isoformat() + "Z" if callback_at else None,
    ))
    await _volver(session, vivo)


async def disposicion_de_llamada(session, call_uuid: str) -> int | None:
    """Para el CDR: si el agente ya dispuso la llamada antes de que llegara."""
    return (
        await session.execute(
            select(EstadoAgente.disposicion_id)
            .where(EstadoAgente.call_uuid == call_uuid, EstadoAgente.disposicion_id.is_not(None))
            .limit(1)
        )
    ).scalar_one_or_none()


# --- Progresivo -------------------------------------------------------------------------------


class Motor:
    """Marcación progresiva: a cada agente LISTO de una campaña progresiva
    en curso le marca el siguiente lead. Un agente, una llamada."""

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
                logger.exception("Error en el ciclo progresivo")
            await asyncio.sleep(1)

    async def ciclo(self) -> int:
        """Una vuelta. Devuelve cuántas llamadas lanzó."""
        async with async_session() as dueno:
            listos = (
                await dueno.execute(
                    select(AgenteVivo.tenant_id, AgenteVivo.user_id).where(
                        AgenteVivo.estado == LISTO, AgenteVivo.audio.is_(True)
                    )
                )
            ).all()
        lanzadas = 0
        for tenant_id, user_id in listos:
            async with sesion_de_empresa(tenant_id) as session:
                vivo = await vivo_de(session, user_id)
                if vivo is None or vivo.estado != LISTO or not vivo.audio:
                    continue
                ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
                for campaign_id in vivo.campanas or []:
                    campana = await session.get(Campaign, campaign_id)
                    if campana is None or campana.metodo != "progresivo" or campana.status != "running":
                        continue
                    if not horario_marcacion.puede_marcar(ajustes, campana.ai_intent, now_local()):
                        continue
                    motivo, _ = await revisar_campana(session, campana)
                    if motivo:
                        # La campaña espera sin tomar números (ver revisar_campana).
                        continue
                    tomados = await hopper.tomar(session, campana, 1, agente_id=vivo.user_id)
                    if not tomados:
                        continue
                    lead = tomados[0]
                    try:
                        await marcar(session, vivo, campana.id, lead_id=lead.id, tomado=True)
                        lanzadas += 1
                    except ErrorAgente as exc:
                        # No se pudo (no llamar, política, troncal): el lead
                        # queda con el motivo y no se reintenta en esta vuelta.
                        lead.status = "failed" if "no llamar" not in exc.mensaje else "no_llamar"
                        lead.last_error = exc.mensaje[:500]
                    break
                await session.commit()
        return lanzadas


motor = Motor()


async def cerrar_todas(motivo: str = "reinicio", tenant_id: int | None = None) -> None:
    """Al arrancar el backend: las sesiones de antes ya no tienen audio ni
    eventos confiables. El agente vuelve a entrar. Con `tenant_id`, solo las
    de esa empresa (al moverla de servidor: su audio queda en el anterior)."""
    consulta = select(AgenteVivo.tenant_id, AgenteVivo.user_id)
    if tenant_id is not None:
        consulta = consulta.where(AgenteVivo.tenant_id == tenant_id)
    async with async_session() as dueno:
        vivos = (await dueno.execute(consulta)).all()
    for tenant_id, user_id in vivos:
        async with sesion_de_empresa(tenant_id) as session:
            vivo = await vivo_de(session, user_id)
            if vivo is not None:
                await salir(session, vivo, motivo, forzar=True)
                await session.commit()

