"""Fase F: números sin ruta, aviso periódico de la posición en la fila,
desborde a un voizbot, buzón sin audio, topes compartidos y avisos de voz
sin Deepgram."""

import uuid as uuidlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core import cupos, permissions
from app.core.config import settings
from app.core.database import async_session
from app.models import CallLog, CupoUso, MensajeBuzon, NumeroSinRuta, Queue, SecurityAlert, VoiceBot
from app.services import alertas, esl, posicion_colas, sin_ruta, tts, voice_prompts
from app.workers.maintenance import MaintenanceWorker

from .conftest import FS_SECRET

# --- Números sin ruta ------------------------------------------------------------------------


@pytest.fixture
async def limpiar_sin_ruta():
    yield
    async with async_session() as s:
        await s.execute(delete(NumeroSinRuta))
        await s.execute(delete(SecurityAlert).where(SecurityAlert.kind == "numero_sin_ruta"))
        await s.commit()


async def _cdr_sin_ruta(cliente, numero: str, troncal: str | None = None) -> dict:
    variables = {
        "uuid": f"sr-{uuidlib.uuid4()}", "direction": "inbound", "billsec": "0", "hangup_cause": "UNALLOCATED_NUMBER",
        "destination_number": numero, "sip_to_user": numero, "caller_id_number": "3005550000", "nspbx_sin_ruta": "1",
    }
    if troncal:
        variables["sip_gateway_name"] = troncal
    r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": variables})
    assert r.status_code == 200
    return r.json()


async def test_llamada_a_numero_sin_ruta_no_cae_en_una_empresa(cliente, mundo, limpiar_sin_ruta):
    troncal = f"{mundo.beta.slug}_principal"
    assert (await _cdr_sin_ruta(cliente, "6015551234", troncal))["sin_ruta"] is True
    await _cdr_sin_ruta(cliente, "6015551234", troncal)
    async with async_session() as s:
        n = (await s.execute(select(NumeroSinRuta).where(NumeroSinRuta.numero == "6015551234"))).scalar_one()
        # Antes se guardaba como llamada de la primera empresa de la instalación.
        assert not (await s.execute(select(CallLog).where(CallLog.callee_number == "6015551234"))).first()
    assert (n.veces, n.troncal, n.origen) == (2, troncal, "3005550000")

    # La plataforma la ve, con la empresa dueña del proveedor.
    lista = (await cliente.get("/api/plataforma/sin-ruta", headers=mundo.cabeceras_plataforma())).json()
    fila = next(f for f in lista if f["numero"] == "6015551234")
    assert (fila["tenant_id"], fila["veces"]) == (mundo.beta.id, 2)
    # Una empresa no.
    assert (await cliente.get("/api/plataforma/sin-ruta", headers=mundo.alfa.cabeceras(permissions.ADMIN))).status_code == 403

    # Y la empresa dueña del proveedor recibe el aviso; la otra no.
    async with async_session() as s:
        hallazgos = await alertas.detectar_operacion(s)
    avisos = [(tid, d) for tid, tipo, d in hallazgos if tipo == "numero_sin_ruta"]
    assert any(tid == mundo.beta.id and "6015551234" in d for tid, d in avisos)
    assert all(tid != mundo.alfa.id for tid, _ in avisos)

    r = await cliente.delete(f"/api/plataforma/sin-ruta/{fila['id']}", headers=mundo.cabeceras_plataforma())
    assert r.status_code == 204


def test_empresa_de_la_troncal():
    slugs = {1: "acme", 2: "acme_co"}
    assert sin_ruta.empresa_de_troncal("acme_co_principal", slugs) == 2
    assert sin_ruta.empresa_de_troncal("acme_principal", slugs) == 1
    assert sin_ruta.empresa_de_troncal("otra_principal", slugs) is None
    assert sin_ruta.empresa_de_troncal(None, slugs) is None


# --- Posición en la fila ---------------------------------------------------------------------

_MIEMBROS = (
    "queue|instance_id|uuid|session_uuid|cid_number|cid_name|system_epoch|joined_epoch|rejoined_epoch|"
    "bridge_epoch|abandoned_epoch|base_score|skill_score|serving_agent|serving_system|state|score\n"
    "q|i|m1|aaaaaaaa-0000-0000-0000-000000000001|300|A|0|1000|0|0|0|0|0|||Answered|0\n"
    "q|i|m2|aaaaaaaa-0000-0000-0000-000000000002|301|B|0|1010|0|0|0|0|0|||Waiting|0\n"
    "q|i|m3|aaaaaaaa-0000-0000-0000-000000000003|302|C|0|1050|0|0|0|0|0|||Trying|0\n"
    "q|i|m4|no es un uuid; hupall|303|D|0|1060|0|0|0|0|0|||Waiting|0\n"
    "+OK\n"
)


def test_quienes_esperan_en_orden():
    filas = posicion_colas.esperando(_MIEMBROS)
    assert [f["session_uuid"][-1] for f in filas] == ["2", "3"]


@pytest.fixture
def avisos_de_voz(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    carpeta = tmp_path / voice_prompts.PROMPTS_DIR
    carpeta.mkdir()
    for k in ("cola_aviso", "cola_delante_0", "cola_delante_1"):
        (carpeta / f"{k}.wav").write_bytes(b"RIFF")
    (carpeta / "cola_delante_mas.mp3").write_bytes(b"ID3")
    return carpeta


def test_audio_de_la_posicion(avisos_de_voz):
    assert posicion_colas.audio_de(1) == (
        f"file_string://{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/cola_aviso.wav"
        f"!{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/cola_delante_1.wav"
    )
    # Más de nueve: la frase «más de nueve» (acá, la de edge-tts en MP3).
    assert posicion_colas.audio_de(12).endswith("/prompts/cola_delante_mas.mp3")
    # Sin la frase de la posición, al menos «gracias por esperar».
    assert posicion_colas.audio_de(5) == f"{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/cola_aviso.wav"


@pytest.fixture
async def grupo_con_posicion(mundo):
    async with async_session() as s:
        q = Queue(tenant_id=mundo.alfa.id, name="fila_f", extension="8611", strategy="ring-all", agents="[]",
                  announce_position=True, enabled=True)
        s.add(q)
        await s.commit()
    yield q
    async with async_session() as s:
        await s.execute(delete(Queue).where(Queue.id == q.id))
        await s.commit()


async def test_anuncia_la_posicion_cada_tanto(monkeypatch, mundo, grupo_con_posicion, avisos_de_voz):
    comandos = []

    async def api(cmd, tenant_id=None, **kw):
        comandos.append((cmd, tenant_id))
        return _MIEMBROS if cmd.startswith("callcenter_config") else "+OK"

    monkeypatch.setattr(esl, "api", api)
    a = posicion_colas.Anunciador()
    # Recién llegados: todavía no (al entrar ya se les dijo).
    assert await a.ciclo(ahora=1030) == 0
    assert comandos[0] == (f"callcenter_config queue list members fila_f@{mundo.alfa.dominio}", mundo.alfa.id)
    # El primero que espera ya pasó PRIMERA_SEG: «eres el siguiente».
    comandos.clear()
    assert await a.ciclo(ahora=1010 + posicion_colas.PRIMERA_SEG) == 1
    difusion = [c for c, _ in comandos if c.startswith("uuid_broadcast")]
    assert difusion == [
        "uuid_broadcast aaaaaaaa-0000-0000-0000-000000000002 file_string://"
        f"{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/cola_aviso.wav!{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/cola_delante_0.wav aleg"
    ]
    # Al ratito no se repite; a los CADA_SEG, sí (y al segundo le toca «hay una persona»).
    assert await a.ciclo(ahora=1010 + posicion_colas.PRIMERA_SEG + 5) == 0
    comandos.clear()
    assert await a.ciclo(ahora=1050 + posicion_colas.PRIMERA_SEG + posicion_colas.CADA_SEG) == 2
    assert any("000000000003" in c and "cola_delante_1.wav" in c for c, _ in comandos)
    # Lo que no es un uuid nunca llega a un comando.
    assert not any("hupall" in c for c, _ in comandos if c.startswith("uuid_broadcast"))


# --- Desborde a un voizbot -------------------------------------------------------------------


async def test_un_grupo_puede_desbordar_a_un_voizbot(cliente, mundo):
    cab = mundo.alfa.cabeceras(permissions.ADMIN)
    async with async_session() as s:
        propio = VoiceBot(tenant_id=mundo.alfa.id, name="recepcion_f", bot_type="ivr", enabled=True)
        ajeno = VoiceBot(tenant_id=mundo.beta.id, name="ajeno_f", bot_type="ivr", enabled=True)
        s.add_all([propio, ajeno])
        await s.commit()
    try:
        cuerpo = {"name": "desborde_bot", "extension": "8612", "agents": [], "failover_extension": f"bot_{ajeno.id}"}
        r = await cliente.post("/api/queues", headers=cab, json=cuerpo)
        assert r.status_code == 400, r.text
        r = await cliente.post("/api/queues", headers=cab, json={**cuerpo, "failover_extension": f"bot_{propio.id}"})
        assert r.status_code == 201, r.text
        assert r.json()["failover_extension"] == f"bot_{propio.id}"
        assert (await cliente.delete(f"/api/queues/{r.json()['id']}", headers=cab)).status_code in (200, 204)
    finally:
        async with async_session() as s:
            await s.execute(delete(Queue).where(Queue.name == "desborde_bot"))
            await s.execute(delete(VoiceBot).where(VoiceBot.id.in_([propio.id, ajeno.id])))
            await s.commit()


# --- Buzón sin audio -------------------------------------------------------------------------


async def test_el_mantenimiento_borra_mensajes_sin_audio(mundo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    base = f"{settings.fs_recordings_dir.rstrip('/')}/t{mundo.alfa.id}/buzon/1000"
    vivo = tmp_path / f"t{mundo.alfa.id}" / "buzon" / "1000" / "vivo.wav"
    vivo.parent.mkdir(parents=True)
    vivo.write_bytes(b"RIFF")
    viejo = datetime.utcnow() - timedelta(days=2)
    async with async_session() as s:
        filas = [
            MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", ruta=f"{base}/vivo.wav", created_at=viejo),
            MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", ruta=f"{base}/borrado.wav", created_at=viejo),
            # Recién creado: el CDR puede llegar antes de que el disco lo muestre; no se toca.
            MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", ruta=f"{base}/nuevo.wav"),
        ]
        s.add_all(filas)
        await s.commit()
    try:
        assert await MaintenanceWorker()._purgar_buzones_sin_audio() == 1
        async with async_session() as s:
            quedan = {m.ruta.rsplit("/", 1)[-1] for m in (await s.execute(
                select(MensajeBuzon).where(MensajeBuzon.id.in_([f.id for f in filas])))).scalars()}
        assert quedan == {"vivo.wav", "nuevo.wav"}
        # Sin la carpeta de grabaciones montada no se borra nada.
        monkeypatch.setattr(settings, "recordings_dir", str(tmp_path / "no-existe"))
        assert await MaintenanceWorker()._purgar_buzones_sin_audio() == 0
    finally:
        async with async_session() as s:
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id.in_([f.id for f in filas])))
            await s.commit()


# --- Topes compartidos -----------------------------------------------------------------------


async def test_el_tope_es_uno_solo_para_todas_las_replicas():
    clave = f"prueba:{uuidlib.uuid4()}"
    try:
        assert [await cupos.consumir(clave, 2, ahora=600.0) for _ in range(2)] == [0, 0]
        # El tercero en la misma ventana espera hasta la próxima.
        assert await cupos.consumir(clave, 2, ahora=630.0) == 31
        # Ventana nueva: vuelve a contar desde uno.
        assert await cupos.consumir(clave, 2, ahora=660.0) == 0
        with pytest.raises(HTTPException) as exc:
            for _ in range(5):
                await cupos.exigir(clave, 2)
        assert exc.value.status_code == 429 and "Retry-After" in exc.value.headers
    finally:
        async with async_session() as s:
            await s.execute(delete(CupoUso).where(CupoUso.clave == clave))
            await s.commit()


async def test_el_asistente_usa_el_tope_compartido(cliente, mundo, monkeypatch):
    llamadas = []

    async def exigir(clave, maximo, ventana_seg=60, mensaje=""):
        llamadas.append(clave)
        raise HTTPException(429, mensaje)

    monkeypatch.setattr(cupos, "exigir", exigir)
    cab = mundo.alfa.cabeceras(permissions.ADMIN)
    r = await cliente.post("/api/assistant/chat", headers=cab, json={"messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 429 and llamadas == [f"asistente:{mundo.alfa.usuarios[permissions.ADMIN]}"]


# --- Avisos de voz sin Deepgram --------------------------------------------------------------


async def test_avisos_con_voz_gratis_sin_deepgram(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    monkeypatch.setattr(voice_prompts, "_TEXTOS", {"uno": "Uno.", "dos": "Dos."})

    async def sin_clave(session, tenant_id):
        return ""

    usadas = []

    async def sintetizar(texto, voz):
        usadas.append(voz)
        return b"ID3" + texto.encode()

    monkeypatch.setattr(voice_prompts, "_clave_deepgram", sin_clave)
    monkeypatch.setattr(tts, "synthesize", sintetizar)
    async with async_session() as s:
        assert await voice_prompts.ensure_prompts(s) == 2
        assert await voice_prompts.ensure_prompts(s) == 0  # ya están
    assert usadas == [voice_prompts._VOZ_GRATIS] * 2
    assert voice_prompts.prompt_path("uno") == f"{voice_prompts.FS_SIDE_SOUNDS_DIR}/prompts/uno.mp3"
    assert (Path(tmp_path) / "prompts" / "dos.mp3").read_bytes() == b"ID3Dos."


async def test_sin_internet_no_insiste(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    monkeypatch.setattr(voice_prompts, "_TEXTOS", {"uno": "Uno.", "dos": "Dos."})
    intentos = []

    async def sin_clave(session, tenant_id):
        return ""

    async def falla(texto, voz):
        intentos.append(texto)
        raise OSError("sin red")

    monkeypatch.setattr(voice_prompts, "_clave_deepgram", sin_clave)
    monkeypatch.setattr(tts, "synthesize", falla)
    async with async_session() as s:
        assert await voice_prompts.ensure_prompts(s) == 0
    assert intentos == ["Uno."] and voice_prompts.prompt_path("uno") is None
