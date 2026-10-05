"""La plataforma bloquea un país o prefijo internacional para todas las
empresas, aunque una lo tenga entre sus países permitidos (además de los
fijos: satelitales y tarifas premium)."""

import itertools
import re

import pytest

from app.core.database import async_session
from app.services import salientes
from app.services.salientes import Politica, motivo_bloqueo, prefijos_desde_texto, restriccion_regex

_CUBA_PERMITIDA_Y_BLOQUEADA = Politica(permitir_internacional=True, paises=("57", "53", "1"), bloqueados_plataforma=("53", "1876"))


def test_el_bloqueo_de_la_plataforma_gana_al_pais_permitido():
    assert "plataforma" in motivo_bloqueo("+5371234567", _CUBA_PERMITIDA_Y_BLOQUEADA)
    assert "plataforma" in motivo_bloqueo("0018765551234", _CUBA_PERMITIDA_Y_BLOQUEADA)  # Jamaica dentro del +1
    assert motivo_bloqueo("+12125551234", _CUBA_PERMITIDA_Y_BLOQUEADA) is None  # el resto del +1 sigue
    assert motivo_bloqueo("00573001234567", _CUBA_PERMITIDA_Y_BLOQUEADA) is None
    assert motivo_bloqueo("3001234567", _CUBA_PERMITIDA_Y_BLOQUEADA) is None  # nacional, intacto


def test_dialplan_y_python_deciden_igual():
    antepuestos = ["", "00", "+", "57"]
    marcados = ["5371234567", "+5371234567", "005371234567", "18765551234", "+18765551234", "12125551234",
                "+12125551234", "573001234567", "3001234567", "+5731234567"]
    diferencias = []
    for antepuesto, marcado in itertools.product(antepuestos, marcados):
        python = motivo_bloqueo(antepuesto + marcado, _CUBA_PERMITIDA_Y_BLOQUEADA) is None
        restriccion = restriccion_regex(_CUBA_PERMITIDA_Y_BLOQUEADA, antepuesto)
        dialplan = restriccion is not None and re.match(r"^(" + restriccion + r".+)$", marcado) is not None
        if python != dialplan:
            diferencias.append((antepuesto, marcado, python, dialplan))
    assert not diferencias, diferencias


def test_prefijos_desde_texto():
    assert prefijos_desde_texto("+53, 7 ;2346, 53") == ("53", "7", "2346")
    assert prefijos_desde_texto("") == ()
    for malo in ("053", "1234567", "abc", "5-3"):
        with pytest.raises(ValueError):
            prefijos_desde_texto(malo)


async def test_la_plataforma_lo_configura_y_aplica_a_todas(cliente, mundo):
    plataforma = mundo.cabeceras_plataforma()
    try:
        r = await cliente.put("/api/plataforma/destinos-bloqueados", json={"prefijos": "+53, 7"}, headers=plataforma)
        assert r.status_code == 200, r.text
        assert r.json()["prefijos"] == "53,7" and "870" in r.json()["fijos"]
        assert (await cliente.get("/api/plataforma/destinos-bloqueados", headers=plataforma)).json()["prefijos"] == "53,7"

        async with async_session() as s:
            politicas = await salientes.politicas(s, [mundo.alfa.id, mundo.beta.id])
        assert all(p.bloqueados_plataforma == ("53", "7") for p in politicas.values())

        malo = await cliente.put("/api/plataforma/destinos-bloqueados", json={"prefijos": "53, 0xx"}, headers=plataforma)
        assert malo.status_code == 422 and "0xx" in malo.text
    finally:
        await cliente.put("/api/plataforma/destinos-bloqueados", json={"prefijos": ""}, headers=plataforma)
