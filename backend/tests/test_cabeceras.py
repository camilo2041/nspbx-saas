"""Cabeceras de seguridad de la API (core/cabeceras.py)."""

import pytest


@pytest.mark.parametrize("ruta", ["/api/extensions", "/api/auth/me"])
async def test_respuestas_de_la_api(cliente, mundo, ruta):
    resp = await cliente.get(ruta, headers=mundo.alfa.cabeceras())
    h = resp.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["referrer-policy"] == "no-referrer"


async def test_tambien_en_errores(cliente, mundo):
    resp = await cliente.get("/api/extensions")
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "no-store"


async def test_no_pisa_el_tipo_de_una_grabacion(cliente, mundo):
    import os

    from app.core.config import settings

    with open(os.path.join(settings.recordings_dir, "alfa.wav"), "wb") as f:
        f.write(b"RIFFalfa")
    resp = await cliente.get(f"/api/calls/{mundo.alfa.ids['call']}/recording", headers=mundo.alfa.cabeceras())
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["x-content-type-options"] == "nosniff"
