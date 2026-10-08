"""Tope diario de cada campaña: llamadas lanzadas y minutos por troncal."""

import uuid as uuidlib
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core import permissions
from app.core.clock import now_local
from app.core.database import async_session, engine
from app.core.security import crear_token, hash_password
from app.models import CallLog, Campaign, CampaignNumber, License, Tenant, Trunk, User
from app.services import esl, tope_campanas
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


@pytest.fixture
async def juliett(mundo):
    """Empresa que puede marcar a cualquier hora (la prueba no depende del
    reloj) con una campaña de 6 números pendientes."""
    async with async_session() as s:
        t = Tenant(name="Juliett", slug=f"juliett{uuidlib.uuid4().hex[:6]}", sip_domain=f"j{uuidlib.uuid4().hex[:6]}.test",
                   modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        ajustes = await get_or_create_settings(s, t.id)
        ajustes.campaign_hours_weekdays = ajustes.campaign_hours_saturday = "00:00-24:00"
        ajustes.campaign_sundays_holidays = True
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.juliett.test", register_enabled=False)
        s.add(troncal)
        await s.flush()
        camp = Campaign(tenant_id=t.id, name="avisos", trunk_id=troncal.id, status="running", max_concurrency=50)
        s.add(camp)
        await s.flush()
        s.add_all([CampaignNumber(tenant_id=t.id, campaign_id=camp.id, phone=f"300100000{i}") for i in range(6)])
        admin = User(tenant_id=t.id, username=f"admin-{t.slug}", full_name="admin juliett",
                     password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True)
        s.add(admin)
        await s.commit()
        datos = {"tenant": t.id, "campaign": camp.id,
                 "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"}}
    yield datos
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE campaigns SET status = 'paused' WHERE id = :c"), {"c": datos["campaign"]})


async def _ciclo(monkeypatch, campaign_id) -> int:
    """Una vuelta del marcador; devuelve cuántas llamadas lanzó esa campaña."""
    from app.workers import dialer

    lanzadas = []

    async def estado():
        return {"current_sessions": 0}

    async def dial(self, session, campaign, number):
        if campaign.id == campaign_id:
            lanzadas.append(number.id)

    monkeypatch.setattr(esl, "status", estado)
    monkeypatch.setattr(dialer.CampaignDialer, "_dial", dial)
    await dialer.CampaignDialer()._process_once()
    return len(lanzadas)


async def _poner(campaign_id, **valores):
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == campaign_id).values(**valores))
        await s.commit()


async def test_tope_de_llamadas_por_dia(monkeypatch, juliett):
    await _poner(juliett["campaign"], max_calls_per_day=2)
    assert await _ciclo(monkeypatch, juliett["campaign"]) == 2
    assert await _ciclo(monkeypatch, juliett["campaign"]) == 0  # ya no hoy
    async with async_session() as s:
        c = await s.get(Campaign, juliett["campaign"])
        assert (c.calls_today, c.calls_today_date) == (2, now_local().date())
        pendientes = (await s.execute(select(func.count()).where(
            CampaignNumber.campaign_id == c.id, CampaignNumber.status == "pending"))).scalar()
    assert pendientes == 4  # esperan, no se dan por fallidos
    # Al día siguiente el contador arranca de cero.
    await _poner(juliett["campaign"], calls_today_date=now_local().date() - timedelta(days=1))
    assert await _ciclo(monkeypatch, juliett["campaign"]) == 2


async def test_tope_de_minutos_por_dia(monkeypatch, juliett):
    await _poner(juliett["campaign"], max_minutes_per_day=10)
    async with async_session() as s:
        s.add(CallLog(tenant_id=juliett["tenant"], campaign_id=juliett["campaign"], uuid=f"tope-{uuidlib.uuid4()}",
                      direction="outbound", status="answered", billsec=600, via_trunk=True,
                      started_at=datetime.utcnow()))
        await s.commit()
    assert await _ciclo(monkeypatch, juliett["campaign"]) == 0
    await _poner(juliett["campaign"], max_minutes_per_day=11)
    assert await _ciclo(monkeypatch, juliett["campaign"]) > 0


async def test_las_estadisticas_dicen_cuanto_lleva_y_por_que_paro(cliente, juliett, monkeypatch):
    await _poner(juliett["campaign"], max_calls_per_day=1)
    await _ciclo(monkeypatch, juliett["campaign"])
    r = (await cliente.get(f"/api/campaigns/{juliett['campaign']}/stats", headers=juliett["cab"])).json()
    assert r["llamadas_hoy"] == 1 and "tope de 1 llamadas" in r["tope_alcanzado"]


async def test_el_cdr_guarda_la_campana_solo_si_es_de_la_empresa(cliente, mundo, juliett):
    async def cdr(campaign_id, tenant_id):
        u = f"cdr-{uuidlib.uuid4()}"
        await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
            "uuid": u, "nspbx_tenant_id": str(tenant_id), "nspbx_campaign_id": str(campaign_id),
            "direction": "outbound", "billsec": "30", "hangup_cause": "NORMAL_CLEARING",
        }})
        async with async_session() as s:
            return (await s.execute(select(CallLog.campaign_id).where(CallLog.uuid == u))).scalar_one()

    assert await cdr(juliett["campaign"], juliett["tenant"]) == juliett["campaign"]
    # La campaña de juliett en una llamada de alfa: no se le cargan los minutos.
    assert await cdr(juliett["campaign"], mundo.alfa.id) is None
    assert await cdr("no-es-un-numero", juliett["tenant"]) is None


@pytest.mark.parametrize("campo", ["max_calls_per_day", "max_minutes_per_day"])
async def test_validacion_de_los_topes(cliente, juliett, campo):
    resp = await cliente.put(f"/api/campaigns/{juliett['campaign']}", json={campo: 0}, headers=juliett["cab"])
    assert resp.status_code == 422
    resp = await cliente.put(f"/api/campaigns/{juliett['campaign']}", json={campo: 50}, headers=juliett["cab"])
    assert resp.status_code == 200 and resp.json()[campo] == 50
    resp = await cliente.put(f"/api/campaigns/{juliett['campaign']}", json={campo: None}, headers=juliett["cab"])
    assert resp.status_code == 200 and resp.json()[campo] is None


def test_disponibles():
    hoy = date(2026, 10, 6)
    c = Campaign(max_calls_per_day=5, calls_today=3, calls_today_date=hoy, max_minutes_per_day=None)
    assert tope_campanas.disponibles(c, hoy, 0) == (2, None)
    assert tope_campanas.disponibles(c, hoy + timedelta(days=1), 0) == (5, None)  # día nuevo
    c.max_minutes_per_day = 30
    assert tope_campanas.disponibles(c, hoy, 30)[0] == 0
    sin = Campaign(max_calls_per_day=None, max_minutes_per_day=None, calls_today=0)
    assert tope_campanas.disponibles(sin, hoy, 9999) == (None, None)


async def test_la_lista_con_detalle_trae_los_topes(cliente, juliett):
    """El panel edita la campaña con lo que trae esta lista: si faltaban los
    topes, al guardar cualquier cambio quedaban borrados."""
    await _poner(juliett["campaign"], max_calls_per_day=7, max_minutes_per_day=90)
    lista = (await cliente.get("/api/campaigns/list/detail", headers=juliett["cab"])).json()
    c = next(x for x in lista if x["id"] == juliett["campaign"])
    assert (c["max_calls_per_day"], c["max_minutes_per_day"]) == (7, 90)
