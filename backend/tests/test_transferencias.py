"""Fase B de la auditoría: poner en espera y transferir (consola de agente y
softphone), aviso a la app móvil en llamadas de grupo y parámetros de un
agente que está en varios grupos."""

import json
import uuid as uuidlib
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import async_session
from app.models import DeviceToken, Extension, Queue
from app.services import esl, push, push_colas, queues_sync

from .test_agentes import FS, _entrar, _evento, _vivo, papa  # noqa: F401 (fixture)


class FSLlamadas(FS):
    """Además de guardar comandos, responde `show calls` y `uuid_exists`."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        self.llamadas: list[dict] = []
        guardar = esl.api

        async def api(cmd, *args, **kw):
            if cmd == "show calls as json":
                self.api.append(cmd)
                return json.dumps({"row_count": len(self.llamadas), "rows": self.llamadas})
            if cmd.startswith("uuid_exists "):
                self.api.append(cmd)
                return "false" if cmd.split()[1] in self.no_existe else "true"
            return await guardar(cmd, **kw)

        monkeypatch.setattr(esl, "api", api)

    def ultimo(self, prefijo: str) -> str:
        return next(c for c in reversed(self.api) if c.startswith(prefijo))


@pytest.fixture
def fsl(monkeypatch):
    return FSLlamadas(monkeypatch)


async def _en_llamada(cliente, papa, fsl, i=0) -> str:
    """Agente i entra, marca a mano y el cliente contesta. Devuelve su uuid."""
    await _entrar(papa, fsl, i, [papa["camp"]["manual"]])
    r = await cliente.post("/api/agente/marcar", headers=papa["cab"](papa["agentes"][i]),
                           json={"campaign_id": papa["camp"]["manual"], "telefono": f"300{uuidlib.uuid4().int % 10**7:07d}"})
    assert r.status_code == 200, r.text
    llamada = fsl.uuid(fsl.bgapi[-1])
    await _evento(papa, "CHANNEL_ANSWER", llamada, agente=papa["agentes"][i])
    assert (await _vivo(papa, i)).estado == "EN_LLAMADA"
    return llamada


def _ctx(papa) -> str:
    return f"ctx_{papa['slug']}"


# --- Consola de agente -------------------------------------------------------------


async def test_agente_pone_en_espera_y_retoma(cliente, papa, fsl):
    llamada = await _en_llamada(cliente, papa, fsl)
    cab = papa["cab"](papa["agentes"][0])
    r = await cliente.post("/api/llamada/espera", headers=cab, json={"activar": True})
    assert r.status_code == 200 and r.json() == {"en_espera": True}
    assert fsl.api[-1] == f"uuid_transfer {llamada} playback:local_stream://moh inline"
    assert (await _vivo(papa)).en_espera is True
    estado = (await cliente.get("/api/agente/estado", headers=cab)).json()
    assert estado["agente"]["en_espera"] is True

    r = await cliente.post("/api/llamada/espera", headers=cab, json={"activar": False})
    assert r.status_code == 200
    sala = f"agente_{papa['tenant']}_{papa['agentes'][0]}@nspbx_agente"
    assert fsl.api[-1] == f"uuid_transfer {llamada} conference:{sala} inline"
    assert (await _vivo(papa)).en_espera is False


async def test_agente_transfiere_directo_y_queda_para_disponer(cliente, papa, fsl):
    llamada = await _en_llamada(cliente, papa, fsl)
    cab = papa["cab"](papa["agentes"][0])
    r = await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "8000"})
    assert r.status_code == 200 and r.json()["estado"] == "transferida"
    assert fsl.api[-1] == f"uuid_transfer {llamada} 8000 XML {_ctx(papa)}"
    assert (await _vivo(papa)).estado == "DISPO"
    # El cliente cuelga después con quien lo atendió: el agente sigue igual.
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", llamada, agente=papa["agentes"][0], causa="NORMAL_CLEARING")
    assert (await _vivo(papa)).estado == "DISPO"


async def test_agente_consulta_y_completa(cliente, papa, fsl):
    llamada = await _en_llamada(cliente, papa, fsl)
    cab = papa["cab"](papa["agentes"][0])
    r = await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "201", "consultada": True})
    assert r.status_code == 200 and r.json()["estado"] == "consultando"
    assert fsl.api[-1] == f"uuid_transfer {llamada} playback:local_stream://moh inline"
    origen = fsl.bgapi[-1]
    consulta = fsl.uuid(origen)
    sala = f"agente_{papa['tenant']}_{papa['agentes'][0]}@nspbx_agente"
    assert f"user/201@{papa['dominio']} &conference({sala})" in origen
    vivo = await _vivo(papa)
    assert (vivo.en_espera, vivo.consulta_uuid, vivo.consulta_destino) == (True, consulta, "201")
    # No se puede abrir otra consulta ni poner en espera a medias.
    assert (await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "201", "consultada": True})).status_code == 409

    r = await cliente.post("/api/llamada/transferencia/completar", headers=cab)
    assert r.status_code == 200, r.text
    assert fsl.api[-1] == f"uuid_bridge {llamada} {consulta}"
    vivo = await _vivo(papa)
    assert vivo.estado == "DISPO" and vivo.consulta_uuid is None and vivo.en_espera is False


async def test_agente_consulta_y_vuelve_con_el_cliente(cliente, papa, fsl):
    llamada = await _en_llamada(cliente, papa, fsl)
    cab = papa["cab"](papa["agentes"][0])
    await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "8000", "consultada": True})
    consulta = fsl.uuid(fsl.bgapi[-1])
    # Lo que no es una extensión se llama por el dialplan de la empresa.
    assert f"loopback/8000/{_ctx(papa)} &conference(" in fsl.bgapi[-1]
    r = await cliente.post("/api/llamada/transferencia/cancelar", headers=cab)
    assert r.status_code == 200
    assert f"uuid_kill {consulta}" in fsl.api
    assert fsl.api[-1].startswith(f"uuid_transfer {llamada} conference:")
    vivo = await _vivo(papa)
    assert vivo.estado == "EN_LLAMADA" and vivo.consulta_uuid is None and not vivo.en_espera


async def test_agente_completa_pero_el_consultado_ya_colgo(cliente, papa, fsl):
    llamada = await _en_llamada(cliente, papa, fsl)
    cab = papa["cab"](papa["agentes"][0])
    await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "201", "consultada": True})
    fsl.no_existe.add(fsl.uuid(fsl.bgapi[-1]))
    r = await cliente.post("/api/llamada/transferencia/completar", headers=cab)
    assert r.status_code == 409 and "ya colgó" in r.json()["detail"]
    assert fsl.api[-1].startswith(f"uuid_transfer {llamada} conference:")
    assert (await _vivo(papa)).estado == "EN_LLAMADA"


# --- Softphone (sin sesión de agente) -----------------------------------------------


def _llamada_softphone(fsl, papa, ext="201"):
    propia, otra = str(uuidlib.uuid4()), str(uuidlib.uuid4())
    fsl.llamadas = [
        # Otra empresa con la misma extensión: no se toca.
        {"uuid": str(uuidlib.uuid4()), "presence_id": f"{ext}@otra.test", "b_uuid": str(uuidlib.uuid4())},
        {"uuid": otra, "presence_id": "", "b_uuid": propia, "b_presence_id": f"{ext}@{papa['dominio']}"},
    ]
    return propia, otra


async def test_softphone_espera_y_transferencia_directa(cliente, papa, fsl):
    cab = papa["cab"](papa["agentes"][1])
    sin = await cliente.post("/api/llamada/espera", headers=cab, json={"activar": True})
    assert sin.status_code == 409 and "llamada en curso" in sin.json()["detail"]

    propia, _ = _llamada_softphone(fsl, papa)
    assert (await cliente.post("/api/llamada/espera", headers=cab, json={"activar": True})).status_code == 200
    assert fsl.api[-1] == f"uuid_hold {propia}"
    assert (await cliente.post("/api/llamada/espera", headers=cab, json={"activar": False})).status_code == 200
    assert fsl.api[-1] == f"uuid_hold off {propia}"

    r = await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "*99200"})
    assert r.status_code == 200
    assert fsl.api[-1] == f"uuid_transfer {propia} -bleg *99200 XML {_ctx(papa)}"


async def test_softphone_transferencia_consultada(cliente, papa, fsl):
    cab = papa["cab"](papa["agentes"][1])
    propia, _ = _llamada_softphone(fsl, papa)
    r = await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "200", "consultada": True})
    assert r.status_code == 200 and r.json()["estado"] == "consultando"
    comando = fsl.api[-1]
    assert comando.startswith(f"uuid_broadcast {propia} att_xfer::{{")
    assert f"nspbx_consulta_de={propia}" in comando and comando.endswith(f"}}user/200@{papa['dominio']} aleg")

    assert (await cliente.post("/api/llamada/transferencia/cancelar", headers=cab)).status_code == 200
    assert fsl.api[-1] == f"hupall NORMAL_CLEARING nspbx_consulta_de {propia}"
    assert (await cliente.post("/api/llamada/transferencia/completar", headers=cab)).status_code == 200
    assert fsl.api[-1] == f"uuid_kill {propia}"


async def test_softphone_validaciones(cliente, papa, fsl):
    cab = papa["cab"](papa["agentes"][1])
    _llamada_softphone(fsl, papa)
    assert (await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "abc"})).status_code == 422
    assert (await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "201"})).status_code == 422
    # Dos llamadas a la vez: no se adivina cuál.
    fsl.llamadas.append({"uuid": str(uuidlib.uuid4()), "presence_id": f"201@{papa['dominio']}", "b_uuid": "x"})
    r = await cliente.post("/api/llamada/transferir", headers=cab, json={"destino": "200"})
    assert r.status_code == 409 and "más de una" in r.json()["detail"]
    # Sin extensión no hay llamada propia que tocar.
    from app.core import permissions
    from app.core.security import crear_token

    sin_ext = {"Authorization": f"Bearer {crear_token(papa['sin_ext'], permissions.ASESOR, papa['tenant'])[0]}"}
    assert (await cliente.post("/api/llamada/espera", headers=sin_ext, json={"activar": True})).status_code == 400


async def test_destinos_de_transferencia(cliente, papa):
    r = await cliente.get("/api/llamada/destinos", headers=papa["cab"](papa["agentes"][1]))
    assert r.status_code == 200
    numeros = {e["numero"] for e in r.json()["extensiones"]}
    assert "200" in numeros and "201" not in numeros  # la propia no


# --- Aviso a la app móvil en llamadas de grupo -----------------------------------------


async def test_llamada_de_grupo_despierta_la_app(papa, monkeypatch):
    async with async_session() as s:
        ext = (await s.execute(select(Extension).where(Extension.tenant_id == papa["tenant"], Extension.number == "200"))).scalar_one()
        s.add(DeviceToken(tenant_id=papa["tenant"], user_id=papa["agentes"][0], extension_id=ext.id,
                          platform="android", token_type="FCM", token="tok-200"))
        s.add(Queue(tenant_id=papa["tenant"], name="ventas", extension="8100", agents='["200", "201"]'))
        await s.commit()
    enviados = []

    async def fcm(token, evento):
        enviados.append((token, evento))

    monkeypatch.setattr(push, "enviar_push_android", fcm)
    ev = {
        "Event-Name": "CUSTOM", "Event-Subclass": "callcenter::info", "CC-Action": "member-queue-start",
        "CC-Queue": f"ventas@{papa['dominio']}", "CC-Member-Session-UUID": "abc-123",
        "CC-Member-CID-Number": "3005550000", "CC-Member-CID-Name": "Juan",
    }
    assert await push_colas.recibir(ev) == 1
    token, evento = enviados[0]
    assert token == "tok-200" and evento["serverCallId"] == "abc-123"
    assert evento["caller"]["phoneNumber"] == "3005550000"
    assert evento["metadata"] == {"extension": "200", "tenantSlug": papa["slug"]}
    # Otras acciones, otro dominio o una cola que no es de esa empresa: nada.
    assert await push_colas.recibir({**ev, "CC-Action": "agent-offering"}) == 0
    assert await push_colas.recibir({**ev, "CC-Queue": "ventas@nadie.test"}) == 0
    assert await push_colas.recibir({**ev, "CC-Queue": f"soporte@{papa['dominio']}"}) == 0
    assert await push_colas.recibir({"Event-Name": "CHANNEL_ANSWER"}) == 0
    assert len(enviados) == 1


# --- Agente en varios grupos -------------------------------------------------------------


def _cola(id, nombre, agentes, **kw):
    base = dict(id=id, tenant_id=1, name=nombre, extension=f"8{id:03d}", strategy="ring-all", moh_sound="$${hold_music}",
                agents=json.dumps(agentes), max_wait_time=0, max_wait_time_with_no_agent=0, agent_ring_timeout=20,
                max_no_answer=3, wrap_up_time=10, record=False, failover_extension=None,
                announce_position=False, enabled=True)
    return SimpleNamespace(**{**base, **kw})


def test_agente_en_varios_grupos_toma_el_valor_mas_holgado():
    ventas = _cola(1, "ventas", ["101", "102"], wrap_up_time=5, agent_ring_timeout=15)
    soporte = _cola(2, "soporte", ["101"], wrap_up_time=30, max_no_answer=5)
    apagada = _cola(3, "noche", ["101"], wrap_up_time=99, enabled=False)
    otra_empresa = _cola(4, "ventas", ["101"], tenant_id=2, wrap_up_time=60)
    todas = [ventas, soporte, apagada, otra_empresa]
    assert queues_sync.parametros_agente("101", ventas, todas) == {"ring": 20, "max_no_answer": 5, "wrap_up_time": 30}
    assert queues_sync.parametros_agente("102", ventas, todas) == {"ring": 15, "max_no_answer": 3, "wrap_up_time": 5}
    # Sin la lista completa (compatibilidad): los de esa cola.
    assert queues_sync.parametros_agente("101", ventas) == {"ring": 15, "max_no_answer": 3, "wrap_up_time": 5}

    xml = ET.fromstring(queues_sync.build_callcenter_xml([ventas, soporte], {1: "a.test"}))
    agentes = {a.get("name"): a for a in xml.iter("agent")}
    assert agentes["101@a.test"].get("wrap-up-time") == "30"
    assert agentes["101@a.test"].get("max-no-answer") == "5"
    assert agentes["101@a.test"].get("contact") == "[leg_timeout=20]user/101@a.test"
    assert agentes["102@a.test"].get("wrap-up-time") == "5"


async def test_guardar_un_grupo_aplica_los_valores_combinados(cliente, mundo, monkeypatch):
    comandos = []

    async def api(cmd, *a, **kw):
        comandos.append(cmd)
        return "+OK"

    monkeypatch.setattr(esl, "api", api)
    cab = mundo.alfa.cabeceras()
    r = await cliente.post("/api/queues", headers=cab, json={
        "name": f"largo{uuidlib.uuid4().hex[:5]}", "extension": f"87{uuidlib.uuid4().int % 100:02d}",
        "agents": ["1000"], "wrap_up_time": 45,
    })
    assert r.status_code == 201, r.text
    # La 1000 también está en «soporte» (10 s): queda el mayor.
    assert any(c.endswith(f"wrap_up_time 1000@{mundo.alfa.dominio} 45") for c in comandos), comandos
    async with async_session() as s:
        await s.delete(await s.get(Queue, r.json()["id"]))
        await s.commit()
