"""Tope de llamadas salientes por segundo por empresa (freno de fraude).

Que `limit hash cps <empresa> N/1` de FreeSWITCH deje pasar N por segundo y
rechace el resto se probó contra un FreeSWITCH 1.10.12 real (ver
docs/seguridad-y-robustez.md, §5.6). Acá: que el dialplan lo lleve con el
valor de la licencia, y que el clic para llamar aplique el mismo tope.
"""

import asyncio
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import update

from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import Extension, License, OutboundRoute, Tenant, Trunk, User
from app.services import esl, licensing, salientes
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


@pytest.fixture(scope="module")
async def foxtrot(mundo):
    async with async_session() as s:
        t = Tenant(name="Foxtrot", slug="foxtrot", sip_domain="foxtrot.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="pro", status="active"))
        await get_or_create_settings(s, t.id)
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.foxtrot.test", register_enabled=False)
        ext = Extension(tenant_id=t.id, number="1000", password="clave-sip-foxtrot-larga")
        s.add_all([troncal, ext])
        await s.flush()
        s.add(OutboundRoute(tenant_id=t.id, name="todo", pattern="3XXXXXXXXX", trunk_ids=str(troncal.id)))
        admin = User(tenant_id=t.id, username="admin-foxtrot", full_name="admin foxtrot",
                     password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True)
        s.add(admin)
        await s.commit()
        return {"tenant": t.id, "ext": ext.id, "trunk": troncal.id,
                "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"}}


async def _limites_de_salida(cliente, slug: str) -> list[list[str]]:
    raiz = ET.fromstring((await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})).text)
    ctx = raiz.find(f".//context[@name='ctx_{slug}']")
    salidas = []
    for e in ctx.findall("extension"):
        acciones = [(a.get("application"), a.get("data") or "") for a in e.iter("action")]
        if any(d.startswith("sofia/gateway/") for _, d in acciones):
            salidas.append(acciones)
    return salidas


async def test_el_dialplan_lleva_el_tope_del_plan(cliente, foxtrot):
    salidas = await _limites_de_salida(cliente, "foxtrot")
    assert salidas
    for acciones in salidas:
        assert ("limit", f"hash cps foxtrot {licensing.PLANES['pro']['max_outbound_cps']}/1 !CALL_REJECTED") in acciones
        # Antes del bridge: después, la llamada ya salió.
        assert acciones.index(next(a for a in acciones if a[1].startswith("hash cps"))) < \
            [app for app, _ in acciones].index("bridge")


async def test_la_plataforma_cambia_el_tope_de_una_empresa(cliente, mundo, foxtrot):
    plataforma = mundo.cabeceras_plataforma()
    resp = await cliente.put(f"/api/tenants/{foxtrot['tenant']}/licencia", json={"max_outbound_cps": 3}, headers=plataforma)
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_outbound_cps"] == 3
    salidas = await _limites_de_salida(cliente, "foxtrot")
    assert all(("limit", "hash cps foxtrot 3/1 !CALL_REJECTED") in a for a in salidas)
    for malo in (0, -1, 5000):
        r = await cliente.put(f"/api/tenants/{foxtrot['tenant']}/licencia", json={"max_outbound_cps": malo}, headers=plataforma)
        assert r.status_code == 422, malo
    # La empresa no puede subírselo.
    r = await cliente.put(f"/api/tenants/{foxtrot['tenant']}/licencia", json={"max_outbound_cps": 100}, headers=foxtrot["cab"])
    assert r.status_code == 403


async def test_enterprise_tambien_tiene_tope():
    """Es freno de fraude, no límite comercial: ningún plan queda sin tope."""
    for plan, valores in licensing.PLANES.items():
        assert valores.get("max_outbound_cps"), plan


async def test_sin_licencia_se_usa_el_tope_de_la_prueba(mundo):
    async with async_session() as s:
        t = Tenant(name="Golf", slug="golf", sip_domain="golf.pbx.test", enabled=True)
        s.add(t)
        await s.commit()
        politica = await salientes.politica_de(s, t.id)
    assert politica.cps == licensing.PLANES["trial"]["max_outbound_cps"]


async def test_clic_para_llamar_respeta_el_tope(cliente, mundo, foxtrot, monkeypatch):
    async def bgapi(cmd, **_kw):
        return "+OK Job-UUID: x"

    monkeypatch.setattr(esl, "bgapi", bgapi)
    async with async_session() as s:
        await s.execute(update(License).where(License.tenant_id == foxtrot["tenant"]).values(max_outbound_cps=2))
        await s.commit()
    salientes._ULTIMAS.clear()
    url, cuerpo = f"/api/extensions/{foxtrot['ext']}/call", {"destination": "3001234567", "trunk_id": foxtrot["trunk"]}
    codigos = [(await cliente.post(url, json=cuerpo, headers=foxtrot["cab"])).status_code for _ in range(3)]
    assert codigos == [200, 200, 429]
    await asyncio.sleep(1.05)
    assert (await cliente.post(url, json=cuerpo, headers=foxtrot["cab"])).status_code == 200


def test_ritmo_por_empresa():
    salientes._ULTIMAS.clear()
    salientes.exigir_ritmo(1, 1)
    with pytest.raises(salientes.RitmoExcedido):
        salientes.exigir_ritmo(1, 1)
    salientes.exigir_ritmo(2, 1)  # otra empresa, su propio tope
    salientes.exigir_ritmo(1, None)  # sin tope
