"""Fase K: instalaciones locales con licencia firmada por la central."""

import json

import pytest
from sqlalchemy import delete

from app.api import instalaciones
from app.core.config import settings
from app.core.database import async_session
from app.core.limitador import LimiteIntentos
from app.models import Instalacion
from app.services import licencia_firmada as lf

_PRIVADA, _PUBLICA = lf.generar_par()


@pytest.fixture(autouse=True)
def _claves(monkeypatch):
    monkeypatch.setattr(settings, "licencia_clave_privada", _PRIVADA)
    monkeypatch.setattr(settings, "licencia_gracia_horas", 72)
    monkeypatch.setattr(instalaciones, "_POR_IP_ACTIVAR", LimiteIntentos(maximo=100, ventana=60, bloqueo=60))
    monkeypatch.setattr(instalaciones, "_POR_IP_LATIDO", LimiteIntentos(maximo=100, ventana=60, bloqueo=60))


async def _limpiar():
    async with async_session() as s:
        await s.execute(delete(Instalacion))
        await s.commit()


# --- Firma ----------------------------------------------------------------------------


def test_firma_y_verificacion():
    firmada = lf.firmar({"version": 1, "instalacion_id": 3, "empresa": {}, "licencia": {}, "emitida": "x",
                         "valida_hasta": "y"}, _PRIVADA)
    doc = lf.verificar(firmada["documento"], firmada["firma"], _PUBLICA)
    assert doc["instalacion_id"] == 3
    assert lf.publica_de(_PRIVADA) == _PUBLICA

    # Un solo carácter cambiado, otra clave o una firma basura: no pasa.
    alterado = firmada["documento"].replace('"instalacion_id":3', '"instalacion_id":4')
    with pytest.raises(lf.LicenciaInvalida):
        lf.verificar(alterado, firmada["firma"], _PUBLICA)
    with pytest.raises(lf.LicenciaInvalida):
        lf.verificar(firmada["documento"], firmada["firma"], lf.generar_par()[1])
    with pytest.raises(lf.LicenciaInvalida):
        lf.verificar(firmada["documento"], "no-es-base64!", _PUBLICA)
    with pytest.raises(lf.LicenciaInvalida):
        lf.verificar(firmada["documento"], firmada["firma"], "")


def test_codigo_legible_y_tolerante():
    codigo = lf.nuevo_codigo()
    assert codigo.startswith("NSPBX-") and len(codigo) == 20
    assert not set(codigo[6:].replace("-", "")) & set("01ILO")
    # Se acepta escrito en minúsculas, sin guiones o sin el prefijo.
    assert lf.hash_codigo(codigo) == lf.hash_codigo(codigo.lower().replace("-", " "))
    assert lf.hash_codigo(codigo) == lf.hash_codigo(codigo[6:])


def test_fechas_en_utc_ida_y_vuelta():
    from datetime import datetime

    local = datetime(2026, 12, 31, 23, 30)
    texto = lf.a_utc_iso(local)
    assert texto.endswith("Z") and lf.de_utc_iso(texto) == local


# --- De punta a punta -----------------------------------------------------------------


async def test_alta_activacion_y_latido(cliente, mundo):
    h = mundo.cabeceras_plataforma()
    await _limpiar()
    try:
        # Solo la plataforma.
        r = await cliente.post("/api/plataforma/instalaciones", headers=mundo.alfa.cabeceras(),
                               json={"empresa_id": mundo.alfa.id, "nombre": "Sede norte"})
        assert r.status_code == 403

        r = await cliente.post("/api/plataforma/instalaciones", headers=h,
                               json={"empresa_id": mundo.alfa.id, "nombre": "Sede norte"})
        assert r.status_code == 201, r.text
        inst = r.json()
        codigo = inst["codigo"]
        assert inst["estado"] == "pendiente"
        lista = (await cliente.get("/api/plataforma/instalaciones", headers=h)).json()
        assert lista["central_lista"] is True and "codigo" not in lista["instalaciones"][0]

        # Un código inventado no sirve.
        r = await cliente.post("/api/licencia/activar", json={"codigo": "NSPBX-AAAA-BBBB-CCCC"})
        assert r.status_code == 404

        r = await cliente.post("/api/licencia/activar", json={"codigo": codigo.lower(), "version": "1.0.0"})
        assert r.status_code == 200, r.text
        act = r.json()
        doc = lf.verificar(act["documento"], act["firma"], _PUBLICA)
        assert doc["instalacion_id"] == inst["id"]
        assert doc["empresa"]["nombre"] == "Empresa alfa" and set(doc["empresa"]["modules"]) == {"voicebot", "pbx"}
        assert doc["licencia"]["plan"] == "enterprise" and doc["licencia"]["status"] == "active"
        assert lf.de_utc_iso(doc["valida_hasta"]) > lf.de_utc_iso(doc["emitida"])

        # El código ya se usó.
        assert (await cliente.post("/api/licencia/activar", json={"codigo": codigo})).status_code == 404

        # Latido: sin token o con uno falso, no; con el suyo, licencia al día.
        assert (await cliente.post("/api/licencia/latido", json={})).status_code == 401
        assert (await cliente.post("/api/licencia/latido", json={}, headers={"Authorization": "Bearer falso"})).status_code == 401
        auth = {"Authorization": f"Bearer {act['token']}"}
        r = await cliente.post("/api/licencia/latido", headers=auth,
                               json={"version": "1.0.1", "uso": {"extensiones": 12, "minutos_salientes_mes": 340}})
        assert r.status_code == 200
        assert json.loads(r.json()["documento"])["licencia"]["status"] == "active"
        fila = next(i for i in (await cliente.get("/api/plataforma/instalaciones", headers=h)).json()["instalaciones"]
                    if i["id"] == inst["id"])
        assert fila["en_linea"] is True and fila["version"] == "1.0.1" and fila["uso"]["extensiones"] == 12

        # Suspendida: el próximo latido trae la licencia suspendida, firmada.
        assert (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/suspender", headers=h)).status_code == 200
        r = await cliente.post("/api/licencia/latido", headers=auth, json={})
        doc = lf.verificar(r.json()["documento"], r.json()["firma"], _PUBLICA)
        assert doc["licencia"]["status"] == "suspended"
        assert (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/reactivar", headers=h)).status_code == 200

        # Reinstalar: un código nuevo deja sin valor el token anterior.
        nuevo = (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/codigo", headers=h)).json()["codigo"]
        act2 = (await cliente.post("/api/licencia/activar", json={"codigo": nuevo})).json()
        assert (await cliente.post("/api/licencia/latido", headers=auth, json={})).status_code == 401
        auth2 = {"Authorization": f"Bearer {act2['token']}"}
        assert (await cliente.post("/api/licencia/latido", headers=auth2, json={})).status_code == 200

        # Una activa no se borra; revocada sí, y aun revocada recibe su suspensión.
        assert (await cliente.delete(f"/api/plataforma/instalaciones/{inst['id']}", headers=h)).status_code == 400
        assert (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/revocar", headers=h)).status_code == 200
        r = await cliente.post("/api/licencia/latido", headers=auth2, json={})
        assert json.loads(r.json()["documento"])["licencia"]["status"] == "suspended"
        assert (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/codigo", headers=h)).status_code == 400
        assert (await cliente.delete(f"/api/plataforma/instalaciones/{inst['id']}", headers=h)).status_code == 204
    finally:
        await _limpiar()


async def test_codigo_vencido_y_central_sin_clave(cliente, mundo, monkeypatch):
    from datetime import datetime, timedelta

    h = mundo.cabeceras_plataforma()
    await _limpiar()
    try:
        inst = (await cliente.post("/api/plataforma/instalaciones", headers=h,
                                   json={"empresa_id": mundo.beta.id, "nombre": "Bodega"})).json()
        async with async_session() as s:
            fila = await s.get(Instalacion, inst["id"])
            fila.codigo_vence = datetime.utcnow() - timedelta(minutes=1)
            await s.commit()
        assert (await cliente.post("/api/licencia/activar", json={"codigo": inst["codigo"]})).status_code == 410

        codigo = (await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/codigo", headers=h)).json()["codigo"]
        monkeypatch.setattr(settings, "licencia_clave_privada", "")
        assert (await cliente.get("/api/plataforma/instalaciones", headers=h)).json()["central_lista"] is False
        r = await cliente.post("/api/licencia/activar", json={"codigo": codigo})
        assert r.status_code == 503
    finally:
        await _limpiar()


async def test_una_instalacion_local_no_es_central(cliente, mundo, monkeypatch):
    monkeypatch.setattr(settings, "modo_instalacion", "local")
    assert (await cliente.post("/api/licencia/activar", json={"codigo": "NSPBX-AAAA-BBBB-CCCC"})).status_code == 404
    assert (await cliente.get("/api/plataforma/instalaciones", headers=mundo.cabeceras_plataforma())).status_code == 404
