"""API pública (/api/v1) y sus claves.

Lo que importa: una clave es de UNA empresa y solo puede lo que dicen sus
permisos; no sirve en el panel, y el token del panel no sirve acá; revocada
o vencida no entra; y con todos los permisos sigue sin alcanzar a otra
empresa.
"""

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core import claves_api
from app.core.config import settings
from app.core.database import engine

from .rutas import rutas_api

from .conftest import foto_de_empresa

TODOS = sorted(claves_api.ESCOPOS)


@pytest.fixture(autouse=True)
async def _limpio():
    """Sin el tope de peticiones de la prueba anterior, y sin acumular claves
    (hay un máximo de claves activas por empresa)."""
    claves_api.limitador.reiniciar()
    yield
    claves_api.limitador.reiniciar()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM api_keys WHERE key_hash <> :semilla"), {"semilla": "0" * 64})


async def _crear(cliente, empresa, scopes, nombre="integracion-prueba", **extra) -> dict:
    resp = await cliente.post(
        "/api/claves-api", json={"name": nombre, "scopes": scopes, **extra}, headers=empresa.cabeceras()
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _con(clave: str) -> dict:
    return {"Authorization": f"Bearer {clave}"}


async def test_la_clave_se_muestra_una_vez_y_se_guarda_como_hash(mundo, cliente):
    nueva = await _crear(cliente, mundo.alfa, ["llamadas:leer"])
    clave = nueva["clave"]
    assert clave.startswith(f"nspbx_{nueva['prefix']}_") and len(clave) > 40

    listado = await cliente.get("/api/claves-api", headers=mundo.alfa.cabeceras())
    assert listado.status_code == 200
    assert clave not in listado.text and "key_hash" not in listado.text
    assert nueva["prefix"] in listado.text

    async with engine.connect() as conn:
        fila = (await conn.execute(text("SELECT * FROM api_keys WHERE id = :i"), {"i": nueva["id"]})).one()
    assert clave not in str(tuple(fila))


async def test_gestion_de_claves_solo_administrador(mundo, cliente):
    for rol in ("supervisor", "asesor"):
        resp = await cliente.post("/api/claves-api", json={"name": "x-x", "scopes": ["llamadas:leer"]},
                                  headers=mundo.alfa.cabeceras(rol))
        assert resp.status_code == 403, rol
    resp = await cliente.post("/api/claves-api", json={"name": "x-x", "scopes": ["usuarios:gestionar"]},
                              headers=mundo.alfa.cabeceras())
    assert resp.status_code == 422


async def test_sin_clave_o_con_otra_credencial_no_entra(mundo, cliente):
    nueva = await _crear(cliente, mundo.alfa, TODOS)
    assert (await cliente.get("/api/v1/llamadas")).status_code == 401
    # El token del panel no sirve en la API pública…
    assert (await cliente.get("/api/v1/llamadas", headers=mundo.alfa.cabeceras())).status_code == 401
    # …ni la clave en el panel.
    assert (await cliente.get("/api/extensions", headers=_con(nueva["clave"]))).status_code == 401
    # Prefijo bueno, secreto inventado.
    falsa = f"nspbx_{nueva['prefix']}_{'A' * 43}"
    assert (await cliente.get("/api/v1/llamadas", headers=_con(falsa))).status_code == 401
    # Por X-API-Key también entra.
    assert (await cliente.get("/api/v1/llamadas", headers={"X-API-Key": nueva["clave"]})).status_code == 200


async def test_solo_puede_lo_que_dicen_sus_permisos(mundo, cliente):
    clave = (await _crear(cliente, mundo.alfa, ["llamadas:leer"]))["clave"]
    resp = await cliente.get("/api/v1/llamadas", headers=_con(clave))
    assert resp.status_code == 200
    assert mundo.alfa.telefono in resp.text and mundo.beta.telefono not in resp.text
    assert "recording" not in resp.text and "summary" not in resp.text

    assert (await cliente.get("/api/v1/citas", headers=_con(clave))).status_code == 403
    resp = await cliente.post(f"/api/v1/campanas/{mundo.alfa.ids['campaign']}/numeros",
                              json={"numbers": [{"phone": "3001234567"}]}, headers=_con(clave))
    assert resp.status_code == 403


async def test_revocada_o_vencida_no_entra(mundo, cliente):
    nueva = await _crear(cliente, mundo.alfa, ["llamadas:leer"])
    assert (await cliente.get("/api/v1/llamadas", headers=_con(nueva["clave"]))).status_code == 200
    resp = await cliente.delete(f"/api/claves-api/{nueva['id']}", headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200 and resp.json()["revoked_at"]
    assert (await cliente.get("/api/v1/llamadas", headers=_con(nueva["clave"]))).status_code == 401

    vence = await _crear(cliente, mundo.alfa, ["llamadas:leer"], dias_validez=1)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE api_keys SET expires_at = :t WHERE id = :i"),
                           {"t": datetime.utcnow() - timedelta(seconds=1), "i": vence["id"]})
    assert (await cliente.get("/api/v1/llamadas", headers=_con(vence["clave"]))).status_code == 401


async def test_otra_empresa_no_revoca_mis_claves(mundo, cliente):
    nueva = await _crear(cliente, mundo.alfa, ["llamadas:leer"])
    resp = await cliente.delete(f"/api/claves-api/{nueva['id']}", headers=mundo.beta.cabeceras())
    assert resp.status_code == 404
    assert (await cliente.get("/api/v1/llamadas", headers=_con(nueva["clave"]))).status_code == 200


def _rutas_v1():
    for ruta, metodos in rutas_api():
        if ruta.startswith("/api/v1/"):
            for m in sorted(metodos - {"HEAD", "OPTIONS"}):
                yield m, ruta


_CUERPOS = {
    ("POST", "/api/v1/campanas/{campaign_id}/numeros"): {"numbers": [{"phone": "3001234567"}]},
}


@pytest.mark.parametrize("metodo,ruta", [r for r in _rutas_v1() if "{" in r[1]])
async def test_con_todos_los_permisos_no_alcanza_a_otra_empresa(mundo, cliente, metodo, ruta):
    clave = (await _crear(cliente, mundo.alfa, TODOS))["clave"]
    antes = await foto_de_empresa(mundo.beta.id)
    recursos = {"campaign_id": "campaign"}
    url = re.sub(r"\{(\w+)\}", lambda m: str(mundo.beta.ids[recursos[m.group(1)]]), ruta)
    resp = await cliente.request(metodo, url, json=_CUERPOS.get((metodo, ruta)), headers=_con(clave))
    assert resp.status_code in (403, 404), f"{metodo} {ruta}: {resp.status_code} {resp.text[:200]}"
    assert mundo.beta.marca not in resp.text
    assert await foto_de_empresa(mundo.beta.id) == antes


@pytest.mark.parametrize("metodo,ruta", [r for r in _rutas_v1() if "{" not in r[1] and r[0] == "GET"])
async def test_los_listados_no_muestran_otra_empresa(mundo, cliente, metodo, ruta):
    clave = (await _crear(cliente, mundo.alfa, TODOS))["clave"]
    resp = await cliente.get(ruta, headers=_con(clave))
    assert resp.status_code == 200, resp.text
    assert mundo.beta.marca not in resp.text and mundo.beta.telefono not in resp.text


async def test_cargar_numeros_aplica_la_politica_de_salientes(mundo, cliente):
    clave = (await _crear(cliente, mundo.alfa, ["campanas:escribir"]))["clave"]
    resp = await cliente.post(
        f"/api/v1/campanas/{mundo.alfa.ids['campaign']}/numeros",
        json={"numbers": [{"phone": "3005550101"}, {"phone": "+447700900123"}]}, headers=_con(clave),
    )
    assert resp.status_code == 201, resp.text
    cuerpo = resp.json()
    assert cuerpo["added"] == 1
    assert [b["phone"] for b in cuerpo["bloqueados"]] == ["+447700900123"]
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM campaign_numbers WHERE phone = '3005550101'"))


async def test_crear_cita(mundo, cliente):
    clave = (await _crear(cliente, mundo.alfa, ["citas:escribir", "citas:leer"]))["clave"]
    cuando = (datetime.utcnow() + timedelta(days=20)).replace(hour=9, minute=0, second=0, microsecond=0)
    resp = await cliente.post("/api/v1/citas", headers=_con(clave), json={
        "patient_name": "Paciente API", "phone": "3005550202", "appointment_date": cuando.isoformat(),
    })
    assert resp.status_code == 201, resp.text
    listado = await cliente.get("/api/v1/citas", headers=_con(clave), params={"desde": cuando.isoformat()})
    assert "Paciente API" in listado.text
    async with engine.connect() as conn:
        tid = (await conn.execute(text("SELECT tenant_id FROM appointments WHERE id = :i"),
                                  {"i": resp.json()["id"]})).scalar_one()
        assert tid == mundo.alfa.id
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM appointments WHERE id = :i"), {"i": resp.json()["id"]})


async def test_tope_de_peticiones_por_clave(mundo, cliente, monkeypatch):
    monkeypatch.setattr(settings, "api_limite_por_minuto", 3)
    una = (await _crear(cliente, mundo.alfa, ["llamadas:leer"]))["clave"]
    otra = (await _crear(cliente, mundo.alfa, ["llamadas:leer"]))["clave"]
    codigos = [(await cliente.get("/api/v1/llamadas", headers=_con(una))).status_code for _ in range(4)]
    assert codigos == [200, 200, 200, 429]
    resp = await cliente.get("/api/v1/llamadas", headers=_con(una))
    assert resp.status_code == 429 and int(resp.headers["Retry-After"]) >= 1
    # El tope es por clave: otra integración no paga por la que se pasó.
    assert (await cliente.get("/api/v1/llamadas", headers=_con(otra))).status_code == 200


async def test_la_auditoria_dice_que_clave_fue(mundo, cliente):
    nueva = await _crear(cliente, mundo.alfa, ["llamadas:leer"], nombre="crm-auditado")
    await cliente.get("/api/v1/llamadas", headers=_con(nueva["clave"]))
    async with engine.connect() as conn:
        fila = (await conn.execute(text(
            "SELECT tenant_id, actor, result FROM audit_log WHERE action = 'GET /api/v1/llamadas' "
            "ORDER BY id DESC LIMIT 1"
        ))).one()
    assert fila == (mundo.alfa.id, f"api:crm-auditado ({nueva['prefix']})", "ok")


async def test_empresa_desactivada_no_entra(mundo, cliente):
    clave = (await _crear(cliente, mundo.beta, ["llamadas:leer"]))["clave"]
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE tenants SET enabled = false WHERE id = :t"), {"t": mundo.beta.id})
    try:
        assert (await cliente.get("/api/v1/llamadas", headers=_con(clave))).status_code == 403
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tenants SET enabled = true WHERE id = :t"), {"t": mundo.beta.id})
    assert (await cliente.get("/api/v1/llamadas", headers=_con(clave))).status_code == 200
