"""Verificación en vivo: lo que la prueba de humo (services/humo.py) no
puede hacer sola porque necesita teléfonos y personas.

Cada prueba dice paso a paso qué marcar. Al pulsar «Empezar» se anota la
hora; al pulsar «Comprobar», si la prueba deja rastro en el backend (el
CDR, la auditoría, un mensaje o una devolución), se busca desde esa hora y
se da por buena sola con la evidencia. Las que no dejan rastro (oír
música, que suene el celular) las confirma la persona con «Pasó» o «Falló».
Los resultados quedan guardados con fecha y quién los hizo.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AuditLog, CallLog, Devolucion, MensajeBuzon


@dataclass
class Prueba:
    clave: str
    titulo: str
    fase: str
    pasos: list[str]
    # Busca el rastro desde `desde`; devuelve la evidencia o None.
    detector: Callable[[AsyncSession, int, datetime], Awaitable[str | None]] | None = field(default=None, repr=False)


async def _llamada(session, tenant_id: int, desde: datetime, *condiciones, que: str) -> str | None:
    fila = (
        await session.execute(
            select(CallLog)
            .where(CallLog.tenant_id == tenant_id, CallLog.started_at >= desde, *condiciones)
            .order_by(CallLog.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if fila is None:
        return None
    return f"{que}: {fila.caller_number or '?'} → {fila.callee_number or '?'}, {fila.billsec} s ({fila.started_at:%H:%M:%S} UTC)"


def _marcado(codigo: str):
    async def detector(session, tenant_id, desde):
        return await _llamada(session, tenant_id, desde, CallLog.callee_number == codigo, CallLog.status == "answered",
                              que=f"Llamada a {codigo}")
    return detector


def _auditado(accion: str, que: str):
    async def detector(session, tenant_id, desde):
        fila = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.tenant_id == tenant_id, AuditLog.created_at >= desde, AuditLog.action == accion,
                       AuditLog.result == "ok")
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return f"{que} por {fila.actor or '?'} ({fila.created_at:%H:%M:%S} UTC)" if fila else None
    return detector


async def _entrante(session, tenant_id, desde):
    return await _llamada(session, tenant_id, desde, CallLog.direction == "inbound", CallLog.via_trunk.is_(True),
                          CallLog.status == "answered", que="Entrante contestada")


async def _saliente(session, tenant_id, desde):
    return await _llamada(session, tenant_id, desde, CallLog.direction == "outbound", CallLog.via_trunk.is_(True),
                          CallLog.status == "answered", que="Saliente contestada")


async def _grabacion(session, tenant_id, desde):
    return await _llamada(session, tenant_id, desde, CallLog.recording_path.is_not(None), CallLog.status == "answered",
                          que="Llamada grabada")


async def _predictiva(session, tenant_id, desde):
    return await _llamada(session, tenant_id, desde, CallLog.campaign_id.is_not(None), CallLog.agente_id.is_not(None),
                          CallLog.status == "answered", que="Campaña pasada a un agente")


async def _cola(session, tenant_id, desde):
    return await _llamada(session, tenant_id, desde, CallLog.cola.is_not(None), CallLog.status == "answered",
                          que="Entró por un grupo y la atendieron")


async def _dejar_mensaje(session, tenant_id, desde):
    fila = (
        await session.execute(
            select(MensajeBuzon)
            .where(MensajeBuzon.tenant_id == tenant_id, MensajeBuzon.created_at >= desde,
                   ~MensajeBuzon.caller_number.startswith("9990"))
            .order_by(MensajeBuzon.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return f"Mensaje de {fila.caller_number or '?'} en la {fila.extension}, {fila.duracion} s" if fila else None


async def _saludo(session, tenant_id, desde):
    carpeta = Path(settings.recordings_dir) / f"t{int(tenant_id)}" / "buzon"
    if not carpeta.is_dir():
        return None
    for archivo in carpeta.glob("*/saludo.wav"):
        try:
            if datetime.utcfromtimestamp(archivo.stat().st_mtime) >= desde:
                return f"Saludo nuevo de la {archivo.parent.name}"
        except OSError:
            continue
    return None


async def _devolucion(session, tenant_id, desde):
    fila = (
        await session.execute(
            select(Devolucion)
            .where(Devolucion.tenant_id == tenant_id, Devolucion.pedida_at >= desde,
                   and_(Devolucion.estado == "hecha"))
            .order_by(Devolucion.pedida_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return f"Devolución a {fila.numero} hecha ({fila.hecha_at:%H:%M:%S} UTC)" if fila and fila.hecha_at else None


PRUEBAS: list[Prueba] = [
    Prueba("saliente", "Llamar a un celular por el proveedor", "Básico", [
        "Desde una extensión o la app, llama a tu celular.",
        "Contesta y habla unos segundos; cuelga.",
    ], _saliente),
    Prueba("entrante", "Recibir una llamada en tu número", "Básico", [
        "Desde un celular, llama al número de la empresa.",
        "Que conteste quien corresponde según la ruta entrante.",
    ], _entrante),
    Prueba("grabacion", "La llamada queda grabada", "Básico", [
        "Con la grabación activa (Ajustes), haz una llamada de al menos 10 segundos.",
        "Ábrela en Llamadas y escucha la grabación.",
    ], _grabacion),
    Prueba("grupo", "Llamada a un grupo de atención", "Fase A", [
        "Ten al menos un agente conectado en el grupo.",
        "Llama al número que va al grupo y espera: debe sonar la música y decir tu posición.",
        "Que el agente conteste.",
    ], _cola),
    Prueba("musica_posicion", "Música y posición en la fila", "Fase A", [
        "Con todos los agentes ocupados o en pausa, llama al grupo.",
        "Debes oír música y «hay N personas antes que tú». Confirma a mano.",
    ]),
    Prueba("dejar_mensaje", "Dejar un mensaje de voz", "Fase A", [
        "Llama a una extensión con buzón y no contestes.",
        "Deja un mensaje después del tono y cuelga.",
    ], _dejar_mensaje),
    Prueba("transferencia_directa", "Transferencia directa", "Fase B", [
        "En una llamada desde el softphone del panel, pulsa Transferir y elige otra extensión.",
        "La otra extensión debe sonar y quedar con el cliente.",
    ], _auditado("POST /api/llamada/transferir", "Transferencia")),
    Prueba("transferencia_consultada", "Transferencia consultada", "Fase B", [
        "En una llamada, elige Transferir › Consultar primero.",
        "Habla con la otra extensión y pulsa Completar: el cliente queda con ella.",
    ], _auditado("POST /api/llamada/transferencia/completar", "Transferencia consultada completada")),
    Prueba("hablar_tres", "Hablar los tres", "Fase F", [
        "Durante una consulta, pulsa «Hablar los tres».",
        "Los tres deben oírse entre sí.",
    ], _auditado("POST /api/llamada/transferencia/conferencia", "Conferencia de tres")),
    Prueba("espera", "Poner en espera", "Fase B", [
        "En una llamada, pulsa Espera: el cliente debe oír música.",
        "Retoma la llamada.",
    ], _auditado("POST /api/llamada/espera", "Espera")),
    Prueba("aviso_celular", "La app suena con el teléfono bloqueado", "Fase B", [
        "Inicia sesión en la app, bloquea el teléfono.",
        "Llama a esa extensión: debe sonar como una llamada normal. Confirma a mano.",
    ]),
    Prueba("saludo_98", "Grabar el saludo con *98", "Fase G", [
        "Desde una extensión con buzón, marca *98.",
        "Graba el saludo, termina con # y escucha la reproducción.",
    ], _saludo),
    Prueba("escuchar_97", "Escuchar los mensajes con *97", "Fase G", [
        "Desde la extensión que tiene mensajes nuevos, marca *97.",
        "Debe decir cuántos hay y reproducirlos.",
    ], _marcado("*97")),
    Prueba("escuchar_96", "Escuchar el buzón desde otro teléfono (*96)", "Fase H", [
        "Ponle un PIN al buzón (Buzón › Escuchar desde otro teléfono).",
        "Desde OTRA extensión marca *96, la extensión y #, el PIN y #.",
    ], _marcado("*96")),
    Prueba("devolucion", "Devolución de llamada desde la fila", "Fase G", [
        "Con el grupo ocupado, llama y marca 1 cuando lo ofrezca; cuelga.",
        "Cuando un agente quede libre, la central lo llama y luego a ti.",
    ], _devolucion),
    Prueba("ivr_horario", "IVR por horario y festivos", "Fase E/G", [
        "Pon un horario que ya terminó (o una fecha especial hoy) en la ruta o el bloque Horario del IVR.",
        "Llama: debe ir al destino de fuera de horario. Confirma a mano y vuelve a dejarlo como estaba.",
    ]),
    Prueba("predictiva", "Campaña predictiva con agentes", "Campañas", [
        "Carga 2 o 3 números propios en una campaña predictiva y asígnate como agente.",
        "En Trabajar pulsa «Empezar a trabajar» y «Listo»; inicia la campaña.",
        "Contesta en un celular: la llamada debe pasar al agente.",
    ], _predictiva),
]

POR_CLAVE = {p.clave: p for p in PRUEBAS}
ESTADOS = ("en_curso", "ok", "fallo", "omitida")


async def comprobar(session: AsyncSession, clave: str, tenant_id: int, desde: datetime) -> str | None:
    prueba = POR_CLAVE.get(clave)
    if prueba is None or prueba.detector is None:
        return None
    return await prueba.detector(session, tenant_id, desde)
