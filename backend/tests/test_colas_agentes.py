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
        self.dnd: set[str] = set()  # claves de la base interna (db select/dnd/...)

    async def api(self, cmd, tenant_id=None, nodo=None):
        self.comandos.append(cmd)
        p = cmd.split()
        if p[0] == "db":
            accion, _, clave = p[1].split("/")[:3]
            if accion == "insert":
                self.dnd.add(clave)
            elif accion == "delete":
                self.dnd.discard(clave)
            return "on" if clave in self.dnd else ""
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
            self.agentes[p[4]][p[3]] = " ".join(p[5:]).strip("'")
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


# --- Dialplan de la cola y números internos ---------------------------------

from xml.etree import ElementTree as ET  # noqa: E402

from app.services.config_generator import _append_queue_routes  # noqa: E402


def _acciones_de_cola(failover):
    ctx = ET.Element("context", attrib={"name": "ctx_alfa"})
    _append_queue_routes(ctx, [_cola(["101"], extension="5000", failover_extension=failover)], DOMINIO)
    return [(a.get("application"), a.get("data")) for a in ctx.iter("action")]


def test_quien_ya_fue_atendido_no_se_pasa_al_desborde():
    """Si el agente cuelga primero, mod_callcenter devuelve al cliente al
    dialplan salvo que hangup_after_bridge sea true; la acción siguiente es el
    desborde, así que con false el cliente atendido terminaba transferido."""
    acciones = _acciones_de_cola("200")
    i_cc = acciones.index(("callcenter", f"ventas@{DOMINIO}"))
    previas = dict(a for a in acciones[:i_cc] if a[0] == "set" and "=" in (a[1] or "")).values()
    assert "hangup_after_bridge=true" in previas
    assert "hangup_after_bridge=false" not in previas
    # Sin agente que conteste (no hubo bridge) el desborde sigue después.
    assert acciones[i_cc + 1] == ("transfer", "200 XML ctx_alfa")


async def test_numero_de_cola_no_puede_ser_el_de_una_extension(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    cuerpo = {"name": "ventas", "extension": "1000", "agents": ["1000"]}
    r = await cliente.post("/api/queues", json=cuerpo, headers=cab)
    assert r.status_code == 409 and "extensión 1000" in r.json()["detail"]
    # Ni el de otra cola (soporte es 5000), ni editar una cola para chocar.
    r = await cliente.post("/api/queues", json={**cuerpo, "extension": "5000"}, headers=cab)
    assert r.status_code in (400, 409)
    r = await cliente.put(f"/api/queues/{mundo.alfa.ids['queue']}", json={"extension": "1000"}, headers=cab)
    assert r.status_code == 409
    # El desborde no puede ser la propia cola.
    r = await cliente.put(f"/api/queues/{mundo.alfa.ids['queue']}", json={"failover_extension": "5000"}, headers=cab)
    assert r.status_code == 400


async def test_extension_no_puede_tomar_el_numero_de_una_cola(cliente, mundo):
    cab = mundo.alfa.cabeceras()
    r = await cliente.post("/api/extensions", json={"number": "5000", "password": "Clave-Segura-9182"}, headers=cab)  # gitleaks:allow (clave de prueba)
    assert r.status_code == 409 and "soporte" in r.json()["detail"]
    r = await cliente.put(f"/api/extensions/{mundo.alfa.ids['extension']}", json={"number": "5000"}, headers=cab)
    assert r.status_code == 409
    # El mismo número en OTRA empresa sí se puede (cada una tiene su plan de marcado).
    r = await cliente.get("/api/queues", headers=mundo.beta.cabeceras())
    assert any(q["extension"] == "5000" for q in r.json())


# --- No molestar en colas ----------------------------------------------------

from app.services.config_generator import _append_dnd_feature_codes, _append_dnd_hook  # noqa: E402


async def test_con_no_molestar_la_cola_no_le_timbra(cc):
    """mod_callcenter le marca directo al agente (sin pasar por el dialplan
    donde está el corte de DND): el DND tiene que pausarlo en la cola."""
    await queues_sync.sync_queue(_cola(["101", "102"]), DOMINIO)
    await esl.dnd_set("102", 7, DOMINIO, True)
    assert cc.reciben_llamadas(COLA) == {f"101@{DOMINIO}"}
    # Guardar la cola de nuevo no lo vuelve a poner disponible.
    await queues_sync.sync_queue(_cola(["101", "102"]), DOMINIO)
    assert cc.reciben_llamadas(COLA) == {f"101@{DOMINIO}"}
    await esl.dnd_set("102", 7, DOMINIO, False)
    assert cc.reciben_llamadas(COLA) == {f"101@{DOMINIO}", f"102@{DOMINIO}"}


async def test_no_molestar_no_se_mezcla_entre_empresas(cc):
    await esl.dnd_set("102", 7, DOMINIO, True)
    assert await esl.dnd_status("102", 7)
    assert not await esl.dnd_status("102", 8)


def test_codigos_de_no_molestar_pausan_al_agente():
    ctx = ET.Element("context", attrib={"name": "ctx_alfa"})
    _append_dnd_feature_codes(ctx, DOMINIO, 7)
    _append_dnd_hook(ctx, [SimpleNamespace(number="101")], 7)
    datos = [a.get("data") for a in ctx.iter("action")]
    assert "insert/dnd/${caller_id_number}_t7/on" in datos
    assert any(f"agent set status ${{caller_id_number}}@{DOMINIO} 'On Break'" in (d or "") for d in datos)
    assert any(f"agent set status ${{caller_id_number}}@{DOMINIO} Available" in (d or "") for d in datos)
    campos = [c.get("field") for c in ctx.iter("condition")]
    assert "${db(select/dnd/${destination_number}_t7)}" in campos
