"""Fase 7: mensajes entre réplicas (services/bus.py, LISTEN/NOTIFY).

Dos buses contra la misma base hacen de dos réplicas. Lo que publica una le
llega a la otra (y no a sí misma), en orden; un mensaje demasiado grande se
descarta sin romper nada; y los tres usos reales funcionan: el tablero en
vivo (con la foto inicial de las llamadas), los permisos y el predictivo.
"""

import asyncio

import pytest

from app.services import bus as bus_mod, predictivo
from app.services.tiempo_real import TiempoReal


async def _esperar(cond, segundos=3.0):
    fin = asyncio.get_running_loop().time() + segundos
    while not cond():
        if asyncio.get_running_loop().time() > fin:
            return False
        await asyncio.sleep(0.02)
    return True


@pytest.fixture
async def replicas():
    a, b = bus_mod.Bus(), bus_mod.Bus()
    await a.start()
    await b.start()
    yield a, b
    await a.stop()
    await b.stop()


async def test_llega_a_la_otra_replica_en_orden_y_no_a_si_misma(replicas):
    a, b = replicas
    en_a, en_b = [], []
    a.registrar("x", en_a.append)
    b.registrar("x", en_b.append)
    for i in range(20):
        a.emitir_pronto("x", {"i": i})
    assert await _esperar(lambda: len(en_b) == 20)
    assert [m["i"] for m in en_b] == list(range(20))
    await asyncio.sleep(0.1)
    assert en_a == []


async def test_mensaje_demasiado_grande_se_descarta(replicas):
    a, b = replicas
    en_b = []
    b.registrar("x", en_b.append)
    a.emitir_pronto("x", {"relleno": "x" * 9000})
    a.emitir_pronto("x", {"ok": True})
    assert await _esperar(lambda: en_b == [{"ok": True}])


async def test_el_tablero_en_vivo_se_ve_desde_cualquier_replica(replicas, monkeypatch):
    a, b = replicas
    lider, otra = TiempoReal(), TiempoReal()
    monkeypatch.setattr(bus_mod, "bus", a)  # la líder publica por su bus
    b.registrar("tr", otra.desde_otra_replica)
    cola = otra.suscribir(77)
    lider.publicar(77, {"tipo": "llamada", "evento": "contesta", "llamada": {
        "uuid": "u-1", "estado": "hablando", "timbre_at": 10.0, "contesta_at": 14.0, "a": "3001"}})
    assert await _esperar(lambda: not cola.empty())
    assert (await cola.get())["llamada"]["uuid"] == "u-1"
    # Quien se conecta a la otra réplica ve la llamada en la foto inicial.
    foto = otra.llamadas(77)
    assert foto[0]["uuid"] == "u-1" and foto[0]["ring_ms"] == 4000
    assert otra.llamadas(78) == []  # y solo la de su empresa
    lider.publicar(77, {"tipo": "llamada", "evento": "cuelga", "llamada": {"uuid": "u-1", "estado": "colgada"}})
    assert await _esperar(lambda: otra.llamadas(77) == [])


async def test_foto_del_predictivo_en_otra_replica(monkeypatch):
    predictivo._fotos.clear()
    predictivo._foto_de_otra_replica({"tenant": 5, "campanas": {"901": {"timbrando": 7, "en_espera": 1, "ultimos_15": {}}}})
    assert predictivo.instantanea(901)["timbrando"] == 7
    # Vieja: no se usa.
    predictivo._fotos[901] = (predictivo._fotos[901][0] - predictivo.VIGENCIA_FOTO_S - 1, predictivo._fotos[901][1])
    assert predictivo.instantanea(901)["timbrando"] == 0
    predictivo._fotos.clear()


async def test_permisos_se_releen_al_avisar(monkeypatch):
    from app.api import role_permissions

    llamadas = []

    async def recargar(_s):
        llamadas.append(1)

    monkeypatch.setattr(role_permissions, "recargar_cache", recargar)
    await role_permissions._desde_otra_replica({})
    assert llamadas == [1]
