"""Colas: las extensiones agregadas a una cola reciben llamadas sin reiniciar
FreeSWITCH.

mod_callcenter lee los agentes y tiers del XML solo al arrancar el módulo;
`queue reload` relee únicamente los parámetros de la cola. Antes, una
extensión agregada desde el panel no existía para FreeSWITCH y las llamadas
seguían entrando solo a la que ya estaba. Acá un mod_callcenter simulado
lleva la cuenta de agentes y tiers como el real.
"""

from types import SimpleNamespace

import pytest

from app.services import esl, queues_sync

DOMINIO = "alfa.pbx.test"
COLA = f"ventas@{DOMINIO}"


class CallcenterFalso:
    def __init__(self, colas_cargadas=(), agentes=(), tiers=()):
        self.colas = set(colas_cargadas)
        self.agentes: dict[str, dict] = {a: {} for a in agentes}
        self.tiers: set[tuple[str, str]] = set(tiers)
        self.comandos: list[str] = []

    async def api(self, cmd, tenant_id=None, nodo=None):
        self.comandos.append(cmd)
        p = cmd.split()
        assert p[0] == "callcenter_config", cmd
        if p[1:3] == ["queue", "reload"]:
            return "+OK" if p[3] in self.colas else "-ERR Invalid Queue not found!"
        if p[1:3] == ["queue", "load"]:
            self.colas.add(p[3])
            return "+OK"
        if p[1:3] == ["queue", "unload"]:
            self.colas.discard(p[3])
            return "+OK"
        if p[1:4] == ["queue", "list", "tiers"]:
            filas = [f"{q}|{a}|Ready|1|1" for q, a in sorted(self.tiers) if q == p[4]]
            return "\n".join(["queue|agent|state|level|position", *filas, "+OK"])
        if p[1:3] == ["agent", "add"]:
            if p[3] in self.agentes:
                return "-ERR Agent already exist!"
            self.agentes[p[3]] = {}
            return "+OK"
        if p[1:3] == ["agent", "set"]:
            if p[4] not in self.agentes:
                return "-ERR Invalid Agent!"
            self.agentes[p[4]][p[3]] = p[5]
            return "+OK"
        if p[1:3] == ["tier", "add"]:
            # El real exige que la cola esté cargada y el agente exista.
            if p[3] not in self.colas or p[4] not in self.agentes:
                return "-ERR"
            self.tiers.add((p[3], p[4]))
            return "+OK"
        if p[1:3] == ["tier", "del"]:
            self.tiers.discard((p[3], p[4]))
            return "+OK"
        return "-ERR comando no simulado"

    def reciben_llamadas(self, cola):
        return {a for q, a in self.tiers if q == cola and self.agentes.get(a, {}).get("status", "Available") == "Available"}


def _cola(agentes, **kw):
    datos = dict(id=1, tenant_id=7, name="ventas", enabled=True, agents=str(agentes).replace("'", '"'),
                 agent_ring_timeout=20, max_no_answer=3, wrap_up_time=5, strategy="ring-all",
                 moh_sound="local_stream://moh", max_wait_time=0, max_wait_time_with_no_agent=0, record=False)
    datos.update(kw)
    return SimpleNamespace(**datos)


@pytest.fixture
def cc(monkeypatch):
    # FreeSWITCH arrancó con la cola y solo la extensión 101.
    falso = CallcenterFalso(colas_cargadas=[COLA], agentes=[f"101@{DOMINIO}"], tiers=[(COLA, f"101@{DOMINIO}")])
    monkeypatch.setattr(esl, "api", falso.api)
    return falso


async def test_extensiones_nuevas_reciben_llamadas_sin_reiniciar(cc):
    await queues_sync.sync_queue(_cola(["101", "102", "103"]), DOMINIO)
    assert cc.reciben_llamadas(COLA) == {f"{e}@{DOMINIO}" for e in ("101", "102", "103")}
    nuevo = cc.agentes[f"102@{DOMINIO}"]
    assert nuevo["contact"] == f"[leg_timeout=20]user/102@{DOMINIO}"
    assert (nuevo["max_no_answer"], nuevo["wrap_up_time"]) == ("3", "5")
    # Al 101, que ya estaba, no se le duplica el tier.
    assert sum(c == f"callcenter_config tier add {COLA} 101@{DOMINIO} 1 1" for c in cc.comandos) == 0


async def test_quitar_una_extension_la_saca_de_la_cola(cc):
    await queues_sync.sync_queue(_cola(["101", "102"]), DOMINIO)
    await queues_sync.sync_queue(_cola(["102"]), DOMINIO)
    assert cc.reciben_llamadas(COLA) == {f"102@{DOMINIO}"}


async def test_cola_nueva_se_carga_con_todos_sus_agentes(cc):
    otra = f"soporte@{DOMINIO}"
    await queues_sync.sync_queue(_cola(["201", "202"], name="soporte"), DOMINIO)
    assert otra in cc.colas
    assert cc.reciben_llamadas(otra) == {f"201@{DOMINIO}", f"202@{DOMINIO}"}


async def test_al_arrancar_el_backend_tambien_se_crean(cc, monkeypatch):
    async def reloadxml():
        return "+OK"

    monkeypatch.setattr(esl, "reloadxml", reloadxml)
    await queues_sync.apply_queues([_cola(["101", "104"])], {7: DOMINIO})
    assert cc.reciben_llamadas(COLA) == {f"101@{DOMINIO}", f"104@{DOMINIO}"}


async def test_una_extension_invalida_no_llega_a_freeswitch(cc):
    await queues_sync.sync_queue(_cola(["101", "102 status x"]), DOMINIO)
    assert not any("102 status" in c for c in cc.comandos)
