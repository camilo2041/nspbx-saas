"""I2: una llamada de una empresa nunca termina en recursos de otra.

Se pide el directorio y el dialplan a los mismos endpoints que consulta
FreeSWITCH y se revisa el XML. Las dos empresas tienen la extensión 1000,
la cola 5000 y una troncal "principal": si algo se cruzara, sería acá.
"""

import re
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import text

from app.core import validacion
from app.core.database import engine

from .conftest import FS_SECRET


async def _xml(cliente, ruta: str) -> ET.Element:
    resp = await cliente.get(ruta, params={"secret": FS_SECRET})
    assert resp.status_code == 200, resp.text[:300]
    return ET.fromstring(resp.text)


def _acciones(contexto: ET.Element) -> list[str]:
    return [
        f"{a.get('application')} {a.get('data') or ''}"
        for a in contexto.iter("action")
    ]


@pytest.mark.parametrize("ruta", ["/fs/directory", "/fs/dialplan"])
async def test_endpoints_de_freeswitch_exigen_el_secreto(cliente, mundo, ruta):
    assert (await cliente.get(ruta)).status_code == 403
    assert (await cliente.get(ruta, params={"secret": "otro"})).status_code == 403


async def test_cdr_exige_el_secreto(cliente, mundo):
    resp = await cliente.post("/fs/cdr/otro", json={})
    assert resp.status_code == 403


async def test_directorio_cada_dominio_solo_con_sus_extensiones(cliente, mundo):
    raiz = await _xml(cliente, "/fs/directory")
    for propia, ajena in ((mundo.alfa, mundo.beta), (mundo.beta, mundo.alfa)):
        dominio = raiz.find(f".//domain[@name='{propia.dominio}']")
        assert dominio is not None, f"falta el dominio {propia.dominio}"
        usuarios = sorted(u.get("id") for u in dominio.findall(".//user"))
        # Exactamente las extensiones habilitadas de esa empresa en la base
        # (otras pruebas le agregan algunas).
        async with engine.connect() as conn:
            esperadas = sorted(
                (await conn.execute(
                    text("SELECT number FROM extensions WHERE tenant_id = :t AND enabled"), {"t": propia.id}
                )).scalars().all()
            )
        assert usuarios == esperadas and "1000" in usuarios
        texto = ET.tostring(dominio, encoding="unicode")
        assert f"clave-sip-{propia.marca}" in texto
        assert ajena.marca not in texto, f"el dominio de {propia.slug} contiene datos de {ajena.slug}"
        contexto = dominio.find(".//variable[@name='user_context']").get("value")
        assert contexto == f"ctx_{propia.slug}"


async def test_contexto_de_cada_empresa_no_menciona_a_la_otra(cliente, mundo):
    raiz = await _xml(cliente, "/fs/dialplan")
    for propia, ajena in ((mundo.alfa, mundo.beta), (mundo.beta, mundo.alfa)):
        ctx = raiz.find(f".//context[@name='ctx_{propia.slug}']")
        assert ctx is not None
        acciones = _acciones(ctx)
        assert acciones, "contexto vacío"
        for accion in acciones:
            for prohibido in (ajena.dominio, f"ctx_{ajena.slug}", f"gateway/{ajena.slug}_", ajena.marca):
                assert prohibido not in accion, f"ctx_{propia.slug} → {accion!r} apunta a {ajena.slug}"


async def test_puentes_y_colas_quedan_dentro_de_la_empresa(cliente, mundo):
    """Control positivo de lo anterior: los destinos SÍ existen y son los
    propios (si el contexto no puenteara a nada, la prueba de arriba
    pasaría igual)."""
    raiz = await _xml(cliente, "/fs/dialplan")
    for e in (mundo.alfa, mundo.beta):
        acciones = _acciones(raiz.find(f".//context[@name='ctx_{e.slug}']"))
        assert f"bridge user/${{destination_number}}@{e.dominio}" in acciones
        assert f"callcenter soporte@{e.dominio}" in acciones
        assert any(a.startswith(f"bridge sofia/gateway/{e.slug}_principal/") for a in acciones)


async def test_entrantes_cada_did_va_al_contexto_de_su_empresa(cliente, mundo):
    raiz = await _xml(cliente, "/fs/dialplan")
    public = raiz.find(".//context[@name='public']")
    destinos = {}
    for ext in public.findall("extension"):
        cond = ext.find("condition[@field='destination_number']")
        transfer = ext.find(".//action[@application='transfer']")
        if cond is None or transfer is None:
            continue
        destinos[cond.get("expression")] = (
            transfer.get("data"),
            ext.find(".//action[@application='set']").get("data"),
        )
    for e in (mundo.alfa, mundo.beta):
        did = validacion.expresion_did(f"{e.telefono}00")
        assert did in destinos, f"falta el DID de {e.slug}"
        transfer, dominio = destinos[did]
        assert transfer.endswith(f"XML ctx_{e.slug}")
        assert dominio == f"domain_name={e.dominio}"


async def test_entrantes_un_did_sin_duenio_se_rechaza(cliente, mundo):
    """Lo último del contexto público tiene que colgar, no caer en el
    contexto de alguna empresa."""
    raiz = await _xml(cliente, "/fs/dialplan")
    ultima = raiz.find(".//context[@name='public']").findall("extension")[-1]
    acciones = _acciones(ultima)
    assert acciones == ["set nspbx_sin_ruta=1", "hangup UNALLOCATED_NUMBER"]


async def test_salientes_sin_permiso_internacional_no_dejan_salir_00_ni_011(cliente, mundo):
    """El filtro mínimo de I5 en la regla configurada de cada empresa.
    Los casos con prefijos de acceso (9 + 00…) son de la fase 1."""
    raiz = await _xml(cliente, "/fs/dialplan")
    for e in (mundo.alfa, mundo.beta):
        ctx = raiz.find(f".//context[@name='ctx_{e.slug}']")
        expresiones = [
            ext.find("condition[@field='destination_number']").get("expression")
            for ext in ctx.findall("extension")
            if any((a.get("data") or "").startswith("sofia/gateway/") for a in ext.iter("action"))
        ]
        assert expresiones, f"{e.slug} no tiene ruta saliente"
        for expresion in expresiones:
            for internacional in ("0044770090012", "01144770090012", "+447700900123", "3001234567890123"):
                assert not re.match(expresion, internacional), f"{expresion} deja salir {internacional}"
            assert re.match(expresion, "3001234567"), f"{expresion} no deja salir un celular nacional"


async def test_fuera_del_horario_la_llamada_va_a_otro_destino(cliente, mundo, monkeypatch):
    """Número entrante con horario de atención: dentro va a su destino;
    fuera, al de «fuera de horario» (vacío = colgar)."""
    from datetime import datetime

    from app.core import clock

    cab = mundo.alfa.cabeceras()
    r = await cliente.post("/api/inbound-routes", headers=cab, json={
        "name": "horario", "did_pattern": "6019990000", "destination_type": "extension", "destination_value": "1000",
        "horario": '{"mon": ["08:00", "18:00"]}', "fuera_horario_tipo": "queue", "fuera_horario_valor": "5000",
    })
    assert r.status_code == 201, r.text

    def acciones_del_did(raiz):
        ext = next(e for e in raiz.find(".//context[@name='public']").findall("extension") if e.get("name", "").startswith(f"did_{r.json()['id']}_"))
        return [(a.get("application"), a.get("data")) for a in ext.iter("action")]

    lunes_10 = datetime(2026, 10, 5, 10, 0)  # lunes
    monkeypatch.setattr(clock, "now_local", lambda: lunes_10)
    assert ("transfer", f"1000 XML ctx_{mundo.alfa.slug}") in acciones_del_did(await _xml(cliente, "/fs/dialplan"))
    monkeypatch.setattr(clock, "now_local", lambda: lunes_10.replace(hour=20))
    assert ("transfer", f"5000 XML ctx_{mundo.alfa.slug}") in acciones_del_did(await _xml(cliente, "/fs/dialplan"))

    # Horario mal escrito: se rechaza.
    r2 = await cliente.put(f"/api/inbound-routes/{r.json()['id']}", headers=cab, json={"horario": '{"mon": ["18:00", "08:00"]}'})
    assert r2.status_code == 422
