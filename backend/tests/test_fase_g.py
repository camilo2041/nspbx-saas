"""Fase G: prueba de humo, vigía de grupos y devolución de llamada, buzón
completo, festivos, calidad automática y operación."""

import re
from datetime import datetime

import pytest
from sqlalchemy import delete, select, update

from app.core import permissions
from app.core.config import settings
from app.core.database import async_session
from app.models import Extension, MensajeBuzon, NumeroSinRuta, Queue
from app.services import esl, humo

# --- G1: prueba de humo --------------------------------------------------------------------


class CentralFalsa:
    """Responde como FreeSWITCH y, al originar, deja lo que dejaría el CDR."""

    def __init__(self, monkeypatch, mundo, viva=True, deja_cdr=True):
        self.mundo, self.viva, self.deja_cdr = mundo, viva, deja_cdr
        self.comandos: list[str] = []
        self.en_fila: str | None = None
        monkeypatch.setattr(esl, "api", self.api)
        monkeypatch.setattr(esl, "bgapi", self.bgapi)

    async def api(self, cmd, tenant_id=None, **kw):
        self.comandos.append(cmd)
        if not self.viva:
            raise ConnectionError("ESL caído")
        if cmd == "status":
            return "UP 0 years, 1 day\nFreeSWITCH is ready\n"
        if cmd.startswith("sofia status gateway"):
            return "State\tREGED\n"
        if cmd == "show registrations":
            return f"reg_user,realm\n1000,{self.mundo.alfa.dominio}\n"
        if cmd.startswith("callcenter_config queue list members"):
            cabecera = "queue|instance_id|uuid|session_uuid|cid_number|cid_name|system_epoch|joined_epoch|state|score"
            fila = f"\nq|i|m|aaaaaaaa-0000-0000-0000-000000000009|{self.en_fila}|P|0|1|Waiting|0" if self.en_fila else ""
            return cabecera + fila + "\n+OK\n"
        if cmd.startswith("callcenter_config queue list agents"):
            return "name|status|state|max_no_answer\n1000@x|Available|Waiting|3\n+OK\n"
        return "+OK"

    async def bgapi(self, cmd, tenant_id=None, **kw):
        self.comandos.append(cmd)
        quien = re.search(r"origination_caller_id_number=(\d+)", cmd).group(1)
        destino = re.search(r"loopback/([^/ ]+)/", cmd).group(1)
        if destino.startswith("*99") and self.deja_cdr:
            async with async_session() as s:
                s.add(MensajeBuzon(tenant_id=self.mundo.alfa.id, extension="1000", caller_number=quien, duracion=7,
                                   ruta=f"{settings.fs_recordings_dir}/t{self.mundo.alfa.id}/buzon/1000/humo.wav"))
                await s.commit()
        elif destino.startswith(humo.PREFIJO) and self.deja_cdr:
            async with async_session() as s:
                s.add(NumeroSinRuta(numero=destino, origen=quien))
                await s.commit()
        elif "/public" not in cmd:
            self.en_fila = quien
        return "+OK Job-UUID: x"


@pytest.fixture
async def con_buzon_y_grupo(mundo):
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=True))
        q = Queue(tenant_id=mundo.alfa.id, name="humo_g", extension="8711", strategy="ring-all", agents='["1000"]', enabled=True)
        s.add(q)
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=False))
        await s.execute(delete(Queue).where(Queue.id == q.id))
        await s.execute(delete(NumeroSinRuta))
        await s.commit()


async def test_prueba_de_humo_completa(cliente, mundo, monkeypatch, con_buzon_y_grupo):
    central = CentralFalsa(monkeypatch, mundo)
    r = await cliente.post("/api/plataforma/humo", headers=mundo.cabeceras_plataforma(),
                           json={"tenant_id": mundo.alfa.id, "buzon": "1000", "grupo": "8711"})
    assert r.status_code == 200, r.text
    pasos = {p["clave"]: p for p in r.json()["pasos"]}
    assert {k: p["estado"] for k, p in pasos.items() if k != "voces"} == {
        "central": "ok", "proveedores": "ok", "telefonos": "ok", "sin_ruta": "ok", "buzon": "ok", "grupo": "ok",
    }
    assert "1 conectado" in pasos["telefonos"]["detalle"] and "1 agente(s) libre(s)" in pasos["grupo"]["detalle"]
    # Lo que dejó la prueba se limpia, y la llamada de la fila se cuelga.
    async with async_session() as s:
        assert not (await s.execute(select(MensajeBuzon).where(MensajeBuzon.caller_number.like(f"{humo.PREFIJO}%")))).first()
        assert not (await s.execute(select(NumeroSinRuta))).first()
    assert any(c.startswith("uuid_kill ") for c in central.comandos)
    # El buzón se prueba por *99 en el contexto de la empresa; el número sin ruta, por el público.
    assert any(f"loopback/*991000/ctx_{mundo.alfa.slug}" in c for c in central.comandos)
    assert any("/public &park()" in c for c in central.comandos)
    # Solo la plataforma.
    r = await cliente.post("/api/plataforma/humo", headers=mundo.alfa.cabeceras(permissions.ADMIN), json={"tenant_id": mundo.alfa.id})
    assert r.status_code == 403


async def test_prueba_de_humo_con_fallos(mundo, monkeypatch, con_buzon_y_grupo):
    monkeypatch.setattr(humo, "ESPERA_CDR_SEG", 1)
    CentralFalsa(monkeypatch, mundo, deja_cdr=False)
    r = await humo.probar(mundo.alfa.id, "1000", "9999")
    pasos = {p["clave"]: p for p in r["pasos"]}
    assert r["ok"] is False
    assert pasos["sin_ruta"]["estado"] == "fallo" and "json_cdr" in pasos["sin_ruta"]["detalle"]
    assert pasos["buzon"]["estado"] == "fallo"
    assert pasos["grupo"]["estado"] == "fallo" and "no existe" in pasos["grupo"]["detalle"]

    CentralFalsa(monkeypatch, mundo, viva=False)
    r = await humo.probar(mundo.alfa.id)
    assert [p["estado"] for p in r["pasos"]] == ["fallo", "omitido"]


async def test_mensaje_de_prueba_no_manda_correo(cliente, mundo, monkeypatch):
    """El CDR de un mensaje dejado por la prueba de humo no avisa por correo."""
    from app.services import buzon

    avisos = []

    async def avisar(tenant_id, mensaje_id):
        avisos.append(mensaje_id)

    monkeypatch.setattr(buzon, "avisar", avisar)
    monkeypatch.setattr(buzon, "duracion_wav", lambda ruta: 5.0)
    from pathlib import Path

    carpeta = Path(settings.recordings_dir) / f"t{mundo.alfa.id}" / "buzon" / "1000"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "humo-g.wav").write_bytes(b"RIFF")
    from .conftest import FS_SECRET

    ruta = f"{settings.fs_recordings_dir.rstrip('/')}/t{mundo.alfa.id}/buzon/1000/humo-g.wav"
    try:
        for quien in (f"{humo.PREFIJO}123456", "3005550000"):
            r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
                "uuid": f"humo-{quien}-{datetime.utcnow().timestamp()}", "nspbx_tenant_id": str(mundo.alfa.id),
                "direction": "inbound", "billsec": "7", "caller_id_number": quien,
                "nspbx_buzon_ext": "1000", "nspbx_buzon": ruta,
            }})
            assert r.status_code == 200
            (carpeta / "humo-g.wav").write_bytes(b"RIFF")
        assert len(avisos) == 1
    finally:
        async with async_session() as s:
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.ruta == ruta))
            await s.commit()


# --- G2 y G3: vigía de los grupos y devolución de llamada ---------------------------------------

import asyncio  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.models import Devolucion  # noqa: E402
from app.services import config_generator, vigia_colas, voice_prompts  # noqa: E402


def test_dialplan_de_un_grupo_con_devolucion():
    ctx = ET.Element("context", name="ctx_a")
    q = SimpleNamespace(id=5, tenant_id=1, name="ventas", extension="8000", enabled=True, announce_position=False,
                        devolucion=True, failover_extension="*99101")
    config_generator._append_queue_routes(ctx, [q], "a.test")
    ext = {e.get("name"): [f"{a.get('application')} {a.get('data')}" for a in e.iter("action")] for e in ctx}
    assert ext["queue_ventas"][-3:] == [
        "set cc_exit_keys=1", "callcenter ventas@a.test", "transfer cola_salida_8000_${cc_cancel_reason} XML ctx_a"]
    assert "set nspbx_pide_devolucion=5" in ext["devolucion_ventas"] and ext["devolucion_ventas"][-1] == "hangup NORMAL_CLEARING"
    # Sin la tecla, la salida de siempre (el desborde).
    assert ext["cola_salida_ventas"] == ["transfer *99101 XML ctx_a"]
    assert "set cc_base_score=100000" in ext["devolver_ventas"] and ext["devolver_ventas"][-1] == "transfer 8000 XML ctx_a"
    # La tecla 1 lleva a la devolución antes que al desborde.
    nombres = [e.get("name") for e in ctx]
    assert nombres.index("devolucion_ventas") < nombres.index("cola_salida_ventas")
    # Sin devolución, igual que antes.
    ctx2 = ET.Element("context", name="ctx_a")
    config_generator._append_queue_routes(ctx2, [SimpleNamespace(**{**vars(q), "devolucion": False})], "a.test")
    assert [e.get("name") for e in ctx2] == ["queue_ventas"]


@pytest.fixture
async def grupo_devolucion(mundo):
    async with async_session() as s:
        q = Queue(tenant_id=mundo.alfa.id, name="devol_g", extension="8712", strategy="ring-all", agents='["1000"]',
                  enabled=True, devolucion=True, announce_position=True)
        s.add(q)
        await s.commit()
    yield q
    async with async_session() as s:
        await s.execute(delete(Devolucion).where(Devolucion.queue_id == q.id))
        await s.execute(delete(Queue).where(Queue.id == q.id))
        await s.commit()


async def test_el_cdr_anota_la_devolucion(cliente, mundo, grupo_devolucion):
    from .conftest import FS_SECRET

    async def cdr(numero, uuid):
        r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
            "uuid": uuid, "nspbx_tenant_id": str(mundo.alfa.id), "direction": "inbound", "billsec": "40",
            "caller_id_number": numero, "sip_req_user": "6015550000", "nspbx_pide_devolucion": str(grupo_devolucion.id),
        }})
        assert r.status_code == 200

    await cdr("3005551234", "dv-1")
    await cdr("3005551234", "dv-2")  # la pidió dos veces: una sola pendiente
    await cdr("anonymous", "dv-3")  # sin número, no se puede devolver
    async with async_session() as s:
        filas = (await s.execute(select(Devolucion).where(Devolucion.queue_id == grupo_devolucion.id))).scalars().all()
    assert [(d.numero, d.did, d.estado) for d in filas] == [("3005551234", "6015550000", "pendiente")]


_AGENTES = "name|status|state|max_no_answer\n1000@x|Available|Waiting|3\n+OK\n"


def _miembros(*filas):
    cab = "queue|instance_id|uuid|session_uuid|cid_number|cid_name|system_epoch|joined_epoch|state|score"
    return cab + "".join(f"\nq|i|m|{u}|{n}|X|0|{t}|Waiting|0" for u, n, t in filas) + "\n+OK\n"


async def test_el_vigia_devuelve_la_llamada_cuando_le_toca(mundo, monkeypatch, grupo_devolucion, tmp_path):
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    (tmp_path / "prompts").mkdir()
    for k in ("cola_aviso", "cola_delante_0", "cola_devolucion_oferta"):
        (tmp_path / "prompts" / f"{k}.wav").write_bytes(b"RIFF")
    import calendar

    pedida = datetime.utcnow()
    epoch_pedida = calendar.timegm(pedida.timetuple())
    async with async_session() as s:
        d = Devolucion(tenant_id=mundo.alfa.id, queue_id=grupo_devolucion.id, numero="3005551234", did="6015550000",
                       pedida_at=pedida)
        s.add(d)
        await s.commit()
    estado = {"miembros": _miembros(("aaaaaaaa-0000-0000-0000-000000000001", "3001112222", epoch_pedida - 30))}
    comandos, originados = [], []

    async def api(cmd, tenant_id=None, **kw):
        comandos.append(cmd)
        if "list members" in cmd:
            return estado["miembros"] if "devol_g" in cmd else _miembros()
        if "list agents" in cmd:
            return _AGENTES
        return "+OK"

    async def bgapi_wait(cmd, timeout=40, tenant_id=None):
        originados.append(cmd)
        return "+OK uuid"

    monkeypatch.setattr(esl, "api", api)
    monkeypatch.setattr(esl, "bgapi_wait", bgapi_wait)
    v = vigia_colas.Vigia()

    # Alguien llegó antes de que la pidiera y sigue esperando: respeta su turno.
    r = await v.ciclo(ahora=epoch_pedida + 20)
    assert r["devoluciones"] == 0
    foto = {g["nombre"]: g for g in v.foto(mundo.alfa.id)}["devol_g"]
    assert (foto["esperando"], foto["agentes"]["libres"], foto["devoluciones_pendientes"]) == (1, 1, 1)
    # Al que espera se le ofrece la devolución junto con la posición.
    difusion = [c for c in comandos if c.startswith("uuid_broadcast")]
    assert difusion and "cola_devolucion_oferta" in difusion[0] and "cola_delante_0" in difusion[0]

    # Ya no hay nadie antes: la central llama al cliente y lo pone de primero.
    estado["miembros"] = _miembros()
    r = await v.ciclo(ahora=epoch_pedida + 60)
    assert r["devoluciones"] == 1
    await asyncio.sleep(0.05)
    assert len(originados) == 1
    cmd = originados[0]
    assert f"loopback/3005551234/ctx_{mundo.alfa.slug} devolver_8712_3005551234 XML ctx_{mundo.alfa.slug}" in cmd
    assert "origination_caller_id_number=6015550000" in cmd and f"nspbx_devolucion_id={d.id}" in cmd
    async with async_session() as s:
        hecha = await s.get(Devolucion, d.id)
    assert (hecha.estado, hecha.intentos) == ("hecha", 1)


async def test_devolucion_sin_contestar_se_reintenta_y_falla(mundo, monkeypatch, grupo_devolucion):
    async with async_session() as s:
        d = Devolucion(tenant_id=mundo.alfa.id, queue_id=grupo_devolucion.id, numero="3005551234", pedida_at=datetime.utcnow())
        s.add(d)
        await s.commit()

    async def api(cmd, tenant_id=None, **kw):
        return _AGENTES if "list agents" in cmd else _miembros()

    async def bgapi_wait(cmd, timeout=40, tenant_id=None):
        raise RuntimeError("-ERR NO_ANSWER")

    monkeypatch.setattr(esl, "api", api)
    monkeypatch.setattr(esl, "bgapi_wait", bgapi_wait)
    v = vigia_colas.Vigia()
    for intento in range(1, vigia_colas.INTENTOS_MAX + 1):
        await v.ciclo()
        await asyncio.sleep(0.05)
        async with async_session() as s:
            fila = await s.get(Devolucion, d.id)
            if fila.estado == "pendiente":
                # Espera el reintento; para la prueba, ya.
                fila.proximo_at = None
                await s.commit()
    assert (fila.estado, fila.intentos) == ("fallida", vigia_colas.INTENTOS_MAX) and "NO_ANSWER" in fila.detalle


async def test_supervision_ve_grupos_y_devoluciones(cliente, mundo, monkeypatch):
    vigia_colas.vigia._fotos[mundo.alfa.id] = (__import__("time").monotonic(), [{"id": 1, "nombre": "ventas", "esperando": 2}])
    try:
        cab = mundo.alfa.cabeceras(permissions.SUPERVISOR)
        assert (await cliente.get("/api/supervision/grupos", headers=cab)).json()[0]["esperando"] == 2
        assert (await cliente.get("/api/supervision/grupos", headers=mundo.beta.cabeceras(permissions.SUPERVISOR))).json() == []
        resumen = (await cliente.get("/api/supervision/resumen", headers=cab)).json()
        assert resumen["grupos"][0]["nombre"] == "ventas"
        dev = (await cliente.get("/api/supervision/devoluciones", headers=cab)).json()
        mia = next(x for x in dev["lista"] if x["id"] == mundo.alfa.ids["devolucion"])
        assert mia["estado"] == "pendiente" and dev["cifras"]["pendiente"] >= 1
        assert all(x["numero"].startswith(mundo.alfa.telefono) for x in dev["lista"])
    finally:
        vigia_colas.vigia._fotos.pop(mundo.alfa.id, None)


# --- G4: buzón completo ------------------------------------------------------------------------

import io  # noqa: E402
import uuid as uuidlib  # noqa: E402
import wave  # noqa: E402
from pathlib import Path  # noqa: E402

from app.models import DeviceToken  # noqa: E402
from app.services import buzon, deepgram, push, reportes_programados  # noqa: E402


def _ext(numero, voicemail=True):
    return SimpleNamespace(number=numero, voicemail=voicemail, enabled=True)


def test_dialplan_saludo_propio_y_escuchar_por_telefono():
    ctx = ET.Element("context", name="ctx_a")
    config_generator._append_buzon_directo(ctx, [_ext("101"), _ext("102", False)], 7)
    config_generator._append_buzon_grabar_saludo(ctx, [_ext("101"), _ext("102", False)], 7)
    nuevos = {"101": [(5, "/var/lib/freeswitch/recordings/t7/buzon/101/a.wav"),
                      (6, "/var/lib/freeswitch/recordings/t7/buzon/101/b.wav")]}
    config_generator._append_buzon_escuchar(ctx, [_ext("101"), _ext("102", False)], nuevos)
    por_nombre = {e.get("name"): e for e in ctx}

    # El saludo se decide al ejecutarse: el propio si existe, si no el general.
    directo = [f"{a.get('application')} {a.get('data')}" for a in por_nombre["nspbx_buzon_directo"].iter("action")]
    assert "set nspbx_buzon_dir=$${recordings_dir}/t7/buzon/$1" in directo
    lua = next(a for a in directo if a.startswith("lua "))
    assert "/saludo.wav" in lua and "io.open" in lua

    # *98: solo para extensiones con buzón, graba en su carpeta.
    grabar = por_nombre["nspbx_buzon_saludo"]
    conds = grabar.findall("condition")
    assert conds[0].get("expression") == r"^\*98$" and conds[1].get("field") == "${user_name}"
    assert conds[1].get("expression") == "^(101)$"
    assert any(a.get("data", "").startswith("$${recordings_dir}/t7/buzon/$1/saludo.wav 30") for a in grabar.iter("action")
               if a.get("application") == "record")

    # *97: los nuevos de la 101 en orden, marcando cada uno al terminarlo; los demás, «no tienes».
    oir = [f"{a.get('application')} {a.get('data')}" for a in por_nombre["nspbx_buzon_escuchar_101"].iter("action")]
    assert oir.index("playback /var/lib/freeswitch/recordings/t7/buzon/101/a.wav") < oir.index("set nspbx_buzon_oido=5")
    assert oir.index("set nspbx_buzon_oido=5") < oir.index("playback /var/lib/freeswitch/recordings/t7/buzon/101/b.wav")
    nombres = [e.get("name") for e in ctx]
    assert nombres.index("nspbx_buzon_escuchar_101") < nombres.index("nspbx_buzon_escuchar")


async def test_escuchar_por_telefono_marca_los_oidos(cliente, mundo):
    from .conftest import FS_SECRET

    base = f"{settings.fs_recordings_dir}/t{mundo.alfa.id}/buzon/1000"
    async with async_session() as s:
        ms = [MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", ruta=f"{base}/{i}.wav", duracion=3,
                           created_at=datetime(2026, 1, 1, 10, i)) for i in range(3)]
        s.add_all(ms)
        await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                        .values(voicemail=True))
        await s.commit()
    try:
        # El dialplan los lista para *97.
        r = await cliente.get(f"/fs/dialplan?secret={FS_SECRET}")
        assert f"nspbx_buzon_oido={ms[0].id}" in r.text
        # Colgó tras el segundo: el tercero sigue nuevo.
        r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
            "uuid": f"oir-{uuidlib.uuid4()}", "nspbx_tenant_id": str(mundo.alfa.id), "direction": "outbound",
            "billsec": "20", "caller_id_number": "1000", "nspbx_buzon_oido": str(ms[1].id),
        }})
        assert r.status_code == 200
        async with async_session() as s:
            estado = [(await s.get(MensajeBuzon, m.id)).escuchado for m in ms]
        assert estado == [True, True, False]
    finally:
        async with async_session() as s:
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id.in_([m.id for m in ms])))
            await s.execute(update(Extension).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000")
                            .values(voicemail=False))
            await s.commit()


def _wav_bytes(segundos: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * segundos))
    return buf.getvalue()


async def test_saludo_propio_desde_el_panel(cliente, mundo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    asesor = mundo.alfa.cabeceras(permissions.ASESOR)  # extensión 1000
    assert (await cliente.get("/api/buzon/saludo", headers=asesor)).json() == {"extension": "1000", "propio": False, "segundos": None}
    malo = await cliente.post("/api/buzon/saludo", headers=asesor, files={"archivo": ("x.wav", b"no es wav", "audio/wav")})
    assert malo.status_code == 422
    r = await cliente.post("/api/buzon/saludo", headers=asesor, files={"archivo": ("saludo.wav", _wav_bytes(3), "audio/wav")})
    assert r.status_code == 200 and r.json()["segundos"] == 3
    assert (tmp_path / f"t{mundo.alfa.id}" / "buzon" / "1000" / "saludo.wav").exists()
    assert (await cliente.get("/api/buzon/saludo/audio", headers=asesor)).status_code == 200
    # El asesor solo toca el suyo.
    assert (await cliente.get("/api/buzon/saludo?extension=1001", headers=asesor)).status_code == 404
    assert (await cliente.delete("/api/buzon/saludo", headers=asesor)).status_code == 204
    assert (await cliente.get("/api/buzon/saludo", headers=asesor)).json()["propio"] is False


async def test_mensaje_nuevo_se_transcribe_y_avisa_al_celular(mundo, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    carpeta = tmp_path / f"t{mundo.alfa.id}" / "buzon" / "1000"
    carpeta.mkdir(parents=True)
    (carpeta / "m.wav").write_bytes(_wav_bytes(2))
    ruta = f"{settings.fs_recordings_dir.rstrip('/')}/t{mundo.alfa.id}/buzon/1000/m.wav"
    from app.core.database import fijar_tenant
    from app.services.ajustes import ajustes_de

    async with async_session() as s:
        fijar_tenant(s, mundo.alfa.id)
        a = await ajustes_de(s, mundo.alfa.id)
        a.deepgram_api_key = "clave-deepgram-prueba"
        ext_id = (await s.execute(select(Extension.id).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000"))).scalar_one()
        usuario = mundo.alfa.usuarios[permissions.ASESOR]
        token = DeviceToken(tenant_id=mundo.alfa.id, user_id=usuario, extension_id=ext_id, platform="android",
                            token_type="FCM", token="token-android-prueba")
        m = MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", caller_number="3001112222", caller_name="Ana",
                         ruta=ruta, duracion=2)
        s.add_all([token, m])
        await s.commit()

    async def transcribir(audio, clave):
        return [{"rol": "Hablante 1", "texto": "Hola, llámame"}, {"rol": "Hablante 1", "texto": "por favor."}]

    avisos, correos = [], []

    async def aviso(tok, titulo, cuerpo, datos=None):
        avisos.append((tok, titulo, cuerpo, datos))
        return None

    monkeypatch.setattr(deepgram, "transcribir_grabacion", transcribir)
    monkeypatch.setattr(push, "enviar_aviso_android", aviso)
    monkeypatch.setattr(reportes_programados, "correo_configurado", lambda: True)
    monkeypatch.setattr(reportes_programados, "_enviar_smtp", correos.append)
    try:
        await buzon.avisar(mundo.alfa.id, m.id)
        async with async_session() as s:
            assert (await s.get(MensajeBuzon, m.id)).transcripcion == "Hola, llámame por favor."
        assert avisos == [("token-android-prueba", "Mensaje de voz de Ana", "Hola, llámame por favor.",
                           {"tipo": "buzon", "mensaje_id": m.id})]
        assert "Hola, llámame por favor." in correos[0].get_body().get_content()
    finally:
        async with async_session() as s:
            await s.execute(delete(DeviceToken).where(DeviceToken.token == "token-android-prueba"))
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id == m.id))
            a = await ajustes_de(s, mundo.alfa.id)
            await s.commit()
        async with async_session() as s:
            fijar_tenant(s, mundo.alfa.id)
            a = await ajustes_de(s, mundo.alfa.id)
            a.deepgram_api_key = None
            await s.commit()


# --- G5: festivos y fechas especiales ------------------------------------------------------------

from datetime import date as fecha_dia  # noqa: E402

from app.models import FechaEspecial, SystemSettings  # noqa: E402
from app.services import festivos, horario_marcacion  # noqa: E402

_HORARIO = '{"mon": ["08:00", "18:00"], "tue": ["08:00", "18:00"], "wed": ["08:00", "18:00"], "thu": ["08:00", "18:00"], "fri": ["08:00", "18:00"]}'


@pytest.fixture
async def calendario(mundo):
    yield
    async with async_session() as s:
        from .conftest import FECHA_ESPECIAL_SEMBRADA

        await s.execute(delete(FechaEspecial).where(FechaEspecial.fecha != FECHA_ESPECIAL_SEMBRADA))
        await s.execute(update(SystemSettings).values(festivos_cerrado=False))
        await s.commit()
    festivos.invalidar()
    festivos._CACHE.clear()


async def test_festivos_y_fechas_especiales(cliente, mundo, calendario):
    cab = mundo.alfa.cabeceras(permissions.ADMIN)
    cal = (await cliente.get("/api/festivos", headers=cab)).json()
    assert cal["cerrar_festivos"] is False and len(cal["nacionales"]) == 8
    assert (await cliente.put("/api/festivos", headers=cab, json={"cerrar_festivos": True})).status_code == 200
    r = await cliente.post("/api/festivos/especiales", headers=cab,
                           json={"fecha": "2026-12-24", "nombre": "Nochebuena", "franja": "08:00-12:00"})
    assert r.status_code == 201
    assert (await cliente.post("/api/festivos/especiales", headers=cab,
                               json={"fecha": "2026-12-24", "nombre": "Otra"})).status_code == 409
    assert (await cliente.post("/api/festivos/especiales", headers=cab,
                               json={"fecha": "2026-12-30", "nombre": "Mala", "franja": "8 a 12"})).status_code == 422
    await cliente.post("/api/festivos/especiales", headers=cab, json={"fecha": "2026-11-27", "nombre": "Inventario"})
    # Otra empresa no ve ni toca las de alfa.
    beta = (await cliente.get("/api/festivos", headers=mundo.beta.cabeceras(permissions.ADMIN))).json()
    assert [f["nombre"] for f in beta["especiales"]] == [f"Cierre {mundo.beta.marca}"] and beta["cerrar_festivos"] is False
    assert (await cliente.delete(f"/api/festivos/especiales/{r.json()['id']}",
                                 headers=mundo.beta.cabeceras(permissions.ADMIN))).status_code == 404
    # Un asesor no administra el calendario.
    assert (await cliente.get("/api/festivos", headers=mundo.alfa.cabeceras(permissions.ASESOR))).status_code == 403

    await festivos.refrescar(forzar=True)
    a, b = mundo.alfa.id, mundo.beta.id
    martes = datetime(2026, 11, 24, 10, 0)  # día hábil normal
    festivo = datetime(2026, 12, 8, 10, 0)  # Inmaculada Concepción, martes
    assert festivos.abierto(_HORARIO, a, martes) is True
    assert festivos.abierto(_HORARIO, a, festivo) is False and festivos.abierto(_HORARIO, b, festivo) is True
    # Sin horario es 24/7: el festivo no lo cierra.
    assert festivos.abierto(None, a, festivo) is True
    # Fecha cerrada todo el día y con franja.
    assert festivos.abierto(_HORARIO, a, datetime(2026, 11, 27, 10, 0)) is False
    assert festivos.abierto(_HORARIO, a, datetime(2026, 12, 24, 10, 0)) is True
    assert festivos.abierto(_HORARIO, a, datetime(2026, 12, 24, 15, 0)) is False
    assert festivos.motivo_cierre(a, datetime(2026, 11, 27, 10, 0)) == "Inventario"

    # Las campañas: el día cerrado no marca; el 24, solo hasta el mediodía.
    ajustes = SimpleNamespace(tenant_id=a, campaign_hours_weekdays="07:00-19:00", campaign_hours_saturday="08:00-15:00",
                              campaign_sundays_holidays=False)
    assert horario_marcacion.franja(ajustes, None, fecha_dia(2026, 11, 27)) is None
    desde, hasta = horario_marcacion.franja(ajustes, None, fecha_dia(2026, 12, 24))
    assert (desde.hour, hasta.hour) == (8, 12)
    assert horario_marcacion.franja(SimpleNamespace(**{**vars(ajustes), "tenant_id": b}), None, fecha_dia(2026, 11, 27)) is not None


async def test_ruta_entrante_cerrada_por_fecha_especial(cliente, mundo, calendario, monkeypatch):
    from app.models import InboundRoute
    from app.services import config_generator as cg

    async with async_session() as s:
        s.add(FechaEspecial(tenant_id=mundo.alfa.id, fecha=fecha_dia(2026, 11, 27), nombre="Inventario"))
        await s.commit()
    await festivos.refrescar(forzar=True)
    ruta = SimpleNamespace(id=1, name="principal", tenant_id=mundo.alfa.id, did_pattern="6015550000", priority=0, enabled=True,
                           destination_type="extension", destination_value="1000", horario=_HORARIO,
                           fuera_horario_tipo="voicemail", fuera_horario_valor="1000")
    monkeypatch.setattr("app.core.clock.now_local", lambda: datetime(2026, 11, 27, 10, 0))
    publico = ET.Element("context", name="public")
    cg._append_inbound_routes(publico, [ruta], {mundo.alfa.id: "ctx_alfa"}, {mundo.alfa.id: "alfa.test"})
    transfer = publico.find(".//extension[@name='did_1_principal']//action[@application='transfer']").get("data")
    assert transfer == "*991000 XML ctx_alfa"
