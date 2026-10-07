"""Fase H: buzón desde otro teléfono con PIN, tope de inicio de sesión
compartido y el gasto de la calidad automática."""

import hashlib
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy import text, update

from app.core import permissions
from app.core.database import async_session
from app.models import Extension
from app.schemas.schemas import InboundRouteCreate
from app.services import config_generator

# --- H2: buzón desde otro teléfono ---------------------------------------------------------


def _ext(numero, pin=None, voicemail=True):
    return SimpleNamespace(number=numero, voicemail=voicemail, enabled=True, voicemail_pin=pin)


def _lua_de_96(extensiones, nuevos) -> str:
    ctx = ET.Element("context", name="ctx_a")
    config_generator._append_buzon_remoto(ctx, extensiones, nuevos, 7)
    ext = ctx.find("extension[@name='nspbx_buzon_remoto']")
    assert ext is not None
    luas = [a.get("data") for a in ext.iter("action") if a.get("application") == "lua"]
    return luas[0] if luas else ""


def test_el_dialplan_de_96_no_lleva_el_pin_en_claro():
    lua = _lua_de_96([_ext("101", "482913"), _ext("102"), _ext("103", "777123", voicemail=False)], {})
    assert lua.startswith("~")
    assert "482913" not in lua and "777123" not in lua
    assert "['101']" in lua and "['102']" not in lua and "['103']" not in lua
    sal = lua.split("api:execute('md5','")[1].split("'")[0]
    assert hashlib.md5(f"{sal}101:482913".encode()).hexdigest() in lua
    # La sal cambia en cada dialplan: la huella de ayer no sirve hoy.
    assert _lua_de_96([_ext("101", "482913")], {}) != _lua_de_96([_ext("101", "482913")], {})


def test_sin_pines_el_96_lo_dice_y_cuelga():
    assert _lua_de_96([_ext("101")], {}) == ""


def _correr_96(teclas: list[str], nuevos: dict) -> tuple[list[str], dict]:
    """Ejecuta el Lua de *96 con una sesión de FreeSWITCH simulada."""
    lupa = pytest.importorskip("lupa")
    codigo = _lua_de_96([_ext("101", "482913"), _ext("102", "905172")], nuevos)[1:]
    lua = lupa.LuaRuntime()
    oido, variables, cola = [], {}, list(teclas)

    class Sesion:
        def ready(self):
            return True

        def streamFile(self, f):
            oido.append(f)

        def execute(self, app, datos):
            oido.append(datos)

        def playAndGetDigits(self, *args):
            return cola.pop(0) if cola else ""

        def setVariable(self, k, v):
            variables[k] = v

        def sleep(self, ms):
            pass

    class Api:
        def execute(self, comando, datos):
            assert comando == "md5"
            return hashlib.md5(datos.encode()).hexdigest() + "\n"

    g = lua.globals()
    g.session = Sesion()
    g.freeswitch = lua.table(API=lambda: Api())
    lua.execute(codigo)
    return oido, variables


def test_96_con_el_pin_correcto_reproduce_y_marca_lo_oido():
    nuevos = {"101": [(5, "/rec/t7/buzon/101/a.wav"), (6, "/rec/t7/buzon/101/b.wav")]}
    oido, variables = _correr_96(["101", "482913"], nuevos)
    assert "/rec/t7/buzon/101/a.wav" in oido and "/rec/t7/buzon/101/b.wav" in oido
    assert variables == {"nspbx_buzon_oido": "6"}


def test_96_con_pin_ajeno_o_errado_no_reproduce_nada():
    nuevos = {"101": [(5, "/rec/t7/buzon/101/a.wav")]}
    # El PIN de la 102 no abre la 101; tres intentos y cuelga.
    oido, variables = _correr_96(["101", "905172", "101", "000000", "999", "482913", "101", "482913"], nuevos)
    assert "/rec/t7/buzon/101/a.wav" not in oido and variables == {}
    assert sum("Wrong extension or PIN" in o or "error" in o for o in oido) == 3


def test_ruta_entrante_para_escuchar_el_buzon():
    ruta = InboundRouteCreate(name="buzon", did_pattern="6015550001", destination_type="buzon_remoto")
    assert ruta.destination_value is None
    r = SimpleNamespace(id=4, name="buzon", tenant_id=7, did_pattern="6015550001", priority=0, enabled=True,
                        destination_type="buzon_remoto", destination_value=None, horario=None)
    publico = ET.Element("context", name="public")
    config_generator._append_inbound_routes(publico, [r], {7: "ctx_a"}, {7: "a.test"})
    transfer = publico.find(".//extension[@name='did_4_buzon']//action[@application='transfer']").get("data")
    assert transfer == "*96 XML ctx_a"


async def test_pin_del_buzon_desde_el_panel(cliente, mundo):
    from .conftest import FS_SECRET

    asesor = mundo.alfa.cabeceras(permissions.ASESOR)  # extensión 1000
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=True))
        await s.commit()
    try:
        r = await cliente.get("/api/buzon/pin", headers=asesor)
        assert r.json() == {"extension": "1000", "tiene_pin": False, "marcar": "*96"}
        for malo in ("12a4", "123", "1111", "4567", "9876", "1000"):
            assert (await cliente.put("/api/buzon/pin", headers=asesor, json={"pin": malo})).status_code == 422, malo
        # Solo la propia: la de otro ni se confirma.
        otra = await cliente.put("/api/buzon/pin", headers=asesor, json={"pin": "482913", "extension": "1001"})
        assert otra.status_code == 404
        r = await cliente.put("/api/buzon/pin", headers=asesor, json={"pin": "482913"})
        assert r.status_code == 200 and r.json()["tiene_pin"] is True
        assert "482913" not in r.text
        async with async_session() as s:
            crudo = (await s.execute(text(
                "SELECT voicemail_pin FROM extensions WHERE tenant_id = :t AND number = '1000'"), {"t": mundo.alfa.id}
            )).scalar_one()
        assert crudo and "482913" not in crudo  # cifrado en la base
        dialplan = (await cliente.get(f"/fs/dialplan?secret={FS_SECRET}")).text
        assert "nspbx_buzon_remoto" in dialplan and "482913" not in dialplan
        assert (await cliente.delete("/api/buzon/pin", headers=asesor)).status_code == 204
        assert (await cliente.get("/api/buzon/pin", headers=asesor)).json()["tiene_pin"] is False
    finally:
        async with async_session() as s:
            await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                            .values(voicemail=False, voicemail_pin=None))
            await s.commit()
