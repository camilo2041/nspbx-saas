"""Consumo mensual: cuenta lo que se factura y nada de otra empresa."""

import os
from datetime import datetime

import pytest
from sqlalchemy import text

from app.core import claves_api
from app.core.config import settings
from app.core.database import async_session, engine
from app.models import AiCallUsage, CallLog
from app.services import consumo

MES = "2025-03"


@pytest.fixture(scope="module")
async def mes_con_trafico(mundo):
    dia = datetime(2025, 3, 10, 12, 0)
    async with async_session() as s:
        s.add_all([
            # alfa: 2 min por troncal, 1 min interno, una sin contestar.
            CallLog(tenant_id=mundo.alfa.id, uuid="cons-a1", direction="outbound", status="answered",
                    billsec=120, via_trunk=True, started_at=dia),
            CallLog(tenant_id=mundo.alfa.id, uuid="cons-a2", direction="outbound", status="answered",
                    billsec=60, via_trunk=False, started_at=dia),
            CallLog(tenant_id=mundo.alfa.id, uuid="cons-a3", direction="outbound", status="no_answer",
                    billsec=0, via_trunk=True, started_at=dia),
            # Fuera del mes: no cuenta.
            CallLog(tenant_id=mundo.alfa.id, uuid="cons-a4", direction="outbound", status="answered",
                    billsec=600, via_trunk=True, started_at=datetime(2025, 4, 1, 0, 0)),
            # beta: mucho tráfico el mismo mes, que no se puede sumar a alfa.
            CallLog(tenant_id=mundo.beta.id, uuid="cons-b1", direction="outbound", status="answered",
                    billsec=6000, via_trunk=True, started_at=dia),
            AiCallUsage(tenant_id=mundo.alfa.id, call_uuid="cons-ia-a", tts_chars=1000, stt_seconds=60,
                        duration_seconds=90, started_at=dia),
            AiCallUsage(tenant_id=mundo.beta.id, call_uuid="cons-ia-b", tts_chars=99000, duration_seconds=900,
                        started_at=dia),
        ])
        await s.commit()
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM call_logs WHERE uuid LIKE 'cons-%'"))
        await conn.execute(text("DELETE FROM ai_call_usage WHERE call_uuid LIKE 'cons-%'"))


async def test_resumen_de_la_empresa(mundo, cliente, mes_con_trafico):
    resp = await cliente.get("/api/consumo", params={"mes": MES}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert (r["llamadas"], r["llamadas_contestadas"], r["minutos_hablados"]) == (3, 2, 3.0)
    assert (r["llamadas_por_troncal"], r["minutos_por_troncal"]) == (2, 2.0)
    assert (r["conversaciones_ia"], r["minutos_ia"], r["tts_caracteres"]) == (1, 1.5, 1000)
    assert r["costo_ia_usd"] > 0
    assert r["tenant_id"] == mundo.alfa.id


async def test_las_grabaciones_cuentan_solo_las_propias(mundo, cliente):
    carpeta = os.path.join(settings.recordings_dir, f"t{mundo.beta.id}", "consumo")
    os.makedirs(carpeta, exist_ok=True)
    archivo = os.path.join(carpeta, "grande.wav")
    with open(archivo, "wb") as f:
        f.write(b"\0" * 3 * 1024 * 1024)
    try:
        alfa = (await cliente.get("/api/consumo", headers=mundo.alfa.cabeceras())).json()
        beta = (await cliente.get("/api/consumo", headers=mundo.beta.cabeceras())).json()
        assert beta["grabaciones_mb"] >= 3.0
        assert alfa["grabaciones_mb"] < 3.0
    finally:
        os.unlink(archivo)


async def test_mes_invalido_y_permisos(mundo, cliente):
    for mes in ("2025-13", "marzo", "2025"):
        resp = await cliente.get("/api/consumo", params={"mes": mes}, headers=mundo.alfa.cabeceras())
        assert resp.status_code == 422, mes
    for rol in ("supervisor", "asesor"):
        assert (await cliente.get("/api/consumo", headers=mundo.alfa.cabeceras(rol))).status_code == 403
    assert (await cliente.get("/api/consumo", headers=mundo.cabeceras_plataforma())).status_code == 403


async def test_csv_de_la_empresa(mundo, cliente):
    resp = await cliente.get("/api/consumo/csv", params={"meses": 3}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    lineas = resp.text.strip().splitlines()
    assert lineas[0].startswith("mes,tenant_id,llamadas")
    assert len(lineas) == 4
    assert all(f",{mundo.alfa.id}," in l for l in lineas[1:])


async def test_plataforma_ve_todas_y_la_empresa_no_entra(mundo, cliente, mes_con_trafico):
    resp = await cliente.get("/api/plataforma/consumo", params={"mes": MES}, headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 200, resp.text
    por_empresa = {f["tenant_id"]: f for f in resp.json()}
    assert por_empresa[mundo.alfa.id]["minutos_por_troncal"] == 2.0
    assert por_empresa[mundo.beta.id]["minutos_por_troncal"] == 100.0

    csv_ = await cliente.get("/api/plataforma/consumo/csv", params={"mes": MES}, headers=mundo.cabeceras_plataforma())
    assert csv_.status_code == 200 and "Empresa zzbeta" in csv_.text
    assert f'consumo-{MES}.csv' in csv_.headers["content-disposition"]

    assert (await cliente.get("/api/plataforma/consumo", headers=mundo.alfa.cabeceras())).status_code == 403


async def test_api_v1(mundo, cliente, mes_con_trafico):
    claves_api.limitador.reiniciar()
    resp = await cliente.post("/api/claves-api", json={"name": "facturacion", "scopes": ["consumo:leer"]},
                              headers=mundo.alfa.cabeceras())
    clave = resp.json()["clave"]
    try:
        r = await cliente.get("/api/v1/consumo", params={"mes": MES}, headers={"Authorization": f"Bearer {clave}"})
        assert r.status_code == 200 and r.json()["minutos_por_troncal"] == 2.0
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM api_keys WHERE name = 'facturacion'"))


def test_csv_no_ejecuta_formulas():
    salida = consumo.a_csv([{"empresa": "=HYPERLINK(\"http://x\")", "n": 1}, {"empresa": "Normal", "n": -2}])
    assert "'=HYPERLINK" in salida
    assert "Normal,-2" in salida  # los números negativos no se tocan


def test_meses_anteriores():
    meses = consumo.meses_anteriores(14)
    assert len(meses) == 14 and meses == sorted(meses)
    assert meses[-1] == datetime.utcnow().strftime("%Y-%m")
    assert consumo.rango_del_mes("2025-12")[1:] == (datetime(2025, 12, 1), datetime(2026, 1, 1))
