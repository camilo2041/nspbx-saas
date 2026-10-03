"""Fase 1 del contact center: tiempos de cada llamada y llamadas en vivo.

- El CDR guarda setup, ring, espera y quién colgó, cada uno por separado.
- Los eventos de FreeSWITCH llegan SOLO a la empresa de la llamada.
- El WebSocket de tiempo real exige sesión vigente y permiso de ver todas
  las llamadas; una sesión cerrada ya no lo abre (tampoco /ws/logs).
"""

import asyncio
import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.api.tiempo_real_ws import PERMISO, autorizar
from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import CallLog, License, Tenant, User
from app.services import tiempos_llamada
from app.services.ajustes import get_or_create_settings
from app.services.tiempo_real import Resolutor, TiempoReal, leer_evento

from .conftest import FS_SECRET

T0 = 1_760_000_000_000_000  # microsegundos


def _vars(**marcas_ms) -> dict:
    """Variables de CDR con marcas relativas a T0, en milisegundos."""
    v = {"start_uepoch": str(T0)}
    for nombre, ms in marcas_ms.items():
        v[f"{nombre}_uepoch"] = str(T0 + ms * 1000)
    return v


# --- Tiempos del CDR ---------------------------------------------------------


def test_saliente_contestada():
    t = tiempos_llamada.calcular(_vars(progress=1200, answer=5200, end=65200))
    assert (t.setup_ms, t.ring_ms) == (1200, 4000)
    assert t.progress_at == datetime.utcfromtimestamp((T0 + 1_200_000) / 1_000_000)


def test_sin_contestar_el_ring_es_hasta_que_se_cuelga():
    t = tiempos_llamada.calcular(_vars(progress=800, end=30800))
    assert (t.setup_ms, t.ring_ms) == (800, 30000)


def test_audio_temprano_sin_180_cuenta_como_timbre():
    v = _vars(progress_media=600, answer=3600, end=9000)
    v["progress_uepoch"] = "0"
    assert tiempos_llamada.calcular(v).ring_ms == 3000


def test_sin_timbre_no_hay_setup():
    t = tiempos_llamada.calcular(_vars(answer=300, end=10000))
    assert (t.setup_ms, t.ring_ms, t.progress_at) == (None, 300, None)


def test_marcas_incoherentes_no_dan_tiempos_negativos():
    t = tiempos_llamada.calcular(_vars(progress=5000, answer=1000))
    assert t.ring_ms is None


def test_espera():
    assert tiempos_llamada.calcular({"hold_accum_usec": "12500000"}).espera_ms == 12500
    assert tiempos_llamada.calcular({"hold_accum_seconds": "7"}).espera_ms == 7000
    assert tiempos_llamada.calcular({}).espera_ms is None


@pytest.mark.parametrize(
    "direccion,disposicion,quien",
    [
        ("outbound", "recv_bye", "llamado"),
        ("outbound", "send_bye", "llamante"),
        ("inbound", "recv_bye", "llamante"),
        ("inbound", "send_bye", "llamado"),
        ("inbound", "recv_cancel", "llamante"),
        ("outbound", "", None),
    ],
)
def test_quien_colgo(direccion, disposicion, quien):
    v = {"direction": direccion, "sip_hangup_disposition": disposicion}
    assert tiempos_llamada.calcular(v).colgo == quien


# --- CDR y estadísticas por la API --------------------------------------------


@pytest.fixture
async def mike(mundo):
    """Empresa sin llamadas, para que los promedios no dependan de otras pruebas."""
    async with async_session() as s:
        t = Tenant(name="Mike", slug=f"mike{uuidlib.uuid4().hex[:6]}", sip_domain=f"m{uuidlib.uuid4().hex[:6]}.test",
                   modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        await get_or_create_settings(s, t.id)
        admin = User(tenant_id=t.id, username=f"admin-{t.slug}", full_name="admin mike",
                     password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True)
        s.add(admin)
        await s.commit()
        return {"tenant": t.id, "admin": admin.id,
                "cab": {"Authorization": f"Bearer {crear_token(admin.id, permissions.ADMIN, t.id)[0]}"}}


async def _cdr(cliente, tenant_id: int, **extra) -> str:
    u = f"cdr-{uuidlib.uuid4()}"
    variables = {"uuid": u, "nspbx_tenant_id": str(tenant_id), "direction": "outbound",
                 "hangup_cause": "NORMAL_CLEARING", **extra}
    resp = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": variables})
    assert resp.status_code == 200
    return u


async def test_el_cdr_guarda_los_tiempos_y_la_api_los_devuelve(cliente, mike):
    u = await _cdr(
        cliente, mike["tenant"], billsec="60", sip_hangup_disposition="recv_bye", hold_accum_usec="4000000",
        **_vars(progress=1500, answer=6500, end=66500),
    )
    async with async_session() as s:
        c = (await s.execute(select(CallLog).where(CallLog.uuid == u))).scalar_one()
    assert (c.setup_ms, c.ring_ms, c.espera_ms, c.colgo) == (1500, 5000, 4000, "llamado")
    fila = (await cliente.get(f"/api/calls/{c.id}", headers=mike["cab"])).json()
    assert (fila["setup_ms"], fila["ring_ms"], fila["espera_ms"], fila["colgo"]) == (1500, 5000, 4000, "llamado")


async def test_promedios_en_las_estadisticas(cliente, mike):
    vacias = (await cliente.get("/api/calls/stats", headers=mike["cab"])).json()
    assert vacias["ring_promedio_s"] is None and vacias["hablado_promedio_s"] is None

    await _cdr(cliente, mike["tenant"], billsec="30", **_vars(progress=1000, answer=3000, end=33000))
    await _cdr(cliente, mike["tenant"], billsec="90", **_vars(progress=2000, answer=8000, end=98000))
    # No contestada: cuenta para el setup, no para el ring ni lo hablado.
    await _cdr(cliente, mike["tenant"], billsec="0", hangup_cause="NO_ANSWER", **_vars(progress=3000, end=33000))
    r = (await cliente.get("/api/calls/stats", headers=mike["cab"])).json()
    assert r["ring_promedio_s"] == 4.0  # (2 + 6) / 2
    assert r["setup_promedio_s"] == 2.0  # (1 + 2 + 3) / 3
    assert r["hablado_promedio_s"] == 60.0


# --- Eventos de FreeSWITCH -----------------------------------------------------


def test_leer_evento_decodifica_los_valores():
    ev = leer_evento("Event-Name: CHANNEL_CREATE\nCaller-Caller-ID-Name: Mar%C3%ADa%20P%C3%A9rez\nUnique-ID: abc")
    assert ev == {"Event-Name": "CHANNEL_CREATE", "Caller-Caller-ID-Name": "María Pérez", "Unique-ID": "abc"}


def _ev(nombre: str, uuid: str, ms: int = 0, **extra) -> dict:
    return {"Event-Name": nombre, "Unique-ID": uuid, "Event-Date-Timestamp": str(T0 + ms * 1000), **extra}


@pytest.fixture
async def rt(mundo):
    resolutor = Resolutor()
    await resolutor.refrescar(forzar=True)
    return TiempoReal(resolutor)


def _vaciar(cola: asyncio.Queue) -> list[dict]:
    mensajes = []
    while not cola.empty():
        mensajes.append(cola.get_nowait())
    return mensajes


async def test_cada_empresa_recibe_solo_sus_llamadas(rt, mundo):
    alfa, beta = rt.suscribir(mundo.alfa.id), rt.suscribir(mundo.beta.id)
    # Una por cada forma de identificar la empresa.
    await rt.recibir(_ev("CHANNEL_CREATE", "a1", variable_nspbx_tenant_id=str(mundo.alfa.id),
                         **{"Caller-Destination-Number": "3001112233"}))
    await rt.recibir(_ev("CHANNEL_CREATE", "a2", variable_domain_name=mundo.alfa.dominio))
    async with async_session() as s:
        contexto_beta = (await s.get(Tenant, mundo.beta.id)).dialplan_context
    await rt.recibir(_ev("CHANNEL_CREATE", "b2", **{"Caller-Context": contexto_beta}))
    # Sin empresa identificable: no le llega a nadie.
    await rt.recibir(_ev("CHANNEL_CREATE", "x1", variable_domain_name="nadie.test"))

    assert {m["llamada"]["uuid"] for m in _vaciar(alfa)} == {"a1", "a2"}
    assert {m["llamada"]["uuid"] for m in _vaciar(beta)} == {"b2"}
    assert all("_visto" not in c for c in rt.llamadas(mundo.beta.id))
    assert {c["uuid"] for c in rt.llamadas(mundo.alfa.id)} == {"a1", "a2"}
    assert all("tenant_id" not in c for c in rt.llamadas(mundo.alfa.id))


async def test_ciclo_de_una_llamada(rt, mundo):
    cola = rt.suscribir(mundo.alfa.id)
    tid = {"variable_nspbx_tenant_id": str(mundo.alfa.id)}
    await rt.recibir(_ev("CHANNEL_CREATE", "c1", 0, **tid, **{"Call-Direction": "outbound"}))
    await rt.recibir(_ev("CHANNEL_PROGRESS", "c1", 900))
    await rt.recibir(_ev("CHANNEL_PROGRESS_MEDIA", "c1", 1200))  # el timbre es el primero
    await rt.recibir(_ev("CHANNEL_ANSWER", "c1", 4900))
    await rt.recibir(_ev("CHANNEL_BRIDGE", "c1", 5000, **{"Other-Leg-Unique-ID": "c2"}))
    await rt.recibir(_ev("CHANNEL_HOLD", "c1", 9000))
    assert rt.llamadas(mundo.alfa.id)[0]["estado"] == "espera"
    await rt.recibir(_ev("CHANNEL_UNHOLD", "c1", 12000))
    await rt.recibir(_ev("CHANNEL_HANGUP_COMPLETE", "c1", 20000, **{"Hangup-Cause": "NORMAL_CLEARING"}))

    mensajes = _vaciar(cola)
    assert [m["evento"] for m in mensajes] == [
        "nueva", "timbra", "timbra", "contesta", "puente", "espera", "retoma", "cuelga",
    ]
    final = mensajes[-1]["llamada"]
    assert final["direccion"] == "saliente" and final["otra_pata"] == "c2"
    assert final["ring_ms"] == 4000 and final["causa"] == "NORMAL_CLEARING"
    assert rt.llamadas(mundo.alfa.id) == []


async def test_la_empresa_se_resuelve_cuando_llega_la_variable(rt, mundo):
    """El dialplan puede fijar nspbx_tenant_id después de crear el canal."""
    cola = rt.suscribir(mundo.alfa.id)
    await rt.recibir(_ev("CHANNEL_CREATE", "d1"))
    assert _vaciar(cola) == []
    await rt.recibir(_ev("CHANNEL_ANSWER", "d1", 100, variable_nspbx_tenant_id=str(mundo.alfa.id)))
    assert [m["evento"] for m in _vaciar(cola)] == ["contesta"]


async def test_una_empresa_desactivada_no_recibe(mundo):
    async with async_session() as s:
        t = Tenant(name="Off", slug=f"off{uuidlib.uuid4().hex[:6]}", sip_domain=f"o{uuidlib.uuid4().hex[:6]}.test",
                   enabled=False)
        s.add(t)
        await s.commit()
    resolutor = Resolutor()
    await resolutor.refrescar(forzar=True)
    rt = TiempoReal(resolutor)
    cola = rt.suscribir(t.id)
    await rt.recibir(_ev("CHANNEL_CREATE", "e1", variable_nspbx_tenant_id=str(t.id)))
    assert _vaciar(cola) == []


async def test_un_id_de_empresa_inventado_no_se_publica(rt):
    cola = rt.suscribir(999999)
    await rt.recibir(_ev("CHANNEL_CREATE", "f1", variable_nspbx_tenant_id="999999"))
    assert _vaciar(cola) == []


async def test_al_perder_la_conexion_se_vacia(rt, mundo):
    cola = rt.suscribir(mundo.alfa.id)
    await rt.recibir(_ev("CHANNEL_CREATE", "g1", variable_nspbx_tenant_id=str(mundo.alfa.id)))
    rt.reiniciar()
    assert rt.llamadas(mundo.alfa.id) == []
    assert _vaciar(cola)[-1] == {"tipo": "reinicio", "llamadas": []}


async def test_un_cliente_lento_no_hace_crecer_la_memoria(rt, mundo):
    cola = rt.suscribir(mundo.alfa.id)
    for i in range(cola.maxsize + 50):
        await rt.recibir(_ev("CHANNEL_CREATE", f"h{i}", variable_nspbx_tenant_id=str(mundo.alfa.id)))
    assert cola.qsize() == cola.maxsize
    assert cola.get_nowait()["llamada"]["uuid"] == "h50"  # se descartó lo más viejo


async def test_desuscribir(rt, mundo):
    cola = rt.suscribir(mundo.alfa.id)
    rt.desuscribir(mundo.alfa.id, cola)
    await rt.recibir(_ev("CHANNEL_CREATE", "i1", variable_nspbx_tenant_id=str(mundo.alfa.id)))
    assert _vaciar(cola) == []


# --- Quién abre el WebSocket ------------------------------------------------------


@pytest.mark.parametrize("rol", [permissions.ADMIN, permissions.SUPERVISOR, permissions.ASESOR])
async def test_el_socket_exige_el_permiso(mundo, rol):
    esperado = mundo.alfa.id if permissions.puede(rol, PERMISO, mundo.alfa.id) else None
    assert await autorizar(mundo.alfa.token(rol)) == esperado


async def test_el_socket_rechaza_sin_empresa_o_sin_token(mundo):
    token_plataforma = crear_token(mundo.plataforma_id, permissions.PLATAFORMA, None)[0]
    assert await autorizar(token_plataforma) is None
    for token in (None, "", "basura"):
        assert await autorizar(token) is None


async def test_una_sesion_cerrada_no_abre_los_sockets(mundo):
    from app.api.logs_ws import _usuario_del_token
    from app.core.database import app_session

    async with async_session() as s:
        u = User(tenant_id=mundo.alfa.id, username=f"sup-{uuidlib.uuid4().hex[:6]}", full_name="sup",
                 password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True)
        s.add(u)
        await s.commit()
    token = crear_token(u.id, permissions.ADMIN, mundo.alfa.id)[0]
    assert await autorizar(token) == mundo.alfa.id
    async with async_session() as s:
        await s.execute(update(User).where(User.id == u.id).values(sesiones_desde=datetime.utcnow() + timedelta(seconds=1)))
        await s.commit()
    assert await autorizar(token) is None
    async with app_session() as s:
        assert await _usuario_del_token(token, s) is None


async def test_una_empresa_desactivada_no_abre_el_socket(mike):
    token = crear_token(mike["admin"], permissions.ADMIN, mike["tenant"])[0]
    assert await autorizar(token) == mike["tenant"]
    async with async_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == mike["tenant"]).values(enabled=False))
        await s.commit()
    assert await autorizar(token) is None


async def test_un_canal_sin_cuelgue_se_purga(rt, mundo):
    await rt.recibir(_ev("CHANNEL_CREATE", "j1", variable_nspbx_tenant_id=str(mundo.alfa.id)))
    rt._canales["j1"]["_visto"] -= 7 * 3600
    assert rt.llamadas(mundo.alfa.id) == []


async def test_la_conexion_de_eventos_reparte_canales_y_resultados(monkeypatch, rt, mundo):
    """El mismo socket de ESL trae los resultados de los originate
    (BACKGROUND_JOB) y los eventos de canal: cada uno a su destino, y al
    cerrarse el socket el tablero se vacía."""
    from app.services import esl, tiempo_real as modulo
    from app.services.lider import lider

    monkeypatch.setattr(modulo, "tiempo_real", rt)
    monkeypatch.setattr(lider, "es_lider", True)
    cola = rt.suscribir(mundo.alfa.id)
    futuro = asyncio.get_running_loop().create_future()
    monkeypatch.setitem(esl._pending_jobs, "job-1", futuro)

    def trama(cuerpo: str) -> bytes:
        datos = cuerpo.encode()
        return f"Content-Length: {len(datos)}\nContent-Type: text/event-plain\n\n".encode() + datos

    lector = asyncio.StreamReader()
    lector.feed_data(trama(
        f"Event-Name: CHANNEL_CREATE\nUnique-ID: k1\nvariable_nspbx_tenant_id: {mundo.alfa.id}\n"
        "Caller-Destination-Number: 300%20555\n\n"
    ))
    lector.feed_data(trama("Event-Name: BACKGROUND_JOB\nJob-UUID: job-1\nContent-Length: 4\n\n+OK\n"))
    lector.feed_data(trama("Event-Name: CHANNEL_ANSWER\nUnique-ID: k1\n\n"))
    lector.feed_eof()
    await esl._event_loop(lector)

    assert futuro.result() == "+OK"
    mensajes = _vaciar(cola)
    assert [m.get("evento") for m in mensajes] == ["nueva", "contesta", None]
    assert mensajes[0]["llamada"]["a"] == "300 555"
    assert mensajes[-1]["tipo"] == "reinicio"



async def test_una_replica_que_no_es_lider_ignora_los_eventos_de_canal(monkeypatch, rt, mundo):
    """Solo la líder los procesa (services/lider.py); la otra igual recibe
    el resultado de sus propios originate."""
    from app.services import esl, tiempo_real as modulo
    from app.services.lider import lider

    monkeypatch.setattr(modulo, "tiempo_real", rt)
    monkeypatch.setattr(lider, "es_lider", False)
    cola = rt.suscribir(mundo.alfa.id)
    futuro = asyncio.get_running_loop().create_future()
    monkeypatch.setitem(esl._pending_jobs, "job-2", futuro)

    def trama(cuerpo: str) -> bytes:
        datos = cuerpo.encode()
        return f"Content-Length: {len(datos)}\nContent-Type: text/event-plain\n\n".encode() + datos

    lector = asyncio.StreamReader()
    lector.feed_data(trama(f"Event-Name: CHANNEL_CREATE\nUnique-ID: k9\nvariable_nspbx_tenant_id: {mundo.alfa.id}\n\n"))
    lector.feed_data(trama("Event-Name: BACKGROUND_JOB\nJob-UUID: job-2\nContent-Length: 4\n\n+OK\n"))
    lector.feed_eof()
    await esl._event_loop(lector)
    assert futuro.result() == "+OK"
    assert _vaciar(cola) == []  # ni el canal ni un «reinicio»: nunca tuvo llamadas
    assert rt.llamadas(mundo.alfa.id) == []
