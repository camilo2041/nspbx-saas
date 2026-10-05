"""Resúmenes que ahora se suman en la base en vez de traer todas las filas.

Se comparan contra la cuenta fila por fila que se hacía antes (la de
referencia), con datos de las dos empresas: el resultado tiene que ser el
mismo y no puede incluir a la otra.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.ai_usage import Tarifas
from app.core.database import async_session, engine
from app.models import AiCallUsage, Debt, PaymentPromise
from app.services.ajustes import ajustes_de

_PROVEEDORES = [("elevenlabs", "elevenlabs"), ("deepgram", "deepgram"), ("edge", "deepgram"), (None, None)]


@pytest.fixture(scope="module")
async def consumo_ia(mundo):
    ahora = datetime.utcnow()
    filas = {"alfa": [], "beta": []}
    async with async_session() as s:
        for e, n in (("alfa", 23), ("beta", 7)):
            tid = getattr(mundo, e).id
            for i in range(n):
                tts, stt = _PROVEEDORES[i % 4]
                f = AiCallUsage(
                    tenant_id=tid, call_uuid=f"res-{e}-{i}", tts_provider=tts, stt_provider=stt,
                    tts_chars=137 * i + 11, stt_seconds=7 * i, llm_calls=i % 3,
                    llm_prompt_tokens=1000 + 31 * i, llm_completion_tokens=90 + i, turns=i % 5,
                    resolved=i % 2 == 0, duration_seconds=40 + i, started_at=ahora - timedelta(days=i % 5, hours=1),
                )
                s.add(f)
                filas[e].append(f)
        await s.commit()
    yield filas
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM ai_call_usage WHERE call_uuid LIKE 'res-%'"))


async def _tarifas(tenant_id):
    async with async_session() as s:
        return Tarifas(await ajustes_de(s, tenant_id))


async def test_resumen_de_ia_igual_que_fila_por_fila(mundo, cliente, consumo_ia):
    resp = await cliente.get("/api/ai-usage/summary", params={"days": 30}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, resp.text
    r = resp.json()
    propias = consumo_ia["alfa"]
    # La semilla de conftest también tiene una conversación de alfa, sin fecha reciente o con:
    # se compara contra lo que hay en la base para alfa en la ventana.
    async with engine.connect() as conn:
        n = (await conn.execute(text(
            "SELECT count(*) FROM ai_call_usage WHERE tenant_id = :t AND started_at >= now() - interval '30 days'"
        ), {"t": mundo.alfa.id})).scalar()
    assert r["calls"] == n and n >= len(propias)
    t = await _tarifas(mundo.alfa.id)
    esperado = sum(t.costo_llamada(f) for f in propias)
    otras = r["cost_usd"] - esperado
    assert abs(otras) < 0.01, (r["cost_usd"], esperado)  # sin la semilla de beta (7 filas caras)
    por_clave = {p["key"]: p for p in r["providers"]}
    assert por_clave["deepgram"]["tts_chars"] == sum(f.tts_chars for f in propias if f.tts_provider == "deepgram")


async def test_serie_diaria_igual_que_fila_por_fila(mundo, cliente, consumo_ia):
    resp = await cliente.get("/api/ai-usage/daily", params={"days": 7}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200
    serie = resp.json()
    assert len(serie) == 7
    propias = consumo_ia["alfa"]
    assert sum(d["calls"] for d in serie) >= len(propias)
    assert sum(d["tts_chars"] for d in serie) >= sum(f.tts_chars for f in propias)
    # Nada de beta: sus 7 filas sumarían más caracteres de los que tiene alfa fuera de la semilla.
    beta = sum(f.tts_chars for f in consumo_ia["beta"])
    assert sum(d["tts_chars"] for d in serie) < sum(f.tts_chars for f in propias) + beta


@pytest.mark.parametrize("ruta", ["/api/ai-usage/summary", "/api/ai-usage/daily", "/api/appointments/gestion"])
async def test_la_ventana_de_dias_tiene_tope(mundo, cliente, ruta):
    """Sin tope, daily?days=1000000000 armaba mil millones de días en memoria."""
    for dias in (0, 367, 1000000000):
        resp = await cliente.get(ruta, params={"days": dias}, headers=mundo.alfa.cabeceras())
        assert resp.status_code == 422, (ruta, dias)


async def test_resumen_de_cobranza_igual_que_fila_por_fila(mundo, cliente):
    async with async_session() as s:
        s.add_all([
            Debt(tenant_id=mundo.alfa.id, phone="3001230001", debtor_name="R1", amount=100.5, status="open"),
            Debt(tenant_id=mundo.alfa.id, phone="3001230002", debtor_name="R2", amount=200.25, status="paid"),
            Debt(tenant_id=mundo.alfa.id, phone="3001230003", debtor_name="R3", amount=300, status="overdue"),
            Debt(tenant_id=mundo.beta.id, phone="3001230004", debtor_name="R4", amount=99999, status="open"),
            PaymentPromise(tenant_id=mundo.alfa.id, phone="3001230001", amount_promised=50, promise_date=datetime.utcnow()),
            PaymentPromise(tenant_id=mundo.beta.id, phone="3001230004", amount_promised=77777, promise_date=datetime.utcnow()),
        ])
        await s.commit()
    try:
        resp = await cliente.get("/api/cobranza/summary", headers=mundo.alfa.cabeceras())
        assert resp.status_code == 200, resp.text
        r = resp.json()
        async with engine.connect() as conn:
            deudas = (await conn.execute(text("SELECT status, amount FROM debts WHERE tenant_id = :t"), {"t": mundo.alfa.id})).all()
            promesas = (await conn.execute(text("SELECT status, amount_promised FROM payment_promises WHERE tenant_id = :t"), {"t": mundo.alfa.id})).all()
        assert r == {
            "debts_total": len(deudas),
            "debts_open": sum(1 for st, _ in deudas if st == "open"),
            "amount_owed": round(sum(a for st, a in deudas if st in ("open", "promised", "overdue")), 2),
            "promises_total": len(promesas),
            "promises_pending": sum(1 for st, _ in promesas if st == "pending"),
            "amount_promised": round(sum(a for _, a in promesas), 2),
        }
        assert r["amount_owed"] < 99999 and r["amount_promised"] < 77777  # nada de beta
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM payment_promises WHERE phone LIKE '300123000%'"))
            await conn.execute(text("DELETE FROM debts WHERE phone LIKE '300123000%'"))


async def test_cargar_numeros_solo_mira_los_que_llegan(mundo, cliente):
    """Actualiza los que ya estaban, agrega los nuevos y el total es el de la campaña."""
    camp = mundo.alfa.ids["campaign"]
    url = f"/api/campaigns/{camp}/numbers"
    previo = (await cliente.get(f"/api/campaigns/{camp}/stats", headers=mundo.alfa.cabeceras())).json()
    try:
        r1 = await cliente.post(url, json={"numbers": [{"phone": "3005550001"}, {"phone": "3005550002"}]},
                                headers=mundo.alfa.cabeceras())
        assert r1.status_code == 201, r1.text
        r2 = await cliente.post(url, json={"numbers": [
            {"phone": "3005550002", "vars": {"cliente": "Ana"}}, {"phone": "3005550003"}, {"phone": "3005550003"},
        ]}, headers=mundo.alfa.cabeceras())
        assert r2.status_code == 201, r2.text
        assert (r2.json()["added"], r2.json()["updated"]) == (1, 1)
        async with engine.connect() as conn:
            total = (await conn.execute(text("SELECT count(*) FROM campaign_numbers WHERE campaign_id = :c"), {"c": camp})).scalar()
            extra = (await conn.execute(text("SELECT extra_data FROM campaign_numbers WHERE phone = '3005550002'"))).scalar()
        assert r2.json()["total"] == total
        assert "Ana" in extra
        assert previo  # la campaña existía con sus números de semilla
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM campaign_numbers WHERE phone LIKE '300555000%'"))
