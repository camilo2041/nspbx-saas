"""Puesta en marcha: los pasos se marcan solos según lo que hay de verdad."""

import pytest

from app.services import esl


@pytest.fixture
def freeswitch(monkeypatch):
    estado = {"gateway": "REGED", "registros": ""}

    async def gateway_status(nombre, tenant_id=None):
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


# --- «Agregar persona»: usuario y extensión en un paso ------------------------------


async def test_agregar_persona_crea_su_extension(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    antes = [int(e["number"]) for e in (await cliente.get("/api/extensions", headers=cab)).json() if e["number"].isdigit()]
    r = await cliente.post("/api/users", headers=cab, json={
        "username": "ana.perez", "full_name": "Ana Pérez", "role": "asesor",
        "password": "Clave-Segura-9182", "crear_extension": True,  # gitleaks:allow (clave de prueba)
    })
    assert r.status_code == 201, r.text
    ext_id = r.json()["extension_id"]
    exts = {e["id"]: e for e in (await cliente.get("/api/extensions", headers=cab)).json()}
    nueva = exts[ext_id]
    # La siguiente a la mayor de la empresa, con el nombre de la persona.
    assert int(nueva["number"]) == max(antes) + 1 and nueva["caller_id_name"] == "Ana Pérez"
    assert len(nueva["password"]) >= 12

    # Con número elegido que ya está en uso: no crea nada a medias.
    r = await cliente.post("/api/users", headers=cab, json={
        "username": "luis", "full_name": "Luis", "role": "asesor", "password": "Clave-Segura-9182",  # gitleaks:allow
        "crear_extension": True, "numero_extension": "1000",
    })
    assert r.status_code == 409
    assert not any(u["username"] == "luis" for u in (await cliente.get("/api/users", headers=cab)).json())
