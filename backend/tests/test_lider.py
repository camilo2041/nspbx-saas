"""Fase 7: un solo líder entre réplicas (services/lider.py).

Dos réplicas contra la misma base: solo una marca y procesa eventos. Si la
líder se apaga o pierde la base, la otra toma el relevo en su siguiente
vuelta, y la que la perdió deja de trabajar en el acto.
"""

import pytest

from app.services.lider import Lider


class Registro:
    def __init__(self):
        self.eventos: list[str] = []

    def replica(self, nombre: str) -> Lider:
        async def sube():
            self.eventos.append(f"{nombre}+")

        async def baja():
            self.eventos.append(f"{nombre}-")

        return Lider(al_ascender=sube, al_descender=baja)


@pytest.fixture
async def dos():
    r = Registro()
    a, b = r.replica("a"), r.replica("b")
    yield r, a, b
    await a.stop()
    await b.stop()


async def test_solo_una_es_lider_y_el_relevo_al_apagar(dos):
    r, a, b = dos
    assert await a.intentar() is True
    assert await b.intentar() is False
    assert await a.intentar() is True  # sigue siéndolo
    assert (a.es_lider, b.es_lider) == (True, False)
    await a.stop()  # apagado ordenado: suelta el candado
    assert await b.intentar() is True
    assert r.eventos == ["a+", "a-", "b+"]


async def test_si_pierde_la_base_deja_de_trabajar_y_otra_toma_el_relevo(dos):
    r, a, b = dos
    assert await a.intentar()
    a._conexion.terminate()  # la conexión de la líder se corta
    assert await a.intentar() is False
    assert not a.es_lider and r.eventos == ["a+", "a-"]
    # Postgres soltó el candado con la conexión: la otra lo toma.
    assert await b.intentar() is True
    assert r.eventos[-1] == "b+"
    # La primera vuelve, pero ya no es líder.
    assert await a.intentar() is False


async def test_un_error_al_arrancar_queda_en_el_log_y_sigue_siendo_lider():
    async def falla():
        raise RuntimeError("no arrancó")

    a = Lider(al_ascender=falla)
    try:
        assert await a.intentar() is True  # sigue siendo líder: el resto de sus tareas sí corre
    finally:
        await a.stop()
