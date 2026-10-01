"""Avisos de CSP: llegan, se agrupan sin guardar datos, y no se pueden abusar."""

import pytest

from app.api import csp
from app.core.limitador import LimiteIntentos


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    csp.reiniciar()
    monkeypatch.setattr(csp, "_POR_IP", LimiteIntentos(maximo=60, ventana=60, bloqueo=60))
    yield
    csp.reiniciar()


_VIEJO = {"csp-report": {
    "document-uri": "https://pbx.ejemplo.com/softphone?token=secreto",
    "effective-directive": "connect-src",
    "blocked-uri": "wss://turn.ejemplo.com:5349/ruta?usuario=ana",
}}
_NUEVO = [{"type": "csp-violation", "body": {
    "documentURL": "https://pbx.ejemplo.com/calls", "effectiveDirective": "script-src-elem",
    "blockedURL": "https://cdn.ajeno.com/x.js",
}}]


async def test_se_agrupan_y_solo_guardan_el_origen(cliente, mundo):
    for _ in range(3):
        r = await cliente.post("/api/csp-report", content=__import__("json").dumps(_VIEJO),
                               headers={"Content-Type": "application/csp-report"})
        assert r.status_code == 204
    r = await cliente.post("/api/csp-report", json=_NUEVO, headers={"Content-Type": "application/reports+json"})
    assert r.status_code == 204

    resp = await cliente.get("/api/plataforma/csp", headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 200
    filas = {(f["directiva"], f["origen"], f["pagina"]): f["veces"] for f in resp.json()}
    assert filas == {
        ("connect-src", "wss://turn.ejemplo.com:5349", "/softphone"): 3,
        ("script-src-elem", "https://cdn.ajeno.com", "/calls"): 1,
    }
    # Ni el token de la página ni el usuario de la URL bloqueada.
    assert "secreto" not in resp.text and "ana" not in resp.text


async def test_solo_la_plataforma_ve_el_resumen(cliente, mundo):
    assert (await cliente.get("/api/plataforma/csp", headers=mundo.alfa.cabeceras())).status_code == 403
    assert (await cliente.get("/api/plataforma/csp")).status_code == 401


async def test_no_se_puede_abusar(cliente, monkeypatch):
    assert (await cliente.post("/api/csp-report", content=b"no es json")).status_code == 400
    assert (await cliente.post("/api/csp-report", content=b"x" * 20000)).status_code == 413
    monkeypatch.setattr(csp, "_MAX_GRUPOS", 2)
    for i in range(5):
        cuerpo = {"csp-report": {"effective-directive": "img-src", "blocked-uri": f"https://h{i}.test/a"}}
        await cliente.post("/api/csp-report", json=cuerpo)
    assert len(csp.resumen()) == 2
    monkeypatch.setattr(csp, "_POR_IP", LimiteIntentos(maximo=2, ventana=60, bloqueo=60))
    codigos = [(await cliente.post("/api/csp-report", json=_NUEVO)).status_code for _ in range(3)]
    assert codigos == [204, 204, 429]


async def test_no_queda_en_la_auditoria(cliente):
    from sqlalchemy import text

    from app.core.database import engine

    await cliente.post("/api/csp-report", json=_NUEVO)
    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM audit_log WHERE action LIKE '%csp-report%'"))).scalar()
    assert n == 0
