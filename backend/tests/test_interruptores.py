"""Controles de emergencia y cupo diario: cortar salientes tiene que ser
inmediato, en los tres caminos de salida, y quien no corresponde no puede
deshacerlo."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.api.calls import _salio_por_troncal
from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import CallLog, Extension, License, PlatformState, SystemSettings, Tenant, Trunk, User
from app.services import salientes
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


@pytest.fixture(scope="module")
async def epsilon(mundo):
    async with async_session() as s:
        t = Tenant(name="Epsilon", slug="epsilon", sip_domain="epsilon.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        await get_or_create_settings(s, t.id)
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.epsilon.test", register_enabled=False)
        ext = Extension(tenant_id=t.id, number="1000", password="clave-sip-epsilon-larga")
        admin = User(
            tenant_id=t.id, username="admin-epsilon", full_name="admin epsilon",
            password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True,
        )
        s.add_all([troncal, ext, admin])
        await s.commit()
        token = crear_token(admin.id, permissions.ADMIN, t.id)[0]
        return {
            "tenant": t.id, "ext": ext.id, "trunk": troncal.id,
            "cab": {"Authorization": f"Bearer {token}"},
        }


async def _puede_salir_por_dialplan(cliente, slug: str = "epsilon") -> bool:
    resp = await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})
    ctx = ET.fromstring(resp.text).find(f".//context[@name='ctx_{slug}']")
    return any((a.get("data") or "").startswith("sofia/gateway/") for a in ctx.iter("action"))


async def _clic_para_llamar(cliente, e) -> int:
    resp = await cliente.post(
        f"/api/extensions/{e['ext']}/call", headers=e["cab"],
        json={"destination": "3001234567", "trunk_id": e["trunk"]},
    )
    # 502 = llegó a FreeSWITCH (no existe en las pruebas): la política lo dejó pasar.
    return resp.status_code


async def _estado(cliente, e) -> dict:
    resp = await cliente.get("/api/system/salientes", headers=e["cab"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_sin_interruptores_las_salientes_funcionan(cliente, epsilon):
    assert await _puede_salir_por_dialplan(cliente)
    assert await _clic_para_llamar(cliente, epsilon) == 502
    assert (await _estado(cliente, epsilon))["bloqueo"] is None


async def test_la_empresa_puede_pausar_y_reanudar_sus_salientes(cliente, epsilon):
    resp = await cliente.put("/api/system/settings", headers=epsilon["cab"], json={"outbound_paused": True})
    assert resp.status_code == 200
    try:
        assert not await _puede_salir_por_dialplan(cliente)
        assert await _clic_para_llamar(cliente, epsilon) == 403
        assert (await _estado(cliente, epsilon))["bloqueo"] == salientes.MOTIVO_EMPRESA
    finally:
        await cliente.put("/api/system/settings", headers=epsilon["cab"], json={"outbound_paused": False})
    assert await _puede_salir_por_dialplan(cliente)


async def test_dialplan_cortado_rechaza_con_motivo(cliente, epsilon):
    """No alcanza con quitar la ruta: sin ella la llamada cae en "sin ruta"
    y nadie sabe por qué. Se rechaza explícitamente y queda en el log."""
    await cliente.put("/api/system/settings", headers=epsilon["cab"], json={"outbound_paused": True})
    try:
        resp = await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})
        ctx = ET.fromstring(resp.text).find(".//context[@name='ctx_epsilon']")
        bloqueada = ctx.find("extension[@name='Outbound_Bloqueadas']")
        acciones = [(a.get("application"), a.get("data")) for a in bloqueada.iter("action")]
        assert ("hangup", "CALL_REJECTED") in acciones
        assert any(app == "log" and "pausadas" in data for app, data in acciones)
    finally:
        await cliente.put("/api/system/settings", headers=epsilon["cab"], json={"outbound_paused": False})


async def test_el_corte_de_la_plataforma_no_lo_deshace_la_empresa(cliente, mundo, epsilon):
    plataforma = mundo.cabeceras_plataforma()
    resp = await cliente.put(f"/api/tenants/{epsilon['tenant']}", headers=plataforma, json={"outbound_blocked": True})
    assert resp.status_code == 200 and resp.json()["outbound_blocked"] is True
    try:
        assert not await _puede_salir_por_dialplan(cliente)
        assert await _clic_para_llamar(cliente, epsilon) == 403
        assert (await _estado(cliente, epsilon))["bloqueo"] == salientes.MOTIVO_PLATAFORMA
        # La empresa intenta deshacerlo por las dos vías que tiene a mano.
        await cliente.put("/api/system/settings", headers=epsilon["cab"], json={"outbound_paused": False})
        resp = await cliente.put(f"/api/tenants/{epsilon['tenant']}", headers=epsilon["cab"], json={"outbound_blocked": False})
        assert resp.status_code == 403
        assert not await _puede_salir_por_dialplan(cliente)
    finally:
        await cliente.put(f"/api/tenants/{epsilon['tenant']}", headers=plataforma, json={"outbound_blocked": False})
    assert await _puede_salir_por_dialplan(cliente)


async def test_interruptor_global_corta_a_todas_las_empresas(cliente, mundo, epsilon):
    plataforma = mundo.cabeceras_plataforma()
    assert (await cliente.put("/api/plataforma/salientes", headers=mundo.alfa.cabeceras(), json={"outbound_blocked": True})).status_code == 403
    resp = await cliente.put("/api/plataforma/salientes", headers=plataforma, json={"outbound_blocked": True})
    assert resp.status_code == 200
    try:
        for slug in ("alfa", "beta", "epsilon"):
            assert not await _puede_salir_por_dialplan(cliente, slug), slug
        assert await _clic_para_llamar(cliente, epsilon) == 403
        assert (await cliente.get("/api/plataforma/salientes", headers=plataforma)).json() == {"outbound_blocked": True}
    finally:
        await cliente.put("/api/plataforma/salientes", headers=plataforma, json={"outbound_blocked": False})
    assert await _puede_salir_por_dialplan(cliente, "alfa")


async def _cdr(tenant_id: int, segundos: int, via_trunk, cuando: datetime | None = None, uuid: str = ""):
    async with async_session() as s:
        s.add(
            CallLog(
                tenant_id=tenant_id, uuid=uuid, direction="outbound", status="answered",
                billsec=segundos, via_trunk=via_trunk, started_at=cuando or datetime.utcnow(),
            )
        )
        await s.commit()


async def test_cupo_diario_agotado_corta_las_salientes(cliente, mundo, epsilon):
    plataforma = mundo.cabeceras_plataforma()
    resp = await cliente.put(
        f"/api/tenants/{epsilon['tenant']}/licencia", headers=plataforma, json={"max_outbound_minutes_day": 2}
    )
    assert resp.status_code == 200 and resp.json()["max_outbound_minutes_day"] == 2
    try:
        # No cuentan: llamadas internas, ni las de ayer.
        await _cdr(epsilon["tenant"], 600, False, uuid="cupo-interna")
        await _cdr(epsilon["tenant"], 600, True, datetime.utcnow() - timedelta(days=2), uuid="cupo-vieja")
        assert await _puede_salir_por_dialplan(cliente)
        # 1 minuto: todavía hay cupo.
        await _cdr(epsilon["tenant"], 60, True, uuid="cupo-1")
        assert await _puede_salir_por_dialplan(cliente)
        estado = await _estado(cliente, epsilon)
        assert estado["minutos_hoy"] == 1.0 and estado["cupo_diario"] == 2
        # 2 minutos: agotado.
        await _cdr(epsilon["tenant"], 60, True, uuid="cupo-2")
        assert not await _puede_salir_por_dialplan(cliente)
        assert await _clic_para_llamar(cliente, epsilon) == 403
        assert "Cupo diario" in (await _estado(cliente, epsilon))["bloqueo"]
    finally:
        async with async_session() as s:
            await s.execute(delete(CallLog).where(CallLog.uuid.like("cupo-%")))
            await s.commit()
        await cliente.put(
            f"/api/tenants/{epsilon['tenant']}/licencia", headers=plataforma, json={"max_outbound_minutes_day": None}
        )


async def test_cupo_por_plan():
    from app.services import licensing

    assert licensing.limite(License(plan="trial"), "max_outbound_minutes_day") == 60
    assert licensing.limite(License(plan="pro"), "max_outbound_minutes_day") == 5000
    assert licensing.limite(License(plan="enterprise"), "max_outbound_minutes_day") is None
    assert licensing.limite(License(plan="pro", max_outbound_minutes_day=10), "max_outbound_minutes_day") == 10


@pytest.mark.parametrize(
    "variables,esperado",
    [
        ({"direction": "outbound", "channel_name": "sofia/external/3001234567"}, True),
        ({"direction": "outbound", "channel_name": "sofia/internal/1001@x", "sip_gateway_name": "alfa_principal"}, True),
        ({"direction": "outbound", "channel_name": "sofia/internal/1001@alfa.pbx.test"}, False),
        ({"direction": "inbound", "channel_name": "sofia/external/3001234567"}, False),
        ({}, False),
    ],
)
def test_cdr_identifica_la_pata_de_troncal(variables, esperado):
    assert _salio_por_troncal(variables) is esperado
