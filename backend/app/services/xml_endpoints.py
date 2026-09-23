import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Guardia compartido con /fs/cdr (app/api/calls.py) — ver el porqué en su
# docstring; antes vivía acá y ese otro endpoint quedó sin protección.
from app.core.auth import verificar_secreto_fs as _verificar_secreto
from app.core.database import get_admin_session
from app.models import DeviceToken, Extension, InboundRoute, OutboundRoute, Queue, SystemSettings, Tenant, Trunk, VoiceBot
from app.services import webcall
from app.services.ajustes import dominios_tenants
from app.services.config_generator import build_dialplan_xml, build_directory_xml, build_guest_directory_xml

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
    push_por_tenant: dict[int, set] | None = None,
    salientes_por_tenant: dict[int, list] | None = None,
) -> list[dict]:
    """Los bloques por empresa que consumen los generadores XML.

    El dominio sale de Ajustes (fs_domain, que se siembra desde
    Tenant.sip_domain) con respaldo en el propio Tenant.sip_domain, y el
    contexto es `ctx_<slug>` — la unidad de multiempresa de FreeSWITCH
    (ver docs/arquitectura-multitenant.md).
    """
    push_por_tenant = push_por_tenant or {}
    salientes_por_tenant = salientes_por_tenant or {}
    out = []
    for t in tenantes_rows:
        ajustes = ajustes_por_tenant.get(t.id)
        colas = colas_por_tenant.get(t.id, [])
        # Widget de llamada web (ver app/api/webcall.py): por ahora solo
        # tenant_id=1 lo usa, pero se resuelve genéricamente por si algún
        # día se activa en otra empresa — no hay nada especial de tenant_id
        # 1 en esta cuenta, solo que es la única fila con webcall_enabled.
        webcall_queue = None
        if ajustes and ajustes.webcall_enabled and ajustes.webcall_queue_id:
            webcall_queue = next((q for q in colas if q.id == ajustes.webcall_queue_id), None)
        out.append(
            {
                "tenant_id": t.id,
                "slug": t.slug,
                "dominio": (ajustes.fs_domain if ajustes and ajustes.fs_domain else None) or t.sip_domain,
                "contexto": t.dialplan_context,
                "extensions": extensiones_por_tenant.get(t.id, []),
                "bots": bots_por_tenant.get(t.id, []),
                "trunks": troncales_por_tenant.get(t.id, []),
                "queues": colas,
                "record_all": bool(ajustes.record_all_calls) if ajustes else False,
                "max_call_minutes": ajustes.max_call_duration_minutes if ajustes else 60,
                "allow_international": bool(ajustes.allow_international) if ajustes else False,
                "max_concurrent": ajustes.max_concurrent_calls if ajustes else 20,
                # Números con la app móvil registrada (ver DeviceToken) —
                # solo a esos se les dispara el push de aviso antes de
                # timbrar (ver config_generator._append_mobile_push_hook).
                "push_extensions": push_por_tenant.get(t.id, set()),
                # Reglas de salida por patrón. Vacío = ruta única de
                # siempre (ver config_generator._append_outbound_route).
                "outbound_routes": salientes_por_tenant.get(t.id, []),
                "webcall_queue": webcall_queue,
            }
        )
    return out


@router.get("/fs/directory", dependencies=[Depends(_verificar_secreto)])
async def fs_directory(request: Request, session: AsyncSession = Depends(get_admin_session)):
    """Directorio de extensiones. Lo pide FreeSWITCH server-to-server (sin
    sesión de usuario), así que usa la sesión del DUEÑO: tiene que ver la
    config de TODAS las empresas para poder registrarlas. Cada empresa se
    sirve en su propio <domain>, que es como FreeSWITCH decide de quién es
    cada teléfono."""
    # Credencial temporal del widget de llamada web (ver app/api/webcall.py
    # y app/services/webcall.py): FreeSWITCH pide el usuario concreto en
    # cada REGISTER/INVITE. Si matchea el patrón de invitado y sigue
    # vigente en el registro en memoria, se le arma un directorio a medida
    # con user_context=webcall_<slug> (aislado). Si no existe/venció, 404
    # = "usuario desconocido" para mod_xml_curl.
    #
    # El widget está fijo a tenant_id=1 por ahora (ver docstring de
    # app/api/webcall.py); el dominio del invitado sale de
    # Tenant.sip_domain de esa empresa, no de un ajuste global.
    pedido = request.query_params.get("user") or request.query_params.get("sip_auth_username")
    if pedido and webcall.GUEST_RE.match(pedido):
        guest = await webcall.registry.get(pedido)
        if not guest:
            return Response(status_code=404)
        tenant = await session.get(Tenant, 1)
        if not tenant:
            return Response(status_code=404)
        return Response(
            content=build_guest_directory_xml(
                guest.username, guest.password, tenant.sip_domain, f"webcall_{tenant.slug}"
            ),
            media_type="text/xml",
        )

    extensions = (await session.execute(select(Extension).where(Extension.enabled.is_(True)))).scalars().all()
    # Una empresa desactivada (falta de pago, baja) no debe poder registrar
    # teléfonos ni recibir llamadas: antes seguía sirviéndose completa.
    tenantes_rows = (await session.execute(select(Tenant).where(Tenant.enabled.is_(True)))).scalars().all()
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
    outbound_routes = (
        await session.execute(select(OutboundRoute).where(OutboundRoute.enabled.is_(True)).order_by(OutboundRoute.priority, OutboundRoute.id))
    ).scalars().all()
    # Extensiones con la app móvil registrada, para el hook de push (ver
    # config_generator._append_mobile_push_hook). Se agrupan por empresa
    # con el número en vez del id porque el dialplan matchea por número.
    push_rows = (
        await session.execute(
            select(Extension.tenant_id, Extension.number)
            .join(DeviceToken, DeviceToken.extension_id == Extension.id)
            .distinct()
        )
    ).all()
    push_por_tenant: dict[int, set] = {}
    for tenant_id, numero in push_rows:
        push_por_tenant.setdefault(tenant_id, set()).add(numero)
    tenantes_rows = (await session.execute(select(Tenant).where(Tenant.enabled.is_(True)))).scalars().all()
    ajustes_rows = (await session.execute(select(SystemSettings))).scalars().all()
    ajustes_por_tenant = {r.tenant_id: r for r in ajustes_rows}
    dominios = await dominios_tenants(session)
    contextos = {t.id: t.dialplan_context for t in tenantes_rows}
    # Las rutas de una empresa desactivada no se enrutan (caerían en "default").
    inbound_routes = [r for r in inbound_routes if r.tenant_id in contextos]
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
        push_por_tenant,
        _agrupar(outbound_routes),
    )
    xml = build_dialplan_xml(tenantes, inbound_routes, contextos, dominios, slugs)
    return Response(content=xml, media_type="text/xml")
