"""Colgar las salientes EN CURSO (services/emergencia.py).

FreeSWITCH no existe en las pruebas: se capturan los comandos que se le
mandarían. Que `hupall <causa> <variable> <valor>` cuelgue solo los
canales marcados se probó contra un FreeSWITCH 1.10.12 real (ver
docs/seguridad-y-robustez.md, §5.15); acá se prueba que cada camino de
salida lleve la marca correcta y que cada quien cuelgue solo lo suyo.
"""

import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import select, text

from app.core import permissions
from app.core.database import async_session, engine
from app.core.security import crear_token, hash_password
from app.models import Campaign, CampaignNumber, Extension, License, OutboundRoute, Tenant, Trunk, User
from app.services import esl
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


@pytest.fixture
def fs(monkeypatch):
    """Comandos que recibiría FreeSWITCH."""
    enviados: list[str] = []

    async def api(cmd):
        enviados.append(cmd)
        return "+OK"

    async def bgapi(cmd):
        enviados.append(cmd)
        return "+OK Job-UUID: x"

    monkeypatch.setattr(esl, "api", api)
    monkeypatch.setattr(esl, "bgapi", bgapi)
    return enviados


@pytest.fixture
def fs_caido(monkeypatch):
    async def caido(cmd):
        raise ConnectionRefusedError("FreeSWITCH no responde")

    monkeypatch.setattr(esl, "api", caido)


@pytest.fixture(scope="module")
async def eco(mundo):
    """Empresa con troncal y regla de salida, para los tres caminos."""
    async with async_session() as s:
        t = Tenant(name="Eco", slug="eco", sip_domain="eco.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        await get_or_create_settings(s, t.id)
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.eco.test", register_enabled=False)
        ext = Extension(tenant_id=t.id, number="1000", password="clave-sip-eco-larga-1")
        s.add_all([troncal, ext])
        await s.flush()
        s.add(OutboundRoute(tenant_id=t.id, name="todo", pattern="3XXXXXXXXX", trunk_ids=str(troncal.id)))
        camp = Campaign(tenant_id=t.id, name="avisos", trunk_id=troncal.id)
        admin = User(
            tenant_id=t.id, username="admin-eco", full_name="admin eco",
            password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True,
        )
        s.add_all([camp, admin])
        await s.commit()
        return {
            "tenant": t.id, "ext": ext.id, "trunk": troncal.id, "campaign": camp.id,
            "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"},
        }


# --- Las marcas en los tres caminos de salida --------------------------------


async def test_dialplan_marca_las_salientes(cliente, eco):
    raiz = ET.fromstring((await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})).text)
    ctx = raiz.find(".//context[@name='ctx_eco']")
    salidas = [e for e in ctx.findall("extension")
               if any((a.get("data") or "").startswith("sofia/gateway/") for a in e.iter("action"))]
    assert salidas
    for e in salidas:
        acciones = [(a.get("application"), a.get("data")) for a in e.iter("action")]
        sets = [d for app, d in acciones if app == "set"]
        assert f"nspbx_saliente={eco['tenant']}" in sets
        assert "nspbx_saliente_ext=${user_name}@${domain_name}" in sets
        # La marca va ANTES del bridge: si no, la llamada ya está hablando sin ella.
        indice_bridge = [app for app, _ in acciones].index("bridge")
        assert acciones.index(("set", f"nspbx_saliente={eco['tenant']}")) < indice_bridge


async def test_clic_para_llamar_por_troncal_lleva_la_marca(cliente, eco, fs):
    resp = await cliente.post(f"/api/extensions/{eco['ext']}/call",
                              json={"destination": "3001234567", "trunk_id": eco["trunk"]}, headers=eco["cab"])
    assert resp.status_code == 200, resp.text
    (cmd,) = [c for c in fs if c.startswith("originate")]
    assert f"nspbx_saliente={eco['tenant']}" in cmd and "nspbx_saliente_ext=1000@eco.pbx.test" in cmd


async def test_clic_para_llamar_interno_no_lleva_la_marca(cliente, eco, fs):
    async with async_session() as s:
        s.add(Extension(tenant_id=eco["tenant"], number="1001", password="clave-sip-eco-larga-2"))
        await s.commit()
    resp = await cliente.post(f"/api/extensions/{eco['ext']}/call", json={"destination": "1001"}, headers=eco["cab"])
    assert resp.status_code == 200, resp.text
    (cmd,) = [c for c in fs if c.startswith("originate")]
    assert "nspbx_saliente" not in cmd


async def test_el_marcador_de_campanas_lleva_la_marca(eco, monkeypatch):
    from app.workers.dialer import CampaignDialer

    vistos = {}

    async def originate(**kwargs):
        vistos.update(kwargs)
        return "+OK"

    monkeypatch.setattr(esl, "originate", originate)
    async with async_session() as s:
        numero = CampaignNumber(tenant_id=eco["tenant"], campaign_id=eco["campaign"], phone="3001234567")
        s.add(numero)
        await s.commit()
        camp = await s.get(Campaign, eco["campaign"])
        await CampaignDialer()._dial(s, camp, numero)
    assert vistos["extra_vars"]["nspbx_saliente"] == str(eco["tenant"])


# --- Colgar: cada quien lo suyo -----------------------------------------------


def _colgadas(enviados):
    return sorted(int(c.split()[-1]) for c in enviados if c.startswith("hupall MANAGER_REQUEST nspbx_saliente "))


async def test_la_empresa_cuelga_solo_las_suyas(mundo, cliente, fs):
    resp = await cliente.post("/api/system/salientes/colgar", json={"tenant_id": mundo.beta.id},
                              headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, resp.text
    assert _colgadas(fs) == [mundo.alfa.id]


async def test_solo_el_administrador(mundo, cliente, fs):
    for rol in (permissions.SUPERVISOR, permissions.ASESOR):
        resp = await cliente.post("/api/system/salientes/colgar", headers=mundo.alfa.cabeceras(rol))
        assert resp.status_code == 403, rol
    assert fs == []


async def test_la_plataforma_cuelga_todas_o_una(mundo, cliente, fs):
    resp = await cliente.post("/api/plataforma/salientes/colgar", headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 200, resp.text
    async with async_session() as s:
        todas = sorted((await s.execute(select(Tenant.id))).scalars().all())
    assert _colgadas(fs) == todas

    fs.clear()
    resp = await cliente.post(f"/api/tenants/{mundo.beta.id}/salientes/colgar", headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 200
    assert _colgadas(fs) == [mundo.beta.id]
    assert (await cliente.post("/api/tenants/999999/salientes/colgar",
                               headers=mundo.cabeceras_plataforma())).status_code == 404


async def test_una_empresa_no_usa_los_de_la_plataforma(mundo, cliente, fs):
    assert (await cliente.post("/api/plataforma/salientes/colgar", headers=mundo.alfa.cabeceras())).status_code == 403
    assert (await cliente.post(f"/api/tenants/{mundo.beta.id}/salientes/colgar",
                               headers=mundo.alfa.cabeceras())).status_code == 403
    assert fs == []


async def test_si_freeswitch_no_responde_se_dice(mundo, cliente, fs_caido):
    """Un "listo" falso en plena emergencia es peor que un error."""
    resp = await cliente.post("/api/system/salientes/colgar", headers=mundo.alfa.cabeceras())
    assert resp.status_code == 502 and "no se pudo colgar" in resp.text


# --- Extensión comprometida -------------------------------------------------


@pytest.fixture
async def extension_temporal(eco):
    async with async_session() as s:
        ext = Extension(tenant_id=eco["tenant"], number="1050", password="clave-sip-eco-larga-3", enabled=True)
        s.add(ext)
        await s.commit()
        yield ext.id
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM extensions WHERE id = :i"), {"i": ext.id})


def _cortes(enviados):
    return [c for c in enviados if "1050@eco.pbx.test" in c]


@pytest.mark.parametrize("cambio", [{"enabled": False}, {"password": "Otra-Clave-Larga-987"}])
async def test_desactivar_o_cambiar_clave_saca_al_que_la_usa(eco, cliente, fs, extension_temporal, cambio):
    resp = await cliente.put(f"/api/extensions/{extension_temporal}", json=cambio, headers=eco["cab"])
    assert resp.status_code == 200, resp.text
    assert _cortes(fs) == [
        "hupall MANAGER_REQUEST nspbx_saliente_ext 1050@eco.pbx.test",
        "sofia profile internal flush_inbound_reg 1050@eco.pbx.test",
    ]


async def test_otros_cambios_no_cortan(eco, cliente, fs, extension_temporal):
    resp = await cliente.put(f"/api/extensions/{extension_temporal}", json={"voicemail": True}, headers=eco["cab"])
    assert resp.status_code == 200
    assert fs == []


async def test_borrar_saca_al_que_la_usa(eco, cliente, fs, extension_temporal):
    resp = await cliente.delete(f"/api/extensions/{extension_temporal}", headers=eco["cab"])
    assert resp.status_code == 204
    assert len(_cortes(fs)) == 2


async def test_si_freeswitch_no_responde_la_extension_igual_queda_desactivada(eco, cliente, fs_caido, extension_temporal):
    resp = await cliente.put(f"/api/extensions/{extension_temporal}", json={"enabled": False}, headers=eco["cab"])
    assert resp.status_code == 200
    async with async_session() as s:
        assert (await s.get(Extension, extension_temporal)).enabled is False


async def test_otra_empresa_no_corta_mis_extensiones(mundo, cliente, fs, eco, extension_temporal):
    resp = await cliente.put(f"/api/extensions/{extension_temporal}", json={"enabled": False},
                             headers=mundo.alfa.cabeceras())
    assert resp.status_code == 404
    assert fs == []
