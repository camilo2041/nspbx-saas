"""Despertar la app móvil cuando entra una llamada a un grupo de atención.

Las llamadas a una extensión pasan por el dialplan, que avisa al backend
antes de timbrar (config_generator._append_mobile_push_hook). Las de un
grupo NO: mod_callcenter llama a cada agente directo, sin dialplan, así que
quien atendía solo con la app y el teléfono bloqueado nunca se enteraba.

mod_callcenter publica `CUSTOM callcenter::info` con `CC-Action:
member-queue-start` cuando alguien entra a la fila. Con eso se manda el push
a los teléfonos de quienes atienden ese grupo; la app se registra en unos
segundos y mod_callcenter, que vuelve a intentar con los agentes mientras el
cliente espera, ya la encuentra conectada.
"""

import logging

from sqlalchemy import select

from app.core import validacion
from app.core.database import async_session, sesion_de_empresa
from app.models import DeviceToken, Extension, Queue, SystemSettings, Tenant
from app.services import push
from app.services.queues_sync import parse_agents

logger = logging.getLogger(__name__)

SUBCLASE = "callcenter::info"


async def _empresa_de_dominio(dominio: str) -> Tenant | None:
    async with async_session() as session:
        empresa = (await session.execute(select(Tenant).where(Tenant.sip_domain == dominio))).scalar_one_or_none()
        if empresa is not None:
            return empresa
        ajuste = (
            await session.execute(select(SystemSettings).where(SystemSettings.fs_domain == dominio).limit(1))
        ).scalar_one_or_none()
        return await session.get(Tenant, ajuste.tenant_id) if ajuste is not None else None


async def recibir(ev: dict[str, str]) -> int:
    """Devuelve a cuántos teléfonos se avisó (para las pruebas y el log)."""
    if ev.get("Event-Name") != "CUSTOM" or ev.get("Event-Subclass") != SUBCLASE:
        return 0
    if ev.get("CC-Action") != "member-queue-start":
        return 0
    nombre_cola, _, dominio = (ev.get("CC-Queue") or "").partition("@")
    if not validacion.NOMBRE_RE.fullmatch(nombre_cola) or not validacion.HOST_RE.fullmatch(dominio):
        return 0
    empresa = await _empresa_de_dominio(dominio)
    if empresa is None:
        return 0
    llamada = ev.get("CC-Member-Session-UUID") or ev.get("Unique-ID") or ""
    numero = ev.get("CC-Member-CID-Number") or ""
    nombre = ev.get("CC-Member-CID-Name") or ""
    enviados = 0
    async with sesion_de_empresa(empresa.id) as session:
        cola = (await session.execute(select(Queue).where(Queue.name == nombre_cola))).scalar_one_or_none()
        if cola is None or not cola.enabled:
            return 0
        agentes = [e for e in parse_agents(cola.agents) if validacion.EXTENSION_RE.fullmatch(e)]
        con_app = set(
            (
                await session.execute(
                    select(Extension.number)
                    .join(DeviceToken, DeviceToken.extension_id == Extension.id)
                    .where(Extension.number.in_(agentes))
                )
            ).scalars()
        )
        for ext in agentes:
            if ext in con_app:
                enviados += await push.avisar_llamada(session, empresa.id, empresa.slug, ext, llamada, numero, nombre)
    if enviados:
        logger.info("Grupo %s: aviso a %d teléfono(s) con la app", nombre_cola, enviados)
    return enviados
