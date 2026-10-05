"""Opción A de docs/escala.md §4: cada empresa vive en un FreeSWITCH.

- Cada comando va al servidor de la empresa (explícito, por empresa, por el
  evento que se está procesando o por la empresa de la tarea en curso).
- Lo que es de la plataforma (recargar la configuración, colgar huérfanas)
  llega a todos, y un servidor caído no impide que los demás lo reciban.
- Un servidor desactivado no recibe nada: sus empresas vuelven al principal.
- Si se cae la conexión de eventos de un servidor, solo se descartan sus
  llamadas del tablero.
- Solo la plataforma da de alta servidores y mueve empresas; al mover, las
  troncales pasan a la carpeta del servidor nuevo.
"""

import shutil
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, update

from app.core import permissions
from app.core.config import settings
from app.core.contexto import hay_evento, nodo_del_evento
from app.core.database import async_session, sesion_de_empresa
from app.core.runtime_settings import runtime_settings
from app.models import AgenteVivo, NodoFreeswitch, SesionAgente, Tenant, Trunk
from app.services import esl, gateways
from app.services.nodos import directorio
from app.services.tiempo_real import Resolutor, TiempoReal

CAIDOS: set[str] = set()


class ClienteFalso:
    """Un FreeSWITCH por host: anota qué comando recibió cada uno."""

    enviados: list[tuple[str, str]] = []

    def __init__(self, host, port, password):
        self.host, self.port, self.password = host, port, password
        self.connected = False

    async def connect(self):
        if self.host in CAIDOS:
            raise ConnectionRefusedError(self.host)
        self.connected = True

    async def close(self):
        self.connected = False

    async def api(self, command):
        ClienteFalso.enviados.append((self.host, command))
        if command == "status":
            canales = 7 if self.host == "fs2.test" else 3
            return f"FreeSWITCH (Version 1.10.12) is ready\n{canales} session(s) - peak 10, last 5min 4\n"
        return "+OK"

    async def bgapi(self, command):
        return await self.api(f"bgapi {command}")


async def _sin_nodos():
    # ON DELETE SET NULL: sus empresas vuelven al principal.
    async with async_session() as s:
        await s.execute(delete(NodoFreeswitch))
        await s.commit()
    shutil.rmtree(Path(settings.fs_conf_dir) / "nodos", ignore_errors=True)


@pytest.fixture
async def fs(monkeypatch, mundo):
    await _sin_nodos()
    CAIDOS.clear()
    ClienteFalso.enviados = []
    monkeypatch.setattr(esl, "ESLClient", ClienteFalso)
    esl._clientes.clear()
    directorio.invalidar(avisar=False)
    yield ClienteFalso
    await _sin_nodos()
    esl._clientes.clear()
    directorio.invalidar(avisar=False)



def _principal() -> str:
    return runtime_settings.fs_esl_host


async def _nodo(nombre="nodo2", host="fs2.test", activo=True, empresas=()) -> int:
    async with async_session() as s:
        n = NodoFreeswitch(nombre=nombre, esl_host=host, esl_port=8021, esl_password="clave-nodo-2",
                           sip_host=f"sip.{host}", activo=activo)
        s.add(n)
        await s.flush()
        for tid in empresas:
            await s.execute(update(Tenant).where(Tenant.id == tid).values(nodo_id=n.id))
        await s.commit()
    directorio.invalidar(avisar=False)
    return n.id


def _hosts(fs, comando: str) -> list[str]:
    return [h for h, c in fs.enviados if c == comando]


# --- A qué servidor va cada comando -------------------------------------------


async def test_cada_empresa_a_su_servidor(mundo, fs):
    nid = await _nodo(empresas=[mundo.alfa.id])
    await esl.api("uno", tenant_id=mundo.alfa.id)
    await esl.api("dos", tenant_id=mundo.beta.id)
    await esl.api("tres")  # sin empresa: el principal
    assert _hosts(fs, "uno") == ["fs2.test"]
    assert _hosts(fs, "dos") == [_principal()]
    assert _hosts(fs, "tres") == [_principal()]
    # El explícito manda sobre la empresa.
    await esl.api("cuatro", tenant_id=mundo.alfa.id, nodo=None)
    assert _hosts(fs, "cuatro") == [_principal()]
    # La empresa de la tarea en curso (sesion_de_empresa / fijar_tenant).
    async with sesion_de_empresa(mundo.alfa.id):
        await esl.bgapi("cinco")
    await esl.bgapi("seis")
    assert _hosts(fs, "bgapi cinco") == ["fs2.test"]
    assert _hosts(fs, "bgapi seis") == [_principal()]
    # Procesando un evento: el servidor que lo mandó, aunque la tarea sea de otra empresa.
    t1, t2 = hay_evento.set(True), nodo_del_evento.set(nid)
    try:
        async with sesion_de_empresa(mundo.beta.id):
            await esl.api("siete")
    finally:
        hay_evento.reset(t1)
        nodo_del_evento.reset(t2)
    assert _hosts(fs, "siete") == ["fs2.test"]


async def test_servidor_desactivado_devuelve_sus_empresas_al_principal(mundo, fs):
    await _nodo(activo=False, empresas=[mundo.alfa.id])
    await esl.api("uno", tenant_id=mundo.alfa.id)
    assert _hosts(fs, "uno") == [_principal()]
    assert await directorio.todos() == [None]


async def test_lo_de_la_plataforma_llega_a_todos(mundo, fs):
    nid = await _nodo()
    await _nodo("nodo3", "fs3.test")
    CAIDOS.add("fs3.test")
    assert await esl.reloadxml() == "+OK"
    assert sorted(_hosts(fs, "reloadxml")) == sorted([_principal(), "fs2.test"])
    r = await esl.api_todos("hupall NORMAL_CLEARING nspbx_pred 1")
    assert r[None] == "+OK" and r[nid] == "+OK"
    assert [isinstance(v, Exception) for k, v in r.items() if k not in (None, nid)] == [True]
    # Los canales en curso suman todos los servidores que responden.
    assert await esl.sesiones_en_curso() == 3 + 7
    # Si el principal no responde, recargar la configuración falla (y el
    # marcador no marca a ciegas).
    CAIDOS.add(_principal())
    esl._clientes.clear()
    with pytest.raises(ConnectionRefusedError):
        await esl.reloadxml()
    with pytest.raises(ConnectionRefusedError):
        await esl.sesiones_en_curso()


async def test_un_servidor_cambiado_reconecta_con_los_datos_nuevos(mundo, fs):
    nid = await _nodo(empresas=[mundo.alfa.id])
    await esl.api("uno", tenant_id=mundo.alfa.id)
    async with async_session() as s:
        await s.execute(update(NodoFreeswitch).where(NodoFreeswitch.id == nid).values(esl_host="fs2b.test"))
        await s.commit()
    directorio.invalidar(avisar=False)
    await esl.api("dos", tenant_id=mundo.alfa.id)
    assert _hosts(fs, "dos") == ["fs2b.test"]


# --- Tablero en vivo -----------------------------------------------------------


async def test_caida_de_eventos_de_un_servidor_solo_descarta_sus_llamadas(mundo):
    resolutor = Resolutor()
    await resolutor.refrescar(forzar=True)
    rt = TiempoReal(resolutor)
    cola = rt.suscribir(mundo.alfa.id)

    async def llega(uuid, nodo):
        t1, t2 = hay_evento.set(True), nodo_del_evento.set(nodo)
        try:
            await rt.recibir({"Event-Name": "CHANNEL_CREATE", "Unique-ID": uuid, "Event-Date-Timestamp": "1760000000000000",
                              "variable_nspbx_tenant_id": str(mundo.alfa.id)})
        finally:
            hay_evento.reset(t1)
            nodo_del_evento.reset(t2)

    await llega("a-principal", None)
    await llega("a-nodo", 5)
    assert {c["uuid"] for c in rt.llamadas(mundo.alfa.id)} == {"a-principal", "a-nodo"}
    assert all("nodo" not in c for c in rt.llamadas(mundo.alfa.id))
    while not cola.empty():
        cola.get_nowait()
    rt.reiniciar(nodo=5)
    assert [c["uuid"] for c in rt.llamadas(mundo.alfa.id)] == ["a-principal"]
    aviso = cola.get_nowait()
    assert aviso["tipo"] == "reinicio" and [c["uuid"] for c in aviso["llamadas"]] == ["a-principal"]
    rt.reiniciar()
    assert rt.llamadas(mundo.alfa.id) == []


# --- Archivos de troncales por servidor ------------------------------------------


def _carpeta(nodo: str | None) -> Path:
    return gateways._gateways_path(nodo)


async def test_cada_servidor_con_las_troncales_de_sus_empresas(mundo, fs):
    async with async_session() as s:
        troncales = list((await s.execute(Trunk.__table__.select())).all())
        trunks = [await s.get(Trunk, t.id) for t in troncales]
    slugs = {mundo.alfa.id: mundo.alfa.slug, mundo.beta.id: mundo.beta.slug}
    gateways.sync_gateways(trunks, slugs, {mundo.alfa.id: "nodo2"}, ["nodo2"])
    en_nodo = {p.name for p in _carpeta("nodo2").glob("*.xml")}
    en_principal = {p.name for p in _carpeta(None).glob("*.xml")}
    assert en_nodo and all(n.startswith("gw_alfa_") for n in en_nodo)
    assert not any(n.startswith("gw_alfa_") for n in en_principal)
    assert any(n.startswith("gw_beta_") for n in en_principal)
    assert Path(settings.fs_conf_dir) / "nodos" / "nodo2" in _carpeta("nodo2").parents
    # Un nombre de servidor no puede salirse de la carpeta.
    with pytest.raises(Exception):
        gateways._gateways_path("../etc")


# --- API de la plataforma -------------------------------------------------------


async def test_solo_la_plataforma(cliente, mundo, fs):
    for metodo, url in [("get", "/api/plataforma/nodos"), ("post", "/api/plataforma/nodos"),
                        ("put", f"/api/plataforma/nodos/empresas/{mundo.alfa.id}")]:
        r = await getattr(cliente, metodo)(url, headers=mundo.alfa.cabeceras(), **({} if metodo == "get" else {"json": {}}))
        assert r.status_code == 403, url


async def test_alta_lista_y_validacion(cliente, mundo, fs):
    cab = mundo.cabeceras_plataforma()
    cuerpo = {"nombre": "nodo2", "esl_host": "fs2.test", "esl_password": "clave-nodo-2", "sip_host": "sip2.test"}
    r = await cliente.post("/api/plataforma/nodos", json=cuerpo, headers=cab)
    assert r.status_code == 201 and r.json()["capacidad_agentes"] == 200
    assert "esl_password" not in r.json()
    assert (await cliente.post("/api/plataforma/nodos", json=cuerpo, headers=cab)).status_code == 409
    assert (await cliente.post("/api/plataforma/nodos", json={**cuerpo, "nombre": "x3", "esl_host": "a b;c"}, headers=cab)).status_code == 422
    assert (await cliente.post("/api/plataforma/nodos", json={**cuerpo, "nombre": "../x"}, headers=cab)).status_code == 422
    assert _carpeta("nodo2").is_dir()
    CAIDOS.add("fs3.test")
    nid3 = (await cliente.post("/api/plataforma/nodos", json={**cuerpo, "nombre": "nodo3", "esl_host": "fs3.test"}, headers=cab)).json()["id"]
    lista = (await cliente.get("/api/plataforma/nodos", headers=cab)).json()
    assert [(n["nombre"], n["principal"], n["conectado"]) for n in lista] == [
        ("principal", True, True), ("nodo2", False, True), ("nodo3", False, False)]
    assert lista[1]["canales"] == 7 and lista[0]["empresas"] >= 2
    assert (await cliente.post(f"/api/plataforma/nodos/{nid3}/probar", headers=cab)).json()["conectado"] is False
    r = await cliente.put(f"/api/plataforma/nodos/{nid3}", json={"activo": False, "capacidad_agentes": 150}, headers=cab)
    assert r.json()["activo"] is False and r.json()["capacidad_agentes"] == 150
    assert (await cliente.post("/api/plataforma/nodos/999999/probar", headers=cab)).status_code == 404


async def test_mover_una_empresa(cliente, mundo, fs):
    cab = mundo.cabeceras_plataforma()
    nid = await _nodo()
    inactivo = await _nodo("nodo3", "fs3.test", activo=False)
    async with async_session() as s:
        trunk = await s.get(Trunk, mundo.alfa.ids["trunk"])
        nombre = gateways.nombre_gateway(trunk.name, mundo.alfa.slug)
        gateways.write_gateway_file(trunk, mundo.alfa.slug)
    assert (_carpeta(None) / f"gw_{nombre}.xml").exists()
    url = f"/api/plataforma/nodos/empresas/{mundo.alfa.id}"
    assert (await cliente.put(url, json={"nodo_id": inactivo}, headers=cab)).status_code == 409
    # Con agentes conectados pide confirmación.
    async with async_session() as s:
        ses = SesionAgente(tenant_id=mundo.alfa.id, user_id=mundo.alfa.usuarios[permissions.ADMIN], campanas=[], inicio=datetime.utcnow())
        s.add(ses)
        await s.flush()
        s.add(AgenteVivo(tenant_id=mundo.alfa.id, user_id=ses.user_id, sesion_id=ses.id, estado="LISTO"))
        await s.commit()
    r = await cliente.put(url, json={"nodo_id": nid}, headers=cab)
    assert r.status_code == 409 and "conectados" in r.json()["detail"]
    r = await cliente.put(url, json={"nodo_id": nid, "forzar": True}, headers=cab)
    assert r.status_code == 200 and r.json()["cambio"] is True
    assert any("sip.fs2.test" in a for a in r.json()["avisos"])
    assert (_carpeta("nodo2") / f"gw_{nombre}.xml").exists()
    assert not (_carpeta(None) / f"gw_{nombre}.xml").exists()
    assert sorted(_hosts(fs, "sofia profile external rescan")) == sorted([_principal(), "fs2.test"])
    # Ya vive allá: sus comandos van a ese servidor.
    await esl.api("hola", tenant_id=mundo.alfa.id)
    assert _hosts(fs, "hola") == ["fs2.test"]
    empresas = {t["id"]: t for t in (await cliente.get("/api/tenants", headers=cab)).json()}
    assert empresas[mundo.alfa.id]["nodo_id"] == nid and empresas[mundo.beta.id]["nodo_id"] is None
    # Un servidor con empresas no se borra; vacío, sí.
    assert (await cliente.delete(f"/api/plataforma/nodos/{nid}", headers=cab)).status_code == 409
    r = await cliente.put(url, json={"nodo_id": None, "forzar": True}, headers=cab)
    assert r.status_code == 200 and (_carpeta(None) / f"gw_{nombre}.xml").exists()
    assert (await cliente.delete(f"/api/plataforma/nodos/{nid}", headers=cab)).status_code == 204
