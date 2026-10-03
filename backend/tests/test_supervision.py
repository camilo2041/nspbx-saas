"""Fase 5 del contact center: supervisor y wallboard.

- Quién ve y quién interviene (coordinador ve, no interviene; asesor nada).
- Agentes y campañas en vivo, con la pausa pasada de su máximo.
- Forzar pausa (no corta la llamada) y sacar (pide confirmar si hay llamada).
- Escuchar, susurrar e intervenir con FreeSWITCH simulado: el supervisor entra
  muteado, y en susurro el cliente nunca lo oye, tampoco uno que entra después.
- Nivel en caliente, pausar y reanudar.
- Wallboard sin usuario: token que se ve una vez, vence y se revoca.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.core import permissions
from app.core.database import async_session, sesion_de_empresa
from app.core.security import crear_token, hash_password
from app.models import AgenteVivo, Campaign, CodigoPausa, Extension, MonitoreoVivo, Tenant, TokenWallboard, User
from app.services import agentes, esl, predictivo, supervision
from app.services.supervision import monitoreo

from .test_agentes import FS, _accion, _entrar, _evento, _vivo, papa  # noqa: F401  (fixtures)


class FSConSalas(FS):
    """FreeSWITCH simulado que además responde `conference <sala> list`."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        self.salas: dict[str, list[str]] = {}  # sala → uuids en orden de entrada
        anterior = esl.api

        async def api(cmd):
            partes = cmd.split()
            if partes[:1] == ["conference"] and len(partes) >= 3 and partes[2] == "list":
                self.api.append(cmd)
                return "\n".join(f"{i + 1};sofia/x;{u};nombre;0;hear|speak;0;0;100" for i, u in enumerate(self.salas.get(partes[1], [])))
            return await anterior(cmd)

        monkeypatch.setattr(esl, "api", api)

    def miembro(self, sala: str, uuid: str) -> str:
        return str(self.salas[sala].index(uuid) + 1)


@pytest.fixture
def fs(monkeypatch):
    return FSConSalas(monkeypatch)


async def _borrar_monitores():
    async with async_session() as s:
        await s.execute(delete(MonitoreoVivo))
        await s.commit()


@pytest.fixture(autouse=True)
async def _sin_monitores():
    await _borrar_monitores()
    yield
    await _borrar_monitores()


async def _monitores() -> list[MonitoreoVivo]:
    async with async_session() as s:
        return list((await s.execute(select(MonitoreoVivo))).scalars())


async def _usuario(papa, rol, extension=None):  # noqa: F811
    async with async_session() as s:
        ext_id = None
        if extension:
            ext = Extension(tenant_id=papa["tenant"], number=extension, password="clave-sip-larga-1")
            s.add(ext)
            await s.flush()
            ext_id = ext.id
        u = User(tenant_id=papa["tenant"], username=f"{rol}{extension or ''}-{papa['slug']}", full_name=f"{rol} papa",
                 password_hash=hash_password("clave-de-prueba"), role=rol, extension_id=ext_id, enabled=True)
        s.add(u)
        await s.commit()
        return u.id


def _cab(papa, uid, rol):  # noqa: F811
    return {"Authorization": f"Bearer {crear_token(uid, rol, papa['tenant'])[0]}"}


@pytest.fixture
async def sup(papa):  # noqa: F811
    uid = await _usuario(papa, permissions.SUPERVISOR, "299")
    return {"id": uid, "cab": _cab(papa, uid, permissions.SUPERVISOR)}


# --- Quién ve qué ------------------------------------------------------------------------------


async def test_permisos(cliente, papa, sup):  # noqa: F811
    asesor = papa["cab"](papa["agentes"][0])
    assert (await cliente.get("/api/supervision/agentes", headers=asesor)).status_code == 403
    coord = await _usuario(papa, permissions.COORDINADOR)
    cab = _cab(papa, coord, permissions.COORDINADOR)
    assert (await cliente.get("/api/supervision/agentes", headers=cab)).status_code == 200
    assert (await cliente.get("/api/supervision/resumen", headers=cab)).status_code == 200
    r = await cliente.post(f"/api/supervision/agentes/{papa['agentes'][0]}/monitorear", headers=cab, json={"modo": "escuchar"})
    assert r.status_code == 403
    r = await cliente.post(f"/api/supervision/agentes/{papa['agentes'][0]}/pausa", headers=cab, json={})
    assert r.status_code == 403
    assert (await cliente.post("/api/supervision/wallboard/tokens", headers=cab, json={"nombre": "TV"})).status_code == 403


# --- En vivo ------------------------------------------------------------------------------------


async def test_agentes_y_campanas_en_vivo(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["progresivo"]
    await _entrar(papa, fs, 0, [camp])
    await _accion(papa, 0, agentes.listo)
    await _entrar(papa, fs, 1, [camp])
    async with sesion_de_empresa(papa["tenant"]) as s:
        await agentes.asegurar_catalogos(s, papa["tenant"])
        brk = (await s.execute(select(CodigoPausa).where(CodigoPausa.codigo == "BREAK"))).scalar_one()
        await s.commit()
    await _accion(papa, 1, agentes.pausar, brk.id)
    # Lleva 20 minutos en un descanso de 15.
    async with async_session() as s:
        await s.execute(update(AgenteVivo).where(AgenteVivo.user_id == papa["agentes"][1])
                        .values(desde=datetime.utcnow() - timedelta(minutes=20)))
        await s.commit()

    filas = (await cliente.get("/api/supervision/agentes", headers=sup["cab"])).json()
    por_id = {f["user_id"]: f for f in filas}
    listo, pausado = por_id[papa["agentes"][0]], por_id[papa["agentes"][1]]
    assert listo["estado"] == "LISTO" and listo["nombre"] == "Agente 0" and listo["campanas"][0]["id"] == camp
    assert pausado["pausa"]["nombre"] == "Descanso" and pausado["pausa_excedida"] and pausado["en_estado_s"] >= 1200
    assert not listo["pausa_excedida"]

    campanas = (await cliente.get("/api/supervision/campanas", headers=sup["cab"])).json()
    c = next(x for x in campanas if x["id"] == camp)
    assert c["agentes"]["conectados"] == 2 and c["agentes"]["listo"] == 1 and c["agentes"]["pausa"] == 1
    assert c["llamadas"] is None  # el progresivo no tiene llamadas sin agente

    r = (await cliente.get("/api/supervision/resumen", headers=sup["cab"])).json()
    assert r["agentes"]["conectados"] == 2 and r["agentes"]["pausas_excedidas"] == 1
    assert {a["nombre"] for a in r["agentes_lista"]} == {"Agente 0", "Agente 1"}


async def test_campana_predictiva_en_vivo(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["progresivo"]
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == camp).values(metodo="predictivo", status="running"))
        await s.commit()
    try:
        await _entrar(papa, fs, 0, [camp])
        ventana = predictivo.motor.ventana(camp)
        ahora = predictivo.motor.reloj()
        for i in range(10):
            ventana.resueltas.append(ahora)
            if i < 3:
                ventana.contestadas.append(ahora)
        c = next(x for x in (await cliente.get("/api/supervision/campanas", headers=sup["cab"])).json() if x["id"] == camp)
        assert c["llamadas"] == {"timbrando": 0, "en_espera": 0}
        assert c["ultimos_15"]["contacto_pct"] == 30.0
    finally:
        predictivo.motor.ventanas.pop(camp, None)
        async with async_session() as s:
            await s.execute(update(Campaign).where(Campaign.id == camp).values(status="paused"))
            await s.commit()


# --- Acciones -------------------------------------------------------------------------------------


async def test_forzar_pausa(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["manual"]
    await _entrar(papa, fs, 0, [camp])
    await _accion(papa, 0, agentes.listo)
    url = f"/api/supervision/agentes/{papa['agentes'][0]}/pausa"
    r = await cliente.post(url, headers=sup["cab"], json={})
    assert r.status_code == 200 and not r.json()["pendiente"]
    assert (await _vivo(papa, 0)).estado == agentes.PAUSA

    # En llamada: queda pendiente, la llamada sigue.
    await _accion(papa, 0, agentes.listo)
    uuid = await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    await _evento(papa, "CHANNEL_ANSWER", uuid, agente=papa["agentes"][0])
    r = await cliente.post(url, headers=sup["cab"], json={})
    assert r.json()["pendiente"]
    vivo = await _vivo(papa, 0)
    assert vivo.estado == agentes.EN_LLAMADA and vivo.pausa_pendiente_id is not None
    assert not any(c == f"uuid_kill {uuid}" for c in fs.api)

    # Un agente que no está conectado: 404.
    r = await cliente.post(f"/api/supervision/agentes/{papa['agentes'][1]}/pausa", headers=sup["cab"], json={})
    assert r.status_code == 404


async def test_sacar_pide_confirmar_si_hay_llamada(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["manual"]
    await _entrar(papa, fs, 0, [camp])
    await _accion(papa, 0, agentes.listo)
    uuid = await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    url = f"/api/supervision/agentes/{papa['agentes'][0]}/sacar"
    r = await cliente.post(url, headers=sup["cab"], json={})
    assert r.status_code == 409 and "confirma" in r.json()["detail"]
    r = await cliente.post(url, headers=sup["cab"], json={"cortar_llamada": True})
    assert r.status_code == 200
    assert f"uuid_kill {uuid}" in fs.api
    assert await _vivo(papa, 0) is None


# --- Monitoreo -------------------------------------------------------------------------------------


async def _supervisor_contesta(papa, fs, sala, agente_audio):  # noqa: F811
    monitor = (await _monitores())[0]
    fs.salas[sala] = [agente_audio, monitor.uuid]
    await monitoreo.recibir({"Event-Name": "CHANNEL_ANSWER", "Unique-ID": monitor.uuid,
                             "variable_nspbx_supervisor": "1", "variable_nspbx_tenant_id": str(papa["tenant"])})
    assert (await _monitores())[0].contestado
    return monitor


async def test_escuchar_susurrar_e_intervenir(cliente, papa, fs, sup, monkeypatch):  # noqa: F811
    monkeypatch.setattr(supervision, "_PAUSA_REINTENTO_S", 0.01)
    camp = papa["camp"]["manual"]
    agente = papa["agentes"][0]
    audio = await _entrar(papa, fs, 0, [camp])
    sala = agentes.conferencia(papa["tenant"], agente)
    url = f"/api/supervision/agentes/{agente}/monitorear"

    r = await cliente.post(url, headers=sup["cab"], json={"modo": "escuchar"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    orig = fs.bgapi[-1]
    assert f"&conference({sala}@nspbx_agente+flags{{mute}})" in orig  # entra muteado, siempre
    assert f"sip_h_X-NSPBX-Agente={token}" in orig and "user/299@" in orig
    assert f"nspbx_supervisor={sup['id']}" in orig
    assert (await cliente.get("/api/supervision/monitoreo", headers=sup["cab"])).json()["agente_id"] == agente

    monitor = await _supervisor_contesta(papa, fs, sala, audio)
    yo = fs.miembro(sala, monitor.uuid)
    assert fs.api[-1] == f"conference {sala} mute {yo}"
    # El agente lo ve en el tablero.
    filas = (await cliente.get("/api/supervision/agentes", headers=sup["cab"])).json()
    assert next(f for f in filas if f["user_id"] == agente)["monitoreo"] == {"supervisor_id": sup["id"], "modo": "escuchar"}

    # Entra un cliente; pasa a susurrar: el cliente no oye al supervisor.
    await _accion(papa, 0, agentes.listo)
    cli = await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    fs.salas[sala].append(cli)
    r = await cliente.post("/api/supervision/monitoreo/modo", headers=sup["cab"], json={"modo": "susurrar"})
    assert r.status_code == 200
    c = fs.miembro(sala, cli)
    i = fs.api.index(f"conference {sala} relate {yo} {c} nospeak")
    assert fs.api.index(f"conference {sala} unmute {yo}") > i  # primero la relación, después el micrófono

    # Intervenir: se borra la relación y habla con los dos.
    await cliente.post("/api/supervision/monitoreo/modo", headers=sup["cab"], json={"modo": "intervenir"})
    assert fs.api[-2:] == [f"conference {sala} relate {yo} {c} clear", f"conference {sala} unmute {yo}"]

    # Colgar: se corta su pata y deja de figurar.
    await cliente.post("/api/supervision/monitoreo/colgar", headers=sup["cab"])
    assert f"uuid_kill {monitor.uuid}" in fs.api
    assert (await cliente.get("/api/supervision/monitoreo", headers=sup["cab"])).json() is None


async def test_un_cliente_que_entra_durante_el_susurro_tampoco_lo_oye(papa, fs, sup, monkeypatch):  # noqa: F811
    monkeypatch.setattr(supervision, "_PAUSA_REINTENTO_S", 0.01)
    camp = papa["camp"]["manual"]
    agente = papa["agentes"][0]
    audio = await _entrar(papa, fs, 0, [camp])
    sala = agentes.conferencia(papa["tenant"], agente)
    async with sesion_de_empresa(papa["tenant"]) as s:
        yo_sup = (await s.execute(select(User).where(User.id == sup["id"]))).unique().scalar_one()
        await monitoreo.iniciar(s, yo_sup, agente, "susurrar")
        await s.commit()
    monitor = await _supervisor_contesta(papa, fs, sala, audio)
    yo = fs.miembro(sala, monitor.uuid)
    assert fs.api[-1] == f"conference {sala} unmute {yo}"  # sin cliente todavía: habla con el agente

    await _accion(papa, 0, agentes.listo)
    cli = await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    antes = len(fs.api)
    tarea = await monitoreo.antes_de_cliente(papa["tenant"], agente)
    assert fs.api[antes:][-1] == f"conference {sala} mute {yo}"  # se mutea antes de que entre
    fs.salas[sala].append(cli)  # el cliente entra a la sala
    await asyncio.wait_for(tarea, 2)
    c = fs.miembro(sala, cli)
    resto = fs.api[antes:]
    assert resto.index(f"conference {sala} relate {yo} {c} nospeak") < resto.index(f"conference {sala} unmute {yo}")


async def test_reglas_del_monitoreo(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["manual"]
    agente = papa["agentes"][0]
    url = f"/api/supervision/agentes/{agente}/monitorear"
    # No conectado.
    assert (await cliente.post(url, headers=sup["cab"], json={"modo": "escuchar"})).status_code == 404
    # Conectado pero sin audio: no hay sala.
    async with sesion_de_empresa(papa["tenant"]) as s:
        u = (await s.execute(select(User).where(User.id == agente))).unique().scalar_one()
        await agentes.entrar(s, u, [camp])
        await s.commit()
    r = await cliente.post(url, headers=sup["cab"], json={"modo": "escuchar"})
    assert r.status_code == 409 and "audio" in r.json()["detail"]
    await _evento(papa, "CHANNEL_ANSWER", fs.uuid(fs.bgapi[-1]), audio=agente)
    # Modo inválido.
    assert (await cliente.post(url, headers=sup["cab"], json={"modo": "grabar"})).status_code == 422
    # Supervisor sin extensión.
    sin_ext = await _usuario(papa, permissions.SUPERVISOR)
    r = await cliente.post(url, headers=_cab(papa, sin_ext, permissions.SUPERVISOR), json={"modo": "escuchar"})
    assert r.status_code == 400 and "extensión" in r.json()["detail"]
    # Uno a la vez por agente.
    assert (await cliente.post(url, headers=sup["cab"], json={"modo": "escuchar"})).status_code == 200
    otro = await _usuario(papa, permissions.ADMIN, "298")
    r = await cliente.post(url, headers=_cab(papa, otro, permissions.ADMIN), json={"modo": "escuchar"})
    assert r.status_code == 409
    # Si el supervisor cuelga desde su teléfono, deja de figurar.
    m = (await _monitores())[0]
    await monitoreo.recibir({"Event-Name": "CHANNEL_HANGUP_COMPLETE", "Unique-ID": m.uuid, "variable_nspbx_supervisor": "1",
                             "variable_nspbx_tenant_id": str(papa["tenant"])})
    assert await _monitores() == []


# --- Campañas en caliente --------------------------------------------------------------------------------


async def test_nivel_en_caliente_pausar_y_reanudar(cliente, papa, fs, sup):  # noqa: F811
    camp = papa["camp"]["progresivo"]
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == camp).values(metodo="predictivo", nivel_actual=2.4))
        await s.commit()
    r = await cliente.put(f"/api/supervision/campanas/{camp}/nivel", headers=sup["cab"],
                          json={"nivel_marcacion": 1.5, "abandono_objetivo": 2.0})
    assert r.status_code == 200 and r.json()["abandono_objetivo"] == 2.0
    async with async_session() as s:
        c = await s.get(Campaign, camp)
        assert (c.nivel_marcacion, c.abandono_objetivo, c.nivel_actual) == (1.5, 2.0, None)
    assert (await cliente.put(f"/api/supervision/campanas/{camp}/nivel", headers=sup["cab"], json={"nivel_max": 9})).status_code == 422

    assert (await cliente.post(f"/api/supervision/campanas/{camp}/reanudar", headers=sup["cab"])).status_code == 400  # sin números
    from app.models import CampaignNumber

    async with async_session() as s:
        s.add(CampaignNumber(tenant_id=papa["tenant"], campaign_id=camp, phone="3009990000"))
        await s.commit()
    r = await cliente.post(f"/api/supervision/campanas/{camp}/reanudar", headers=sup["cab"])
    assert r.json()["status"] == "running"
    r = await cliente.post(f"/api/supervision/campanas/{camp}/pausar", headers=sup["cab"])
    assert r.json()["status"] == "paused"
    manual = papa["camp"]["manual"]
    assert (await cliente.post(f"/api/supervision/campanas/{manual}/reanudar", headers=sup["cab"])).status_code == 400


# --- Wallboard ---------------------------------------------------------------------------------------------


async def test_wallboard_con_token(cliente, papa, fs, sup):  # noqa: F811
    await _entrar(papa, fs, 0, [papa["camp"]["manual"]])
    r = await cliente.post("/api/supervision/wallboard/tokens", headers=sup["cab"], json={"nombre": "TV sala", "dias": 7})
    assert r.status_code == 201
    token, tid = r.json()["token"], r.json()["id"]
    lista = (await cliente.get("/api/supervision/wallboard/tokens", headers=sup["cab"])).json()
    assert lista[0]["nombre"] == "TV sala" and lista[0]["vigente"] and "token" not in lista[0]
    async with async_session() as s:
        fila = await s.get(TokenWallboard, tid)
        assert fila.token_hash != token and token not in fila.token_hash  # solo el hash

    r = await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": token})
    assert r.status_code == 200
    datos = r.json()
    assert datos["empresa"] == "Papa" and datos["agentes"]["conectados"] == 1
    assert "telefono" not in str(datos["agentes_lista"])
    # Sin token, con uno inventado o con un token de sesión: no.
    assert (await cliente.get("/api/wallboard")).status_code == 401
    assert (await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": "wb_inventado"})).status_code == 401
    assert (await cliente.get("/api/wallboard", headers=sup["cab"])).status_code == 401

    # Revocado.
    assert (await cliente.delete(f"/api/supervision/wallboard/tokens/{tid}", headers=sup["cab"])).status_code == 200
    assert (await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": token})).status_code == 401

    # Vencido, y con la empresa desactivada.
    r = await cliente.post("/api/supervision/wallboard/tokens", headers=sup["cab"], json={"nombre": "TV 2"})
    otro = r.json()["token"]
    assert (await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": otro})).status_code == 200
    async with async_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == papa["tenant"]).values(enabled=False))
        await s.commit()
    assert (await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": otro})).status_code == 401
    async with async_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == papa["tenant"]).values(enabled=True))
        await s.execute(update(TokenWallboard).where(TokenWallboard.id == r.json()["id"])
                        .values(vence=datetime.utcnow() - timedelta(seconds=1)))
        await s.commit()
    assert (await cliente.get("/api/wallboard", headers={"X-Wallboard-Token": otro})).status_code == 401
    assert (await cliente.post("/api/supervision/wallboard/tokens", headers=sup["cab"], json={"nombre": "x", "dias": 365})).status_code == 422


def test_leer_miembros_de_la_conferencia():
    salida = "1;sofia/internal/201@x;aaa-1;Agente;201;hear|speak;0;0;300\n2;sofia/internal/299@x;bbb-2;Sup;299;hear;0;0;300\n"
    assert supervision.leer_miembros(salida) == [
        {"id": "1", "uuid": "aaa-1", "flags": "hear|speak"},
        {"id": "2", "uuid": "bbb-2", "flags": "hear"},
    ]
    assert supervision.leer_miembros("-ERR Conference agente_1_2 not found") == []


async def test_dos_replicas_no_pueden_poner_dos_supervisores_al_mismo_agente(papa, sup):  # noqa: F811
    """La regla «uno por agente» la garantiza la base, no la memoria de una
    réplica: dos pedidos simultáneos en réplicas distintas no pasan los dos."""
    from sqlalchemy.exc import IntegrityError

    otro = await _usuario(papa, permissions.ADMIN, "296")
    agente = papa["agentes"][0]
    async with sesion_de_empresa(papa["tenant"]) as s1, sesion_de_empresa(papa["tenant"]) as s2:
        s1.add(MonitoreoVivo(tenant_id=papa["tenant"], uuid="r1", supervisor_id=sup["id"], agente_id=agente, modo="escuchar", token="t1"))
        s2.add(MonitoreoVivo(tenant_id=papa["tenant"], uuid="r2", supervisor_id=otro, agente_id=agente, modo="escuchar", token="t2"))
        await s1.commit()
        with pytest.raises(IntegrityError):
            await s2.commit()
    assert [m.uuid for m in await _monitores()] == ["r1"]
