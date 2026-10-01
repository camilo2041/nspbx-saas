"""Salientes de los teléfonos solo en horario laboral (opcional por empresa).

Probado además con FreeSWITCH real (docs/seguridad-y-robustez.md, §5.6):
fuera de horario, la extensión sin permiso recibe CALL_REJECTED y la que
tiene permiso sale. Acá: el dialplan que se genera y el clic para llamar.
Las franjas "-" (nunca) y "00:00-24:00" + domingos (siempre) hacen que las
pruebas no dependan de la hora en que corren.
"""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import Extension, License, OutboundRoute, SystemSettings, Tenant, Trunk, User
from app.services import esl, horario_marcacion, salientes
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET

CERRADO = {"outbound_hours_enabled": True, "outbound_hours_weekdays": "-", "outbound_hours_saturday": "-",
           "outbound_hours_sundays_holidays": False}
ABIERTO = {"outbound_hours_enabled": True, "outbound_hours_weekdays": "00:00-24:00",
           "outbound_hours_saturday": "00:00-24:00", "outbound_hours_sundays_holidays": True}
APAGADO = {"outbound_hours_enabled": False}


@pytest.fixture(scope="module")
async def india(mundo):
    async with async_session() as s:
        t = Tenant(name="India", slug="india", sip_domain="india.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        await get_or_create_settings(s, t.id)
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.india.test", register_enabled=False)
        sin = Extension(tenant_id=t.id, number="1000", password="clave-sip-india-larga-1")  # gitleaks:allow (clave de prueba)
        con = Extension(tenant_id=t.id, number="1001", password="clave-sip-india-larga-2", outbound_after_hours=True)  # gitleaks:allow (clave de prueba)
        apagada = Extension(tenant_id=t.id, number="1002", password="clave-sip-india-larga-3",  # gitleaks:allow (clave de prueba)
                            outbound_after_hours=True, enabled=False)
        s.add_all([troncal, sin, con, apagada])
        await s.flush()
        s.add(OutboundRoute(tenant_id=t.id, name="todo", pattern="3XXXXXXXXX", trunk_ids=str(troncal.id)))
        admin = User(tenant_id=t.id, username="admin-india", full_name="admin india",
                     password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True)
        s.add(admin)
        await s.commit()
        return {"tenant": t.id, "sin": sin.id, "con": con.id, "trunk": troncal.id,
                "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"}}


async def _horario(india, valores):
    async with async_session() as s:
        await s.execute(update(SystemSettings).where(SystemSettings.tenant_id == india["tenant"]).values(**valores))
        await s.commit()


async def _extensiones(cliente) -> list[ET.Element]:
    raiz = ET.fromstring((await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})).text)
    return raiz.find(".//context[@name='ctx_india']").findall("extension")


async def test_fuera_de_horario_el_dialplan_deja_salir_solo_a_las_permitidas(cliente, india):
    await _horario(india, CERRADO)
    extensiones = await _extensiones(cliente)
    nombres = [e.get("name") for e in extensiones]
    assert "Outbound_FueraDeHorario" in nombres
    regla = extensiones[nombres.index("Outbound_FueraDeHorario")]
    assert regla.get("continue") == "true"
    # Va antes de toda ruta de salida.
    primera_salida = min(i for i, e in enumerate(extensiones)
                         if any((a.get("data") or "").startswith("sofia/gateway/") for a in e.iter("action")))
    assert nombres.index("Outbound_FueraDeHorario") < primera_salida
    usuario = regla.find("condition[@field='${user_name}']")
    # Vacío (no viene de un teléfono) o la 1001; la 1002 tiene permiso pero está desactivada.
    assert usuario.get("expression") == "^(|1001)$"
    assert [a.get("data") for a in usuario.findall("anti-action")][-1] == "CALL_REJECTED"


@pytest.mark.parametrize("valores", [ABIERTO, APAGADO])
async def test_en_horario_o_sin_limite_no_hay_regla(cliente, india, valores):
    await _horario(india, valores)
    assert "Outbound_FueraDeHorario" not in [e.get("name") for e in await _extensiones(cliente)]


async def test_clic_para_llamar_respeta_el_horario(cliente, india, monkeypatch):
    async def bgapi(cmd):
        return "+OK Job-UUID: x"

    monkeypatch.setattr(esl, "bgapi", bgapi)
    salientes._ULTIMAS.clear()
    await _horario(india, CERRADO)
    cuerpo = {"destination": "3001234567", "trunk_id": india["trunk"]}
    resp = await cliente.post(f"/api/extensions/{india['sin']}/call", json=cuerpo, headers=india["cab"])
    assert resp.status_code == 403 and "horario" in resp.text
    resp = await cliente.post(f"/api/extensions/{india['con']}/call", json=cuerpo, headers=india["cab"])
    assert resp.status_code == 200, resp.text
    await _horario(india, APAGADO)
    salientes._ULTIMAS.clear()
    resp = await cliente.post(f"/api/extensions/{india['sin']}/call", json=cuerpo, headers=india["cab"])
    assert resp.status_code == 200, resp.text


async def test_ajustes_validan_el_horario(cliente, india):
    resp = await cliente.put("/api/system/settings", json={"outbound_hours_weekdays": "25:00-26:00"},
                             headers=india["cab"])
    assert resp.status_code == 422


def test_un_horario_mal_guardado_cierra_en_vez_de_abrir():
    roto = SimpleNamespace(outbound_hours_enabled=True, outbound_hours_weekdays="nada",
                           outbound_hours_saturday="08:00-13:00", outbound_hours_sundays_holidays=True)
    from datetime import datetime

    h = horario_marcacion.horario_salientes_de(roto)
    assert not horario_marcacion.en_horario(h, datetime(2026, 10, 6, 10, 0))
    assert horario_marcacion.horario_salientes_de(SimpleNamespace(outbound_hours_enabled=False)) is None
