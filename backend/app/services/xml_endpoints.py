import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Guardia compartido con /fs/cdr (app/api/calls.py) — ver el porqué en su
# docstring; antes vivía acá y ese otro endpoint quedó sin protección.
from app.core.auth import verificar_secreto_fs as _verificar_secreto
from app.core.database import get_admin_session
from app.models import Extension, InboundRoute, Queue, SystemSettings, Tenant, Trunk, VoiceBot
from app.services.ajustes import dominios_tenants
from app.services.config_generator import build_dialplan_xml, build_directory_xml

logger = logging.getLogger(__name__)

router = APIRouter(tags=["freeswitch-xml"])


def _tenantes(
    session: AsyncSession,
    tenantes_rows: list[Tenant],
    ajustes_por_tenant: dict[int, SystemSettings],
    extensiones_por_tenant: dict[int, list],
    bots_por_tenant: dict[int, list],
    troncales_por_tenant: dict[int, list],
    colas_por_tenant: dict[int, list],
) -> list[dict]:
    """Los bloques por empresa que consumen los generadores XML.

    El dominio sale de Ajustes (fs_domain, que se siembra desde
    Tenant.sip_domain) con respaldo en el propio Tenant.sip_domain, y el
    contexto es `ctx_<slug>` — la unidad de multiempresa de FreeSWITCH
    (ver docs/arquitectura-multitenant.md).
    """
    out = []
    for t in tenantes_rows:
        ajustes = ajustes_por_tenant.get(t.id)
        out.append(
            {
                "tenant_id": t.id,
                "dominio": (ajustes.fs_domain if ajustes and ajustes.fs_domain else None) or t.sip_domain,
                "contexto": t.dialplan_context,
                "extensions": extensiones_por_tenant.get(t.id, []),
                "bots": bots_por_tenant.get(t.id, []),
                "trunks": troncales_por_tenant.get(t.id, []),
                "queues": colas_por_tenant.get(t.id, []),
                "record_all": bool(ajustes.record_all_calls) if ajustes else False,
                "max_call_minutes": ajustes.max_call_duration_minutes if ajustes else 60,
            }
        )
    return out


@router.get("/fs/directory", dependencies=[Depends(_verificar_secreto)])
async def fs_directory(session: AsyncSession = Depends(get_admin_session)):
    """Directorio de extensiones. Lo pide FreeSWITCH server-to-server (sin
    sesión de usuario), así que usa la sesión del DUEÑO: tiene que ver la
    config de TODAS las empresas para poder registrarlas. Cada empresa se
    sirve en su propio <domain>, que es como FreeSWITCH decide de quién es
    cada teléfono."""
    extensions = (await session.execute(select(Extension).where(Extension.enabled.is_(True)))).scalars().all()
    tenantes_rows = (await session.execute(select(Tenant))).scalars().all()
    ajustes_rows = (await session.execute(select(SystemSettings))).scalars().all()
    ajustes_por_tenant = {r.tenant_id: r for r in ajustes_rows}
    por_tenant: dict[int, list] = {}
    for ext in extensions:
        por_tenant.setdefault(ext.tenant_id, []).append(ext)
    tenantes = _tenantes(session, tenantes_rows, ajustes_por_tenant, por_tenant, {}, {}, {})
    xml = build_directory_xml(tenantes)
    return Response(content=xml, media_type="text/xml")


@router.get("/fs/dialplan", dependencies=[Depends(_verificar_secreto)])
async def fs_dialplan(session: AsyncSession = Depends(get_admin_session)):
    """Dialplan completo: un contexto por empresa (`ctx_<slug>`) + el
    contexto `public` de entrantes. Misma razón que el directorio para la
    sesión del dueño: FreeSWITCH necesita la config de todas las empresas
    para enrutar entre ellas."""
    extensions = (await session.execute(select(Extension).where(Extension.enabled.is_(True)))).scalars().all()
    bots = (await session.execute(select(VoiceBot).where(VoiceBot.enabled.is_(True)))).scalars().all()
    trunks = (await session.execute(select(Trunk).where(Trunk.enabled.is_(True)).order_by(Trunk.id))).scalars().all()
    queues = (await session.execute(select(Queue).where(Queue.enabled.is_(True)))).scalars().all()
    inbound_routes = (await session.execute(select(InboundRoute).where(InboundRoute.enabled.is_(True)))).scalars().all()
    tenantes_rows = (await session.execute(select(Tenant))).scalars().all()
    ajustes_rows = (await session.execute(select(SystemSettings))).scalars().all()
    ajustes_por_tenant = {r.tenant_id: r for r in ajustes_rows}
    dominios = await dominios_tenants(session)
    contextos = {t.id: t.dialplan_context for t in tenantes_rows}
    slugs = {t.id: t.slug for t in tenantes_rows}

    def _agrupar(filas):
        d: dict[int, list] = {}
        for f in filas:
            d.setdefault(f.tenant_id, []).append(f)
        return d

    tenantes = _tenantes(
        session,
        tenantes_rows,
        ajustes_por_tenant,
        _agrupar(extensions),
        _agrupar(bots),
        _agrupar(trunks),
        _agrupar(queues),
    )
    xml = build_dialplan_xml(tenantes, inbound_routes, contextos, dominios, slugs)
    return Response(content=xml, media_type="text/xml")
