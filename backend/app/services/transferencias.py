"""Poner en espera y transferir una llamada en curso, desde el panel.

Todo se hace en FreeSWITCH (ESL) y no en el teléfono: así funciona igual con
el softphone del navegador, la app o un teléfono de escritorio, y la
transferencia siempre entra por el dialplan de la empresa (sus reglas de
salida, horarios, buzones y grupos).

Hay dos formas de estar en una llamada, y cada una se maneja distinto:

- **Consola de agente** (services/agentes.py): el agente está en su sala
  (conferencia) y el cliente entra a ella. El cliente sale de la sala para
  esperar con música, para ir a otro destino o para quedar puenteado con la
  persona consultada (`uuid_bridge`).
- **Softphone** (extensión a extensión, grupos, salientes): las dos patas
  están puenteadas. La espera es `uuid_hold` (re-INVITE al teléfono propio
  y música a la otra pata), la directa es `uuid_transfer -bleg` y la
  consultada es `att_xfer` corriendo en la pata propia: al colgar quien
  transfiere, FreeSWITCH une al cliente con la persona consultada.
"""

import json
import logging
import uuid as uuidlib
from dataclasses import dataclass

from sqlalchemy import select

from app.core import validacion
from app.models import AgenteVivo, Extension, Queue, Tenant, User
from app.services import agentes, esl

logger = logging.getLogger(__name__)

MUSICA = "local_stream://moh"


class ErrorTransferencia(Exception):
    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


@dataclass
class Llamada:
    """La llamada en curso de alguien."""

    tenant_id: int
    extension: str
    dominio: str
    contexto: str
    propia: str  # pata del teléfono de quien transfiere
    otra: str  # la otra pata (el cliente)


def _destino_valido(destino: str) -> str:
    destino = (destino or "").strip().replace(" ", "")
    if not validacion.TELEFONO_RE.fullmatch(destino):
        raise ErrorTransferencia("Escribe una extensión, un grupo o un número", 422)
    return destino


async def _contexto(session, tenant_id: int) -> tuple[str, str]:
    empresa = await session.get(Tenant, tenant_id)
    return await agentes._dominio(session, tenant_id), empresa.dialplan_context


async def _cadena(session, tenant_id: int, destino: str, dominio: str, contexto: str) -> str:
    """Cómo se llama a `destino` desde FreeSWITCH: una extensión directo a su
    teléfono; lo demás (grupo, buzón, número externo) por el dialplan."""
    es_extension = (
        await session.execute(
            select(Extension.id).where(Extension.tenant_id == tenant_id, Extension.number == destino, Extension.enabled)
        )
    ).first()
    if es_extension:
        return f"user/{destino}@{dominio}"
    return f"loopback/{destino}/{contexto}"


# --- Encontrar la llamada --------------------------------------------------------------


async def _llamadas_de(tenant_id: int, extension: str, dominio: str) -> list[tuple[str, str]]:
    """(pata propia, otra pata) de cada llamada puenteada de la extensión,
    según `show calls` (presence_id es <ext>@<dominio> en las dos direcciones:
    ver el dial-string del directorio)."""
    crudo = await esl.api("show calls as json", tenant_id=tenant_id)
    try:
        filas = json.loads(crudo).get("rows") or []
    except (ValueError, AttributeError):
        return []
    yo = f"{extension}@{dominio}"
    salida = []
    for f in filas:
        if f.get("presence_id") == yo and f.get("b_uuid"):
            salida.append((f["uuid"], f["b_uuid"]))
        elif f.get("b_presence_id") == yo and f.get("uuid"):
            salida.append((f["b_uuid"], f["uuid"]))
    return salida


async def llamada_de(session, usuario: User) -> Llamada:
    if usuario.tenant_id is None or usuario.extension is None:
        raise ErrorTransferencia("Tu usuario no tiene una extensión", 400)
    dominio, contexto = await _contexto(session, usuario.tenant_id)
    ext = usuario.extension.number
    try:
        pares = await _llamadas_de(usuario.tenant_id, ext, dominio)
    except Exception as exc:
        raise ErrorTransferencia(f"No se pudo consultar la central: {exc}", 503) from None
    if not pares:
        raise ErrorTransferencia("No tienes una llamada en curso")
    if len(pares) > 1:
        raise ErrorTransferencia("Tienes más de una llamada a la vez: cuelga una para transferir")
    propia, otra = pares[0]
    for u in (propia, otra):
        validacion.exigir(validacion.NOMBRE_RE, u, "uuid")
    return Llamada(usuario.tenant_id, ext, dominio, contexto, propia, otra)


async def _agente_en_llamada(session, usuario: User) -> AgenteVivo | None:
    vivo = (
        await session.execute(select(AgenteVivo).where(AgenteVivo.user_id == usuario.id).with_for_update())
    ).scalar_one_or_none()
    if vivo is None or vivo.estado != agentes.EN_LLAMADA or not vivo.call_uuid:
        return None
    return vivo


async def _api(comando: str, tenant_id: int) -> str:
    respuesta = await esl.api(comando, tenant_id=tenant_id)
    if respuesta.strip().startswith("-ERR"):
        raise ErrorTransferencia(f"La central no pudo hacerlo: {respuesta.strip()[5:] or respuesta}", 409)
    return respuesta


# --- Espera ------------------------------------------------------------------------------


async def espera(session, usuario: User, activar: bool) -> dict:
    vivo = await _agente_en_llamada(session, usuario)
    if vivo is not None:
        if vivo.consulta_uuid:
            raise ErrorTransferencia("Termina o cancela la consulta primero")
        if activar and not vivo.en_espera:
            await _api(f"uuid_transfer {vivo.call_uuid} playback:{MUSICA} inline", vivo.tenant_id)
        elif not activar and vivo.en_espera:
            await _volver_a_la_sala(vivo)
        vivo.en_espera = activar
        agentes._publicar(vivo)
        await session.commit()
        return {"en_espera": activar}
    llamada = await llamada_de(session, usuario)
    await _api(f"uuid_hold {'' if activar else 'off '}{llamada.propia}", llamada.tenant_id)
    return {"en_espera": activar}


async def _volver_a_la_sala(vivo: AgenteVivo) -> None:
    sala = f"{agentes.conferencia(vivo.tenant_id, vivo.user_id)}@{agentes.PERFIL_CONFERENCIA}"
    await _api(f"uuid_transfer {vivo.call_uuid} conference:{sala} inline", vivo.tenant_id)


# --- Transferir ----------------------------------------------------------------------------


async def transferir(session, usuario: User, destino: str, consultada: bool) -> dict:
    destino = _destino_valido(destino)
    if usuario.extension is not None and destino == usuario.extension.number:
        raise ErrorTransferencia("No puedes transferirte la llamada a ti mismo", 422)
    vivo = await _agente_en_llamada(session, usuario)
    if vivo is not None:
        return await _transferir_agente(session, vivo, destino, consultada)
    llamada = await llamada_de(session, usuario)
    if not consultada:
        await _api(f"uuid_transfer {llamada.propia} -bleg {destino} XML {llamada.contexto}", llamada.tenant_id)
        return {"estado": "transferida", "destino": destino}
    cadena = await _cadena(session, llamada.tenant_id, destino, llamada.dominio, llamada.contexto)
    variables = agentes._vars({
        "nspbx_tenant_id": str(llamada.tenant_id),
        "nspbx_consulta_de": llamada.propia,
        "origination_caller_id_number": llamada.extension,
    })
    # att_xfer en la pata propia, mientras sigue puenteada: el cliente pasa a
    # oír música y quien transfiere habla con el destino. Al colgar quien
    # transfiere (o «Completar»), FreeSWITCH une al cliente con el destino;
    # si el destino cuelga, vuelve con el cliente.
    await _api(f"uuid_broadcast {llamada.propia} att_xfer::{{{variables}}}{cadena} aleg", llamada.tenant_id)
    return {"estado": "consultando", "destino": destino}


async def _transferir_agente(session, vivo: AgenteVivo, destino: str, consultada: bool) -> dict:
    dominio, contexto = await _contexto(session, vivo.tenant_id)
    if vivo.consulta_uuid:
        raise ErrorTransferencia("Ya estás consultando: completa o cancela esa transferencia")
    if not consultada:
        await _api(f"uuid_transfer {vivo.call_uuid} {destino} XML {contexto}", vivo.tenant_id)
        # La llamada sigue, pero ya no es del agente: pasa a disponerla. El
        # cuelgue de ese canal, cuando llegue, ya no le cambia el estado.
        await agentes._transicion(session, vivo, agentes.DISPO, en_espera=False)
        await session.commit()
        return {"estado": "transferida", "destino": destino}

    # Consultada: el cliente espera con música y el destino entra a la sala.
    if not vivo.en_espera:
        await _api(f"uuid_transfer {vivo.call_uuid} playback:{MUSICA} inline", vivo.tenant_id)
    consulta = str(uuidlib.uuid4())
    cadena = await _cadena(session, vivo.tenant_id, destino, dominio, contexto)
    variables = agentes._vars({
        "origination_uuid": consulta,
        "nspbx_tenant_id": str(vivo.tenant_id),
        "origination_caller_id_number": vivo.extension or "0",
        "origination_caller_id_name": "Transferencia",
        "call_timeout": "40",
    })
    sala = f"{agentes.conferencia(vivo.tenant_id, vivo.user_id)}@{agentes.PERFIL_CONFERENCIA}"
    await esl.bgapi(f"originate {{{variables}}}{cadena} &conference({sala})", tenant_id=vivo.tenant_id)
    vivo.en_espera = True
    vivo.consulta_uuid = consulta
    vivo.consulta_destino = destino
    agentes._publicar(vivo)
    await session.commit()
    return {"estado": "consultando", "destino": destino}


async def completar(session, usuario: User) -> dict:
    """Une al cliente con la persona consultada y se sale de la llamada."""
    vivo = await _agente_en_llamada(session, usuario)
    if vivo is not None:
        if not vivo.consulta_uuid:
            raise ErrorTransferencia("No hay una consulta en curso")
        existe = (await esl.api(f"uuid_exists {vivo.consulta_uuid}", tenant_id=vivo.tenant_id)).strip()
        if existe != "true":
            await _cancelar_agente(session, vivo)
            raise ErrorTransferencia("La persona a la que consultabas ya colgó: el cliente volvió contigo")
        await _api(f"uuid_bridge {vivo.call_uuid} {vivo.consulta_uuid}", vivo.tenant_id)
        destino = vivo.consulta_destino
        await agentes._transicion(session, vivo, agentes.DISPO, en_espera=False, consulta_uuid=None, consulta_destino=None)
        await session.commit()
        return {"estado": "transferida", "destino": destino}
    # Softphone: att_xfer une las otras dos patas cuando quien transfiere cuelga.
    llamada = await llamada_de(session, usuario)
    await _api(f"uuid_kill {llamada.propia}", llamada.tenant_id)
    return {"estado": "transferida"}


async def cancelar(session, usuario: User) -> dict:
    """Corta la consulta y vuelve con el cliente."""
    vivo = await _agente_en_llamada(session, usuario)
    if vivo is not None:
        if not vivo.consulta_uuid:
            raise ErrorTransferencia("No hay una consulta en curso")
        await _cancelar_agente(session, vivo)
        return {"estado": "en_llamada"}
    if usuario.tenant_id is None or usuario.extension is None:
        raise ErrorTransferencia("Tu usuario no tiene una extensión", 400)
    # La pata consultada lleva nspbx_consulta_de=<pata propia>; se corta por
    # esa marca (esté timbrando o ya hablando) y att_xfer devuelve al cliente.
    llamada = await llamada_de(session, usuario)
    await _api(f"hupall NORMAL_CLEARING nspbx_consulta_de {llamada.propia}", llamada.tenant_id)
    return {"estado": "en_llamada"}


async def _cancelar_agente(session, vivo: AgenteVivo) -> None:
    if vivo.consulta_uuid:
        await agentes._matar(vivo.consulta_uuid)
    await _volver_a_la_sala(vivo)
    vivo.en_espera = False
    vivo.consulta_uuid = None
    vivo.consulta_destino = None
    agentes._publicar(vivo)
    await session.commit()


async def unir_a_los_tres(session, usuario: User) -> dict:
    """Consola de agente: el cliente vuelve a la sala, donde ya está la
    persona consultada (los tres hablan)."""
    vivo = await _agente_en_llamada(session, usuario)
    if vivo is None or not vivo.consulta_uuid:
        raise ErrorTransferencia("No hay una consulta en curso")
    await _volver_a_la_sala(vivo)
    vivo.en_espera = False
    agentes._publicar(vivo)
    await session.commit()
    return {"estado": "conferencia"}


# --- A quién se puede transferir ---------------------------------------------------------------


async def destinos(session, usuario: User) -> dict:
    """Extensiones y grupos de la empresa, para elegir sin saberse los números."""
    propia = usuario.extension.number if usuario.extension else None
    extensiones = (
        await session.execute(
            select(Extension.number, Extension.caller_id_name, Extension.voicemail)
            .where(Extension.enabled)
            .order_by(Extension.number)
        )
    ).all()
    colas = (
        await session.execute(select(Queue.extension, Queue.name).where(Queue.enabled).order_by(Queue.extension))
    ).all()
    return {
        "extensiones": [
            {"numero": n, "nombre": nombre, "buzon": bool(vm)} for n, nombre, vm in extensiones if n != propia
        ],
        "grupos": [{"numero": n, "nombre": nombre} for n, nombre in colas],
    }
