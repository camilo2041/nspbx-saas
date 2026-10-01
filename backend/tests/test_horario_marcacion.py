"""Franja de marcación de las campañas (Ley 2300 de 2023).

Cobranza: lunes a viernes 7:00-19:00, sábados 8:00-15:00, nunca domingos ni
festivos. La empresa puede achicar la franja pero no sacar a la cobranza de
la legal.
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.core.database import async_session, engine
from app.models import Campaign, CampaignNumber, License, SystemSettings, Tenant, Trunk
from app.services import horario_marcacion as hm
from app.services.ajustes import get_or_create_settings

_FESTIVOS_OFICIALES = {
    2025: ["01-01", "01-06", "03-24", "04-17", "04-18", "05-01", "06-02", "06-23", "06-30", "07-20", "08-07",
           "08-18", "10-13", "11-03", "11-17", "12-08", "12-25"],
    2026: ["01-01", "01-12", "03-23", "04-02", "04-03", "05-01", "05-18", "06-08", "06-15", "06-29", "07-20",
           "08-07", "08-17", "10-12", "11-02", "11-16", "12-08", "12-25"],
}


@pytest.mark.parametrize("anio", sorted(_FESTIVOS_OFICIALES))
def test_festivos_de_colombia(anio):
    assert hm.festivos(anio) == {date.fromisoformat(f"{anio}-{d}") for d in _FESTIVOS_OFICIALES[anio]}


def _aj(lv="07:00-19:00", sab="08:00-15:00", dom=False):
    return SimpleNamespace(campaign_hours_weekdays=lv, campaign_hours_saturday=sab, campaign_sundays_holidays=dom)


# 2026-10-06 martes, 2026-10-10 sábado, 2026-10-11 domingo, 2026-10-12 lunes festivo
@pytest.mark.parametrize("cuando,puede", [
    ("2026-10-06 06:59", False), ("2026-10-06 07:00", True), ("2026-10-06 18:59", True), ("2026-10-06 19:00", False),
    ("2026-10-10 07:59", False), ("2026-10-10 08:00", True), ("2026-10-10 14:59", True), ("2026-10-10 15:00", False),
    ("2026-10-11 10:00", False), ("2026-10-12 10:00", False),
])
def test_franja_legal_por_defecto(cuando, puede):
    ahora = datetime.fromisoformat(cuando)
    assert hm.puede_marcar(None, "cobranza", ahora) is puede
    assert hm.puede_marcar(_aj(), "confirmar", ahora) is puede


def test_la_cobranza_no_sale_de_la_franja_legal_aunque_la_empresa_la_amplie():
    amplia = _aj(lv="06:00-22:00", sab="06:00-22:00", dom=True)
    noche, domingo = datetime(2026, 10, 6, 20, 0), datetime(2026, 10, 11, 10, 0)
    assert hm.puede_marcar(amplia, "confirmar", noche) and hm.puede_marcar(amplia, "confirmar", domingo)
    assert not hm.puede_marcar(amplia, "cobranza", noche)
    assert not hm.puede_marcar(amplia, "cobranza", domingo)
    assert not hm.puede_marcar(amplia, "Cobranza ", noche)  # como venga escrita la intención


def test_la_empresa_puede_achicarla():
    angosta = _aj(lv="09:00-17:00", sab="-")
    assert not hm.puede_marcar(angosta, "cobranza", datetime(2026, 10, 6, 8, 0))
    assert hm.puede_marcar(angosta, "cobranza", datetime(2026, 10, 6, 9, 0))
    assert not hm.puede_marcar(angosta, "confirmar", datetime(2026, 10, 10, 10, 0))  # sábado sin marcación


def test_proxima_apertura_salta_domingo_y_festivo():
    # Sábado 10 de octubre a las 16:00 -> el lunes 12 es festivo -> martes 13 a las 7:00.
    assert hm.proxima_apertura(None, "cobranza", datetime(2026, 10, 10, 16, 0)) == datetime(2026, 10, 13, 7, 0)
    assert hm.proxima_apertura(None, "cobranza", datetime(2026, 10, 6, 6, 0)) == datetime(2026, 10, 6, 7, 0)


@pytest.mark.parametrize("malo", ["25:00-26:00", "19:00-07:00", "7-19", "07:00 a 19:00"])
def test_franjas_invalidas(malo):
    with pytest.raises(ValueError):
        hm.leer_franja(malo)


async def test_ajustes_validan_y_guardan_la_franja(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    for malo in ("25:00-26:00", "19:00-07:00"):
        resp = await cliente.put("/api/system/settings", json={"campaign_hours_weekdays": malo}, headers=cab)
        assert resp.status_code == 422, malo
    resp = await cliente.put("/api/system/settings", json={"campaign_hours_weekdays": "08:00-18:00",
                                                          "campaign_hours_saturday": ""}, headers=cab)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["campaign_hours_weekdays"], resp.json()["campaign_hours_saturday"]) == ("08:00-18:00", "-")
    estado = await cliente.get("/api/campaigns/horario", headers=cab)
    assert estado.status_code == 200 and set(estado.json()) == {"cobranza", "otras", "festivo_hoy"}
    await cliente.put("/api/system/settings", json={"campaign_hours_weekdays": "07:00-19:00",
                                                   "campaign_hours_saturday": "08:00-15:00"}, headers=cab)


# --- El marcador real ------------------------------------------------------------


@pytest.fixture
async def campana_de_cobranza(mundo):
    async with async_session() as s:
        t = Tenant(name="Hotel", slug="hotel", sip_domain="hotel.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        await get_or_create_settings(s, t.id)
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.hotel.test", register_enabled=False)
        s.add(troncal)
        await s.flush()
        camp = Campaign(tenant_id=t.id, name="cartera", trunk_id=troncal.id, status="running", ai_intent="cobranza")
        s.add(camp)
        await s.flush()
        num = CampaignNumber(tenant_id=t.id, campaign_id=camp.id, phone="3001234567")
        s.add(num)
        await s.commit()
        datos = {"tenant": t.id, "campaign": camp.id, "number": num.id}
    yield datos
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE campaigns SET status = 'paused' WHERE id = :c"), {"c": datos["campaign"]})


async def _ciclo(monkeypatch, ahora: datetime) -> list[int]:
    from app.services import esl
    from app.workers import dialer

    marcados = []

    async def estado():
        return {"current_sessions": 0}

    async def dial(self, session, campaign, number):
        marcados.append(number.id)

    monkeypatch.setattr(esl, "status", estado)
    monkeypatch.setattr(dialer, "now_local", lambda: ahora)
    monkeypatch.setattr(dialer.CampaignDialer, "_dial", dial)
    await dialer.CampaignDialer()._process_once()
    return marcados


async def test_el_marcador_espera_fuera_de_la_franja(monkeypatch, campana_de_cobranza):
    # Domingo: la campaña de cobranza no toma el número ni lo marca como fallido.
    marcados = await _ciclo(monkeypatch, datetime(2026, 10, 11, 10, 0))
    assert campana_de_cobranza["number"] not in marcados
    async with async_session() as s:
        assert (await s.get(CampaignNumber, campana_de_cobranza["number"])).status == "pending"

    # Martes a las 10: ahora sí.
    marcados = await _ciclo(monkeypatch, datetime(2026, 10, 6, 10, 0))
    assert campana_de_cobranza["number"] in marcados
