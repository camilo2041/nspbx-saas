"""Puesta en marcha: los pasos se marcan solos según lo que hay de verdad."""

import pytest

from app.services import esl


@pytest.fixture
def freeswitch(monkeypatch):
    estado = {"gateway": "REGED", "registros": ""}

    async def gateway_status(nombre):
        return {"state": estado["gateway"]}

    async def api(cmd, **_kw):
        return estado["registros"] if cmd == "show registrations" else "+OK"

    monkeypatch.setattr(esl, "gateway_status", gateway_status)
    monkeypatch.setattr(esl, "api", api)
    return estado


def _pasos(r):
    return {p["clave"]: p for p in r.json()["pasos"]}


async def test_los_pasos_reflejan_la_central(cliente, mundo, freeswitch):
    cab = mundo.alfa.cabeceras()
    r = await cliente.get("/api/system/puesta-en-marcha", headers=cab)
    assert r.status_code == 200, r.text
    pasos = _pasos(r)
    assert list(pasos)[:2] == ["proveedor", "equipo"]  # en el orden en que se hacen
    assert pasos["proveedor"]["hecho"] and pasos["entrante"]["hecho"]
    assert not pasos["telefono"]["hecho"] and pasos["telefono"]["enlace"] == "/softphone"
    assert pasos["grupo"]["opcional"]

    # El proveedor rechaza el registro: el paso lo dice.
    freeswitch["gateway"] = "FAIL_WAIT"
    pasos = _pasos(await cliente.get("/api/system/puesta-en-marcha", headers=cab))
    assert not pasos["proveedor"]["hecho"] and "no lo acepta" in pasos["proveedor"]["detalle"]

    # Un softphone de ESTA empresa conectado; uno de otra no cuenta.
    freeswitch["registros"] = (
        "reg_user,realm,token,url\n"
        f"1000,{mundo.beta.dominio},x,sofia/internal/1000\n"
    )
    assert not _pasos(await cliente.get("/api/system/puesta-en-marcha", headers=cab))["telefono"]["hecho"]
    freeswitch["registros"] += f"1000,{mundo.alfa.dominio},y,sofia/internal/1000\n"
    assert _pasos(await cliente.get("/api/system/puesta-en-marcha", headers=cab))["telefono"]["hecho"]
