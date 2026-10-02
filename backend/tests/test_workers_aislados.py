"""El marcador no mezcla empresas.

Recorre las campañas de todas las empresas con la sesión del dueño, pero lo
que hace con cada una (tomar números, leer troncal y bot, anotar el
resultado) va en una sesión atada a la empresa de la campaña. Estas pruebas
arman a propósito datos cruzados —que la API no deja crear— y comprueban que
el worker no los sigue.
"""

import uuid as uuidlib

import pytest
from sqlalchemy import select, text

from app.core.database import async_session, engine, sesion_de_empresa
from app.models import Campaign, CampaignNumber, License, Tenant, Trunk
from app.services import esl
from app.services.ajustes import get_or_create_settings


async def _empresa(s, nombre: str) -> dict:
    sufijo = uuidlib.uuid4().hex[:6]
    t = Tenant(name=nombre, slug=f"{nombre}{sufijo}", sip_domain=f"{nombre}{sufijo}.test",
               modules="voicebot,pbx", enabled=True)
    s.add(t)
    await s.flush()
    s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
    ajustes = await get_or_create_settings(s, t.id)
    ajustes.campaign_hours_weekdays = ajustes.campaign_hours_saturday = "00:00-24:00"
    ajustes.campaign_sundays_holidays = True
    troncal = Trunk(tenant_id=t.id, name="principal", gateway_host=f"sip.{nombre}.test", register_enabled=False)
    s.add(troncal)
    await s.flush()
    camp = Campaign(tenant_id=t.id, name="avisos", trunk_id=troncal.id, status="running", max_concurrency=50)
    s.add(camp)
    await s.flush()
    return {"tenant": t.id, "slug": t.slug, "trunk": troncal.id, "campaign": camp.id}


@pytest.fixture
async def dos(mundo):
    async with async_session() as s:
        a = await _empresa(s, "kilo")
        b = await _empresa(s, "lima")
        # Un número de LIMA colgado de la campaña de KILO.
        cruzado = CampaignNumber(tenant_id=b["tenant"], campaign_id=a["campaign"], phone="3002000001")
        propio = CampaignNumber(tenant_id=a["tenant"], campaign_id=a["campaign"], phone="3002000002")
        s.add_all([cruzado, propio])
        await s.commit()
        a["cruzado"], a["propio"] = cruzado.id, propio.id
    yield a, b
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE campaigns SET status = 'paused' WHERE id IN (:a, :b)"),
            {"a": a["campaign"], "b": b["campaign"]},
        )


async def test_la_sesion_de_empresa_no_ve_otra(dos):
    a, b = dos
    async with sesion_de_empresa(a["tenant"]) as s:
        assert await s.get(Campaign, a["campaign"]) is not None
        assert await s.get(Campaign, b["campaign"]) is None
        assert await s.get(Trunk, b["trunk"]) is None
        ids = (await s.execute(select(CampaignNumber.id))).scalars().all()
    assert a["propio"] in ids and a["cruzado"] not in ids


async def test_el_marcador_no_toma_numeros_de_otra_empresa(monkeypatch, dos):
    from app.workers import dialer

    a, _ = dos
    lanzados = []

    async def estado():
        return {"current_sessions": 0}

    async def dial(self, session, campaign, number):
        lanzados.append(number.id)

    monkeypatch.setattr(esl, "status", estado)
    monkeypatch.setattr(dialer.CampaignDialer, "_dial", dial)
    await dialer.CampaignDialer()._process_once()

    assert a["propio"] in lanzados
    assert a["cruzado"] not in lanzados
    async with async_session() as s:
        assert (await s.get(CampaignNumber, a["cruzado"])).status == "pending"


async def _marcar(monkeypatch, campaign_id: int, number_id: int) -> list[dict]:
    from app.workers import dialer

    llamadas = []

    async def originate(**kw):
        llamadas.append(kw)
        return "+OK"

    monkeypatch.setattr(esl, "originate", originate)
    async with async_session() as s:
        camp = await s.get(Campaign, campaign_id)
        num = await s.get(CampaignNumber, number_id)
    await dialer.CampaignDialer()._dial(None, camp, num)
    return llamadas


async def test_marca_solo_por_las_troncales_de_su_empresa(monkeypatch, dos):
    a, b = dos
    llamadas = await _marcar(monkeypatch, a["campaign"], a["propio"])
    assert len(llamadas) == 1
    tramos = llamadas[0]["endpoint"]
    assert tramos and all(t.startswith(f"sofia/gateway/{a['slug']}_") for t in tramos)
    assert llamadas[0]["extra_vars"]["nspbx_tenant_id"] == str(a["tenant"])
    async with async_session() as s:
        assert (await s.get(CampaignNumber, a["propio"])).status == "done"


async def test_una_troncal_ajena_no_se_usa(monkeypatch, dos):
    a, b = dos
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE campaigns SET trunk_id = :t, retries = 0 WHERE id = :c"),
            {"t": b["trunk"], "c": a["campaign"]},
        )
        # Como lo deja _process_once al tomarlo: un intento hecho.
        await conn.execute(
            text("UPDATE campaign_numbers SET status = 'dialing', attempts = 1 WHERE id = :n"), {"n": a["propio"]}
        )
    llamadas = await _marcar(monkeypatch, a["campaign"], a["propio"])
    assert llamadas == []
    async with async_session() as s:
        n = await s.get(CampaignNumber, a["propio"])
    assert n.status == "failed" and "troncal" in (n.last_error or "")
