"""Fase A de la auditoría: buzón de voz, número entrante tolerante al
formato, y grupos de atención que no dejan a nadie en silencio."""

import asyncio
import uuid as uuidlib
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core import permissions, validacion
from app.core.config import settings
from app.core.database import async_session
from app.models import CallLog, Extension, MensajeBuzon
from app.services import buzon, musica_espera, queues_sync, reportes_programados, voice_prompts
from app.services.numeros import numero_a_palabras

from .conftest import FS_SECRET


async def _dialplan(cliente) -> ET.Element:
    resp = await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})
    assert resp.status_code == 200, resp.text[:300]
    return ET.fromstring(resp.text)


async def _extension(tenant_id: int, numero: str, voicemail: bool) -> None:
    async with async_session() as s:
        existe = (
            await s.execute(select(Extension).where(Extension.tenant_id == tenant_id, Extension.number == numero))
        ).scalar_one_or_none()
        if existe is None:
            s.add(Extension(tenant_id=tenant_id, number=numero, password="clave-sip-larga-de-prueba", voicemail=voicemail))
        else:
            existe.voicemail = voicemail
        await s.commit()


def _wav(tenant_id: int, ext: str, segundos: float, nombre: str | None = None) -> tuple[str, Path]:
    """(ruta como la ve FreeSWITCH, ruta local) de un mensaje de prueba."""
    relativa = f"t{tenant_id}/buzon/{ext}/{nombre or uuidlib.uuid4().hex}.wav"
    local = Path(settings.recordings_dir) / relativa
    local.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(local), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * int(8000 * segundos))
    return f"{settings.fs_recordings_dir}/{relativa}", local


async def _cdr(cliente, tenant_id: int, **variables) -> str:
    u = f"vm-{uuidlib.uuid4()}"
    base = {
        "uuid": u, "nspbx_tenant_id": str(tenant_id), "direction": "inbound", "billsec": "9",
        "hangup_cause": "NORMAL_CLEARING", "caller_id_number": "3005550000", "caller_id_name": "Juan Cliente",
    }
    r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {**base, **variables}})
    assert r.status_code == 200, r.text
    return u


# --- Dialplan ------------------------------------------------------------------


async def test_sin_contestar_va_al_buzon_solo_si_la_extension_lo_tiene(cliente, mundo):
    await _extension(mundo.alfa.id, "4701", True)
    await _extension(mundo.alfa.id, "4702", False)
    ctx = (await _dialplan(cliente)).find(f".//context[@name='ctx_{mundo.alfa.slug}']")

    local = ctx.find("extension[@name='Local_Extension']")
    condiciones = local.findall("condition")
    con_buzon = [c for c in condiciones if c.find("action[@application='record']") is not None]
    assert len(con_buzon) == 1
    expresion = con_buzon[0].get("expression")
    assert "4701" in expresion and "4702" not in expresion
    assert con_buzon[0].get("break") == "never"
    acciones = [f"{a.get('application')} {a.get('data')}" for a in con_buzon[0]]
    assert "set nspbx_buzon_ext=${destination_number}" in acciones
    assert any(a.startswith(f"set nspbx_buzon=$${{recordings_dir}}/t{mundo.alfa.id}/buzon/") for a in acciones)
    assert any(a.startswith("record ${nspbx_buzon} ") for a in acciones)
    # El timbrado dura lo razonable antes de pasar al buzón.
    assert any(a.get("data") == "call_timeout=30" for a in local.iter("action"))
    # Sin buzón, se cuelga como antes (la última condición).
    assert condiciones[-1].find("action[@application='hangup']").get("data") == "NO_ANSWER"

    directo = ctx.find("extension[@name='nspbx_buzon_directo']")
    exp = directo.find("condition").get("expression")
    assert exp.startswith(r"^\*99(") and "4701" in exp and "4702" not in exp
    sets = [a.get("data") for a in directo.iter("action") if a.get("application") == "set"]
    assert f"nspbx_tenant_id={mundo.alfa.id}" in sets and "nspbx_buzon_ext=$1" in sets

    # «No molestar» también deja mensaje si hay buzón.
    dnd = ctx.find("extension[@name='nspbx_dnd_cortar']")
    assert any("4701" in (c.get("expression") or "") and c.find("action[@application='record']") is not None
               for c in dnd.findall("condition"))


async def test_ruta_entrante_al_buzon_y_did_en_cualquier_formato(cliente, mundo):
    await _extension(mundo.alfa.id, "4701", True)
    cab = mundo.alfa.cabeceras()
    r = await cliente.post("/api/inbound-routes", headers=cab, json={
        "name": "buzon-alfa", "did_pattern": "+57 601 555-0101", "destination_type": "voicemail",
        "destination_value": "4701",
    })
    assert r.status_code == 201, r.text
    assert r.json()["did_pattern"] == "6015550101"
    # El mismo número escrito de otra forma es la MISMA ruta.
    dup = await cliente.post("/api/inbound-routes", headers=cab, json={
        "name": "otra", "did_pattern": "576015550101", "destination_type": "extension", "destination_value": "1000",
    })
    assert dup.status_code == 409
    mal = await cliente.post("/api/inbound-routes", headers=cab, json={
        "name": "mal", "did_pattern": "6015550102", "destination_type": "voicemail", "destination_value": "bot_1",
    })
    assert mal.status_code == 422

    public = (await _dialplan(cliente)).find(".//context[@name='public']")
    destino = f"*994701 XML ctx_{mundo.alfa.slug}"
    por_campo = {}
    for ext in public.findall("extension"):
        cond = ext.find("condition")
        transfer = ext.find(".//action[@application='transfer']")
        if transfer is not None and transfer.get("data") == destino:
            por_campo[cond.get("field")] = cond.get("expression")
    esperado = r"^(?:\+?57)?6015550101$"
    assert por_campo == {"destination_number": esperado, "${sip_to_user}": esperado}
    # Los exactos (número marcado y To) van antes que el «cualquier número».
    nombres = [e.get("name") for e in public.findall("extension")]
    assert nombres[-1] == "no_route"


def test_did_canonico_y_expresion():
    for escrito in ("+576011234567", "576011234567", "601 123 4567", "601-123-4567"):
        assert validacion.did_canonico(escrito) == "6011234567"
    assert validacion.did_canonico("+18005551234") == "+18005551234"
    import re

    exp = validacion.expresion_did("6011234567")
    for llega in ("+576011234567", "576011234567", "6011234567"):
        assert re.fullmatch(exp.strip("^$"), llega)
    assert not re.match(exp, "16011234567") and not re.match(exp, "60112345678")
    assert validacion.expresion_did("12345") == r"^\+?12345$"
    assert validacion.expresion_did("*77") == r"^\*77$"


# --- CDR: guardar el mensaje ---------------------------------------------------


async def test_cdr_del_buzon_guarda_el_mensaje(cliente, mundo):
    ruta, local = _wav(mundo.alfa.id, "1000", 3.0)
    u = await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon=ruta)
    async with async_session() as s:
        llamada = (await s.execute(select(CallLog).where(CallLog.uuid == u))).scalar_one()
        mensaje = (await s.execute(select(MensajeBuzon).where(MensajeBuzon.call_uuid == u))).scalar_one()
    assert llamada.status == "voicemail"
    assert (mensaje.tenant_id, mensaje.extension, mensaje.duracion) == (mundo.alfa.id, "1000", 3)
    assert (mensaje.caller_number, mensaje.caller_name, mensaje.escuchado) == ("3005550000", "Juan Cliente", False)
    assert local.exists()


async def test_cdr_del_buzon_descarta_vacios_y_rutas_ajenas(cliente, mundo):
    # Colgó al oír el saludo: no hay mensaje y el archivo se borra.
    ruta, local = _wav(mundo.alfa.id, "1000", 0.5)
    u = await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon=ruta)
    # Ruta en la carpeta de OTRA empresa, o de otra extensión: no se toma.
    ajena, _ = _wav(mundo.beta.id, "1000", 3.0)
    u2 = await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon=ajena)
    otra_ext, _ = _wav(mundo.alfa.id, "4701", 3.0)
    u3 = await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon=otra_ext)
    u4 = await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon="/etc/passwd")
    async with async_session() as s:
        hay = (await s.execute(select(MensajeBuzon).where(MensajeBuzon.call_uuid.in_([u, u2, u3, u4])))).scalars().all()
    assert hay == []
    assert not local.exists()


async def test_aviso_por_correo_con_el_audio(mundo, monkeypatch):
    ruta, _ = _wav(mundo.alfa.id, "1000", 2.5)
    async with async_session() as s:
        m = MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", call_uuid=f"vm-{uuidlib.uuid4()}",
                         caller_number="3001112222", caller_name="Ana", ruta=ruta, duracion=3)
        s.add(m)
        await s.commit()
    enviados = []
    monkeypatch.setattr(reportes_programados, "correo_configurado", lambda: True)
    monkeypatch.setattr(reportes_programados, "_enviar_smtp", enviados.append)
    await buzon.avisar(mundo.alfa.id, m.id)
    assert len(enviados) == 1
    correo = enviados[0]
    # La extensión 1000 es la del asesor sembrado.
    assert correo["To"] == f"{permissions.ASESOR}@{mundo.alfa.marca}.test"
    assert "Ana" in correo["Subject"]
    adjuntos = [p for p in correo.iter_attachments()]
    assert [a.get_content_type() for a in adjuntos] == ["audio/wav"]


# --- API -----------------------------------------------------------------------


async def test_cada_quien_ve_su_buzon_y_quien_ve_todo_ve_todos(cliente, mundo):
    await _extension(mundo.alfa.id, "4701", True)
    propio, local_propio = _wav(mundo.alfa.id, "1000", 2.5)
    ajeno, _ = _wav(mundo.alfa.id, "4701", 2.5)
    await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="1000", nspbx_buzon=propio)
    await _cdr(cliente, mundo.alfa.id, nspbx_buzon_ext="4701", nspbx_buzon=ajeno)

    asesor = mundo.alfa.cabeceras(permissions.ASESOR)
    lista = (await cliente.get("/api/buzon", headers=asesor)).json()
    assert lista and {m["extension"] for m in lista} == {"1000"}
    todos = (await cliente.get("/api/buzon", headers=mundo.alfa.cabeceras())).json()
    assert {"1000", "4701"} <= {m["extension"] for m in todos}
    del_4701 = next(m for m in todos if m["extension"] == "4701")
    assert (await cliente.get(f"/api/buzon/{del_4701['id']}/audio", headers=asesor)).status_code == 404

    mio = max(lista, key=lambda m: m["id"])  # el que se acaba de dejar
    assert mio["duracion"] == 2 and not mio["escuchado"]
    antes = (await cliente.get("/api/buzon/resumen", headers=asesor)).json()["sin_escuchar"]
    audio = await cliente.get(f"/api/buzon/{mio['id']}/audio", headers=asesor)
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    r = await cliente.put(f"/api/buzon/{mio['id']}", headers=asesor, json={"escuchado": True})
    assert r.status_code == 200 and r.json()["escuchado"] is True
    assert (await cliente.get("/api/buzon/resumen", headers=asesor)).json()["sin_escuchar"] == antes - 1
    sin_escuchar = (await cliente.get("/api/buzon?sin_escuchar=true", headers=asesor)).json()
    assert mio["id"] not in {m["id"] for m in sin_escuchar}

    # Borrar quita también el audio del disco.
    assert local_propio.exists()
    assert (await cliente.delete(f"/api/buzon/{mio['id']}", headers=asesor)).status_code == 204
    assert not local_propio.exists()
    assert (await cliente.get(f"/api/buzon/{mio['id']}/audio", headers=asesor)).status_code == 404


# --- Grupos de atención --------------------------------------------------------


def _cola(**kw):
    base = dict(id=1, tenant_id=1, name="ventas", extension="8000", strategy="ring-all", moh_sound="$${hold_music}",
                agents='["101"]', max_wait_time=60, max_wait_time_with_no_agent=0, agent_ring_timeout=20,
                max_no_answer=3, wrap_up_time=10, record=False, failover_extension="*99101",
                announce_position=True, enabled=True)
    return SimpleNamespace(**{**base, **kw})


def test_cola_con_aviso_y_posicion(monkeypatch):
    carpeta = Path(settings.fs_sounds_dir) / voice_prompts.PROMPTS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "cola_aviso.wav").write_bytes(b"RIFF")
    xml = ET.fromstring(queues_sync.build_callcenter_xml([_cola()], {1: "a.test"}))
    params = {p.get("name"): p.get("value") for p in xml.iter("param")}
    # El aviso periódico lo manda services/vigia_colas.py (con la posición),
    # no el grupo: sonaría dos veces.
    assert "announce-sound" not in params
    assert params["max-wait-time"] == "60"

    from app.services import config_generator

    ctx = ET.Element("context", name="ctx_a")
    config_generator._append_queue_routes(ctx, [_cola()], "a.test")
    acciones = [a.get("application") for a in ctx.iter("action")]
    # Posición antes de entrar a la fila; al salir sin atender, al buzón.
    assert acciones.index("lua") < acciones.index("callcenter")
    assert ctx.find(".//action[@application='transfer']").get("data") == "*99101 XML ctx_a"
    lua = ctx.find(".//action[@application='lua']").get("data")
    assert lua.startswith("~") and "callcenter_config queue list members" in lua and "cola_delante_" in lua


def test_musica_de_espera(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    monkeypatch.setattr(musica_espera, "FRECUENCIAS", (8000,))
    assert musica_espera.asegurar() is True
    ruta = tmp_path / "music" / "8000" / musica_espera.NOMBRE
    with wave.open(str(ruta)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (8000, 1, 2)
        assert 20 < w.getnframes() / 8000 < 40
    # Ya existe: no se vuelve a escribir.
    assert musica_espera.asegurar() is False


def test_avisos_de_voz_nuevos():
    textos = voice_prompts._TEXTOS
    assert "buzon_saludo" in textos and "cola_aviso" in textos
    assert textos["cola_delante_3"] == "Hay tres personas antes que tú."
    assert {f"cola_delante_{n}" for n in range(10)} | {"cola_delante_mas"} <= set(textos)


@pytest.mark.parametrize("n,texto", [(1, "uno"), (7, "siete"), (105, "ciento cinco"), (2007, "dos mil siete")])
def test_numeros_de_una_cifra_en_palabras(n, texto):
    assert numero_a_palabras(n) == texto


async def test_el_aviso_no_rompe_si_no_hay_correo(mundo):
    # Sin SMTP configurado: no hace nada ni lanza.
    await asyncio.wait_for(buzon.avisar(mundo.alfa.id, 999999), timeout=5)
