"""I5: nadie llama a destinos que la empresa no autorizó.

La política vive en services/salientes.py y se aplica de dos formas: en
Python (clic-para-llamar, campañas) y traducida al dialplan. Lo más
importante de este archivo es `test_dialplan_y_python_deciden_igual`: si
las dos formas no coinciden, una de las puertas queda abierta.
"""

import itertools
import re

import pytest

from app.core import validacion
from app.services.salientes import (
    CODIGOS_BLOQUEADOS,
    Politica,
    motivo_bloqueo,
    paises_desde_texto,
    restriccion_regex,
)

_NACIONAL = Politica()
_SOLO_EEUU = Politica(permitir_internacional=True, paises=("1",))
_COLOMBIA_Y_ESPANA = Politica(permitir_internacional=True, paises=("57", "34"))
_SIN_PAISES = Politica(permitir_internacional=True, paises=())
_CORTADAS = Politica(permitir_internacional=True, paises=("57",), bloqueo="Salientes suspendidas")


@pytest.mark.parametrize(
    "numero",
    ["3001234567", "6012345678", "123", "018000123456"[:10], "*78", "0312345"],
)
def test_nacionales_salen_sin_permiso_internacional(numero):
    assert motivo_bloqueo(numero, _NACIONAL) is None


@pytest.mark.parametrize(
    "numero",
    [
        "0044770090012",  # 00
        "01144770090012",  # 011
        "+447700900123",  # +
        "00944770090012",  # operador de larga distancia colombiano (009)
        "447700900123",  # más de 10 dígitos sin prefijo
        "30012345678",  # 11 dígitos
    ],
)
def test_internacionales_bloqueados_sin_permiso(numero):
    assert motivo_bloqueo(numero, _NACIONAL)


@pytest.mark.parametrize("codigo", CODIGOS_BLOQUEADOS)
@pytest.mark.parametrize("prefijo", ["00", "011", "+"])
def test_premium_y_satelital_bloqueados_aunque_haya_permiso(codigo, prefijo):
    politica = Politica(permitir_internacional=True, paises=("1", "8", "9", "87", "88", "97", "80"))
    assert "bloqueado siempre" in motivo_bloqueo(f"{prefijo}{codigo}1234567", politica)


def test_con_permiso_solo_salen_los_paises_elegidos():
    assert motivo_bloqueo("+573001234567", _COLOMBIA_Y_ESPANA) is None
    assert motivo_bloqueo("0034912345678", _COLOMBIA_Y_ESPANA) is None
    assert "país" in motivo_bloqueo("+447700900123", _COLOMBIA_Y_ESPANA)


def test_internacional_activado_sin_paises_no_deja_salir_ninguno():
    assert motivo_bloqueo("+573001234567", _SIN_PAISES)


def test_salientes_cortadas_bloquean_todo():
    assert motivo_bloqueo("3001234567", _CORTADAS) == "Salientes suspendidas"
    assert restriccion_regex(_CORTADAS) is None


@pytest.mark.parametrize("numero", ["", "abc", "300-123-4567x", "+", "00+44", "++44"])
def test_numeros_invalidos(numero):
    assert motivo_bloqueo(numero, _COLOMBIA_Y_ESPANA)


def test_separadores_no_esquivan_la_politica():
    assert motivo_bloqueo("00 44 7700 900123", _NACIONAL)
    assert motivo_bloqueo("(+44) 7700-900-123", _NACIONAL)
    assert motivo_bloqueo("300 123 4567", _NACIONAL) is None


def test_paises_desde_texto():
    assert paises_desde_texto(" 57, +1;34,,abc, 57, 0, 12345") == ("57", "1", "34")
    assert paises_desde_texto(None) == ()


# --- Python y dialplan tienen que decidir igual ---------------------------

_POLITICAS = [_NACIONAL, _SOLO_EEUU, _COLOMBIA_Y_ESPANA, _SIN_PAISES]
_ANTEPUESTOS = ["", "0", "00", "01", "011", "+", "9", "57", "1", "005", "0057", "+57", "123456789", "1234567890", "88"]
_MARCADOS = [
    "3001234567", "123", "30012345678", "0044770090012", "01144770090012", "+447700900123",
    "+573001234567", "573001234567", "0573001234567", "00573001234567", "0011234567890",
    "11234567890", "1900555123", "0019005551234", "+19005551234", "008811234567", "8811234567",
    "88112345", "0", "00", "+", "*78", "#1", "9004477", "34912345678", "0034912345678",
    "1", "12", "5", "7", "0+44", "00+44",
]


def _sale_por_el_dialplan(politica, antepuesto, marcado) -> bool:
    restriccion = restriccion_regex(politica, antepuesto)
    if restriccion is None:
        return False
    # Ruta "acepta todo" (patrón "."), para aislar lo que decide la política.
    return re.match(r"^(" + restriccion + r".+)$", marcado) is not None


@pytest.mark.parametrize("politica", _POLITICAS, ids=["nacional", "solo_eeuu", "co_es", "sin_paises"])
def test_dialplan_y_python_deciden_igual(politica):
    diferencias = []
    for antepuesto, marcado in itertools.product(_ANTEPUESTOS, _MARCADOS):
        python = motivo_bloqueo(antepuesto + marcado, politica) is None
        dialplan = _sale_por_el_dialplan(politica, antepuesto, marcado)
        if python != dialplan:
            diferencias.append((antepuesto, marcado, f"python={python}", f"dialplan={dialplan}"))
    assert not diferencias, diferencias[:20]


@pytest.mark.parametrize(
    "patron,quitar,antepuesto,marcado,sale",
    [
        # El caso que encontró la fase 0: "9." quitando el 9 dejaba salir 00…
        ("9.", 1, "", "900447700900123", False),
        ("9.", 1, "", "93001234567", True),
        # Patrón abierto: el "+" ya no esquiva el filtro.
        (".", 0, "", "+447700900123", False),
        ("X.", 0, "", "447700900123", False),
        # Antepuesto que completa un prefijo internacional.
        ("X.", 0, "0", "0447700900123", False),
        ("3XXXXXXXXX", 0, "", "3001234567", True),
    ],
)
def test_reglas_reales_del_dialplan_sin_internacional(patron, quitar, antepuesto, marcado, sale):
    expresion = validacion.patron_marcado_a_regex(patron, quitar)
    restriccion = restriccion_regex(_NACIONAL, antepuesto)
    expresion = expresion.replace("(", "(" + restriccion, 1)
    assert (re.match(expresion, marcado) is not None) is sale
