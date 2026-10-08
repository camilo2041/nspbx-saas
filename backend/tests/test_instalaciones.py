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
        assert act["descarga"]["registro"] and "version" in act["descarga"]
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


# --- El lado de la instalación local --------------------------------------------------

from datetime import datetime as _dt, timedelta as _td  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.models import License, LicenciaLocal, Tenant  # noqa: E402
from app.services import licencia_local, licensing  # noqa: E402


def _doc(instalacion_id=7, status="active", plan="pro", emitida=None, valida_h=72, expira_dias=30, **topes):
    emitida = emitida or _dt.utcnow().replace(microsecond=0)
    return {
        "version": 1, "instalacion_id": instalacion_id,
        "empresa": {"nombre": "Clínica Local", "slug": "clinica", "business_type": "clinica", "modules": ["pbx"]},
        "licencia": {"plan": plan, "status": status,
                     "expires_at": (emitida + _td(days=expira_dias)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     **{r: topes.get(r) for r in lf.RECURSOS}},
        "emitida": emitida.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valida_hasta": (emitida + _td(hours=valida_h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@pytest.fixture
async def modo_local(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "modo_instalacion", "local")
    monkeypatch.setattr(settings, "licencia_clave_publica", _PUBLICA)
    monkeypatch.setattr(settings, "central_url", "https://central.test")
    monkeypatch.setattr(licencia_local, "ARCHIVO_INSTALADOR", tmp_path / "licencia.json")
    async with async_session() as s:
        t = await s.get(Tenant, 1)
        antes = (t.name, t.business_type, t.modules, t.sip_domain)
        lic = (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one_or_none()
        lic_antes = None if lic is None else {c: getattr(lic, c) for c in ("plan", "status", "expires_at", *lf.RECURSOS)}
    yield tmp_path / "licencia.json"
    async with async_session() as s:
        await s.execute(delete(LicenciaLocal))
        t = await s.get(Tenant, 1)
        t.name, t.business_type, t.modules, t.sip_domain = antes
        lic = (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one_or_none()
        if lic_antes is None and lic is not None:
            await s.delete(lic)
        elif lic_antes is not None:
            for c, v in lic_antes.items():
                setattr(lic, c, v)
        await s.commit()


async def _licencia_1():
    async with async_session() as s:
        return (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one()


async def test_sin_activar_no_opera(modo_local):
    await licencia_local.al_arrancar()
    assert licensing.estado(await _licencia_1()) == "suspendida"


async def test_importa_la_licencia_del_instalador(modo_local, monkeypatch):
    monkeypatch.setattr(settings, "dominio_local", "pbx.clinica.test")
    firmada = lf.firmar(_doc(max_extensions=25), _PRIVADA)
    modo_local.write_text(json.dumps({"instalacion_id": 7, "token": "tok-1", **firmada}))
    await licencia_local.al_arrancar()
    async with async_session() as s:
        t = await s.get(Tenant, 1)
        assert (t.name, t.business_type, t.modules_list, t.sip_domain) == ("Clínica Local", "clinica", ["pbx"], "pbx.clinica.test")
    lic = await _licencia_1()
    assert lic.plan == "pro" and lic.status == "active" and licensing.estado(lic) == "ok"
    assert licensing.limite(lic, "max_extensions") == 25
    # El vencimiento efectivo es el de la gracia (72 h), no el comercial (30 días).
    assert lic.expires_at < lf.de_utc_iso(json.loads(firmada["documento"])["licencia"]["expires_at"])


async def test_un_archivo_alterado_no_se_importa(modo_local):
    firmada = lf.firmar(_doc(), _PRIVADA)
    firmada["documento"] = firmada["documento"].replace('"plan":"pro"', '"plan":"enterprise"')
    modo_local.write_text(json.dumps({"instalacion_id": 7, "token": "tok-1", **firmada}))
    await licencia_local.al_arrancar()
    assert licensing.estado(await _licencia_1()) == "suspendida"


async def test_latido_aplica_lo_nuevo_y_sin_central_reaplica_lo_guardado(modo_local):
    async with async_session() as s:
        await licencia_local.aplicar(s, **lf.firmar(_doc(), _PRIVADA), token="tok-1")

    pedidos = []

    def central(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, json=lf.firmar(_doc(status="suspended", emitida=_dt.utcnow().replace(microsecond=0) + _td(seconds=5)), _PRIVADA))

    async with httpx.AsyncClient(transport=httpx.MockTransport(central)) as c:
        assert await licencia_local.latir(c) is True
    assert pedidos[0].url == "https://central.test/api/licencia/latido"
    assert pedidos[0].headers["Authorization"] == "Bearer tok-1"
    uso = json.loads(pedidos[0].content)["uso"]
    assert {"extensiones", "usuarios", "minutos_salientes_mes"} <= set(uso) and all(isinstance(v, int) for v in uso.values())
    assert licensing.estado(await _licencia_1()) == "suspendida"

    # Alguien la reactiva a mano en la base; la central no responde: se
    # vuelve a aplicar la guardada y queda anotado por qué.
    async with async_session() as s:
        lic = (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one()
        lic.status, lic.max_extensions = "active", 9999
        await s.commit()

    def caida(request):
        raise httpx.ConnectError("sin ruta")

    async with httpx.AsyncClient(transport=httpx.MockTransport(caida)) as c:
        assert await licencia_local.latir(c) is False
    lic = await _licencia_1()
    assert lic.status == "suspended" and lic.max_extensions is None
    async with async_session() as s:
        estado = await licencia_local.estado(s)
    assert estado["estado"] == "suspended" and "Sin conexión" in estado["ultimo_error"]


async def test_respuesta_vieja_u_otra_firma_no_pisan(modo_local):
    ahora = _dt.utcnow().replace(microsecond=0)
    async with async_session() as s:
        await licencia_local.aplicar(s, **lf.firmar(_doc(status="suspended", emitida=ahora), _PRIVADA), token="tok-1")
        with pytest.raises(lf.LicenciaInvalida):
            await licencia_local.aplicar(s, **lf.firmar(_doc(emitida=ahora - _td(hours=1)), _PRIVADA))
        with pytest.raises(lf.LicenciaInvalida):
            await licencia_local.aplicar(s, **lf.firmar(_doc(), lf.generar_par()[0]))
        with pytest.raises(lf.LicenciaInvalida):
            await licencia_local.aplicar(s, **lf.firmar(_doc(instalacion_id=8, emitida=ahora + _td(seconds=1)), _PRIVADA))
    assert licensing.estado(await _licencia_1()) == "suspendida"


async def test_sin_latidos_vence_al_pasar_la_gracia(modo_local):
    vieja = _dt.utcnow().replace(microsecond=0) - _td(hours=80)
    async with async_session() as s:
        await licencia_local.aplicar(s, **lf.firmar(_doc(emitida=vieja), _PRIVADA), token="tok-1")
    assert licensing.estado(await _licencia_1()) == "vencida"


async def test_el_panel_local_ve_su_licencia_y_no_administra_empresas(cliente, mundo, modo_local):
    async with async_session() as s:
        await licencia_local.aplicar(s, **lf.firmar(_doc(), _PRIVADA), token="tok-1")
    r = await cliente.get("/api/instalacion/licencia", headers=mundo.alfa.cabeceras("asesor"))
    assert r.status_code == 200
    datos = r.json()
    assert datos["modo"] == "local" and datos["plan"] == "pro" and datos["empresa"] == "Clínica Local"
    assert "token" not in json.dumps(datos)
    h = mundo.cabeceras_plataforma()
    assert (await cliente.get("/api/tenants", headers=h)).status_code == 403
    assert (await cliente.get("/api/plataforma/nodos", headers=h)).status_code == 403


async def test_en_la_nube_el_panel_lo_dice(cliente, mundo):
    r = await cliente.get("/api/instalacion/licencia", headers=mundo.alfa.cabeceras())
    assert r.json() == {"modo": "nube"}


def test_el_arranque_revisa_la_configuracion_local():
    from app.core.arranque import problemas_de_configuracion
    from app.core.config import Settings

    base = dict(database_url="postgresql+asyncpg://a@h/x", database_url_app="postgresql+asyncpg://b@h/x", fs_xml_secret="s")
    assert not [p for p in problemas_de_configuracion(Settings(**base), "x" * 40) if "LICENCIA" in p or "CENTRAL" in p]
    problemas = problemas_de_configuracion(Settings(**base, modo_instalacion="local"), "x" * 40)
    assert any("LICENCIA_CLAVE_PUBLICA" in p for p in problemas) and any("CENTRAL_URL" in p for p in problemas)
    assert not [p for p in problemas_de_configuracion(
        Settings(**base, modo_instalacion="local", licencia_clave_publica=_PUBLICA, central_url="https://c.test"), "x" * 40)
        if "LICENCIA" in p or "CENTRAL" in p]
    assert any("MODO_INSTALACION" in p for p in problemas_de_configuracion(Settings(**base, modo_instalacion="otro"), "x" * 40))
    assert any("Ed25519" in p for p in problemas_de_configuracion(Settings(**base, licencia_clave_privada="mala"), "x" * 40))


async def test_la_central_sirve_el_instalador_con_su_direccion(cliente):
    r = await cliente.get("/api/licencia/instalar.sh", headers={"X-Forwarded-Host": "pbx.central.test"})
    assert r.status_code == 200 and r.text.startswith("#!/usr/bin/env bash")
    assert 'CENTRAL="${NSPBX_CENTRAL:-https://pbx.central.test}"' in r.text and "__CENTRAL__" not in r.text
    assert (await cliente.get("/api/licencia/instalar.sh", headers={"X-Forwarded-Host": "x;rm -rf /"})).status_code == 400
