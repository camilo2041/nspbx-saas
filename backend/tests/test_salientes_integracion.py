"""I5 de punta a punta: la política de salientes en los tres caminos de salida.

1. Dialplan (lo que marca un teléfono).
2. Clic-para-llamar (originate directo a la troncal).
3. Campañas (carga de números; el marcador usa la misma función).
"""

import re
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import update

from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import Campaign, Extension, License, OutboundRoute, SystemSettings, Tenant, Trunk, User
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


@pytest.fixture(scope="module")
async def delta(mundo):
    """Empresa con internacional habilitado solo hacia EE. UU. (+1), y una
    regla de salida que también lo permite."""
    async with async_session() as s:
        t = Tenant(name="Delta", slug="delta", sip_domain="delta.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        ajustes = await get_or_create_settings(s, t.id)
        ajustes.allow_international = True
        ajustes.international_countries = "1"
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.delta.test", register_enabled=False)
        ext = Extension(tenant_id=t.id, number="1000", password="clave-sip-delta-larga")
        s.add_all([troncal, ext])
        await s.flush()
        s.add(OutboundRoute(tenant_id=t.id, name="todo", pattern=".", trunk_ids=str(troncal.id), allow_international=True))
        camp = Campaign(tenant_id=t.id, name="avisos", trunk_id=troncal.id)
        admin = User(
            tenant_id=t.id, username="admin-delta", full_name="admin delta",
            password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True,
        )
        s.add_all([camp, admin])
        await s.commit()
        token = crear_token(admin.id, permissions.ADMIN, t.id)[0]
        return {
            "tenant": t.id, "ext": ext.id, "trunk": troncal.id, "campaign": camp.id,
            "cab": {"Authorization": f"Bearer {token}"},
        }


async def _expresiones_de_salida(cliente, slug: str) -> list[str]:
    resp = await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})
    raiz = ET.fromstring(resp.text)
    ctx = raiz.find(f".//context[@name='ctx_{slug}']")
    return [
        ext.find("condition[@field='destination_number']").get("expression")
        for ext in ctx.findall("extension")
        if any((a.get("data") or "").startswith("sofia/gateway/") for a in ext.iter("action"))
    ]


def _sale(expresiones: list[str], numero: str) -> bool:
    return any(re.match(e, numero) for e in expresiones)


async def test_dialplan_internacional_solo_a_los_paises_elegidos(cliente, delta):
    expresiones = await _expresiones_de_salida(cliente, "delta")
    assert expresiones
    assert _sale(expresiones, "+12125551234")
    assert _sale(expresiones, "0012125551234")
    assert _sale(expresiones, "3001234567")
    assert not _sale(expresiones, "+447700900123"), "país no elegido"
    assert not _sale(expresiones, "+19005551234"), "premium de Norteamérica"
    assert not _sale(expresiones, "+8811234567"), "satelital"


async def test_dialplan_el_permiso_de_la_regla_no_alcanza_sin_el_de_la_empresa(cliente, delta):
    async with async_session() as s:
        await s.execute(
            update(SystemSettings).where(SystemSettings.tenant_id == delta["tenant"]).values(allow_international=False)
        )
        await s.commit()
    try:
        expresiones = await _expresiones_de_salida(cliente, "delta")
        assert _sale(expresiones, "3001234567")
        assert not _sale(expresiones, "+12125551234")
        assert not _sale(expresiones, "0012125551234")
    finally:
        async with async_session() as s:
            await s.execute(
                update(SystemSettings).where(SystemSettings.tenant_id == delta["tenant"]).values(allow_international=True)
            )
            await s.commit()


@pytest.mark.parametrize("destino", ["+447700900123", "+19005551234", "008811234567", "447700900123"])
async def test_clic_para_llamar_respeta_la_politica(cliente, delta, destino):
    """Antes iba directo a la troncal sin ningún filtro."""
    resp = await cliente.post(
        f"/api/extensions/{delta['ext']}/call",
        headers=delta["cab"],
        json={"destination": destino, "trunk_id": delta["trunk"]},
    )
    assert resp.status_code == 403, resp.text
    assert "FreeSWITCH" not in resp.text, "llegó a intentar el originate"


async def test_clic_para_llamar_a_un_pais_permitido_llega_a_freeswitch(cliente, delta):
    """Control positivo: el rechazo de arriba es la política, no otra cosa.
    En las pruebas no hay FreeSWITCH, así que llegar a él es un 502."""
    resp = await cliente.post(
        f"/api/extensions/{delta['ext']}/call",
        headers=delta["cab"],
        json={"destination": "+12125551234", "trunk_id": delta["trunk"]},
    )
    assert resp.status_code == 502, resp.text


async def test_campania_no_carga_destinos_prohibidos(cliente, delta):
    resp = await cliente.post(
        f"/api/campaigns/{delta['campaign']}/numbers",
        headers=delta["cab"],
        json={"numbers": [{"phone": "3001234567"}, {"phone": "+12125551234"}, {"phone": "+447700900123"}, {"phone": "+8811234567"}]},
    )
    assert resp.status_code == 201, resp.text
    datos = resp.json()
    assert datos["added"] == 2
    assert sorted(b["phone"] for b in datos["bloqueados"]) == ["+447700900123", "+8811234567"]


async def test_ajustes_guardan_los_paises_normalizados(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    resp = await cliente.put("/api/system/settings", headers=cab, json={"international_countries": " +57; 1, abc"})
    assert resp.status_code == 422  # letras: rechazado por el esquema
    resp = await cliente.put("/api/system/settings", headers=cab, json={"international_countries": " +57; 1,,57 "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["international_countries"] == "57,1"
