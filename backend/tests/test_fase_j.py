"""Fase J: verificación en vivo, errores del panel y la app, calidad de
audio, retención de grabaciones y preguntas sin guía."""

import uuid as uuidlib
from datetime import datetime, timedelta

from sqlalchemy import delete

from app.core import permissions
from app.core.database import async_session
from app.models import AuditLog, CallLog, VerificacionVivo
from app.services import verificacion

# --- J1: verificación en vivo --------------------------------------------------------------


async def _limpiar_verificaciones(tenant_id: int):
    async with async_session() as s:
        await s.execute(delete(VerificacionVivo).where(VerificacionVivo.empresa_id == tenant_id))
        await s.commit()


def test_cada_prueba_tiene_pasos_y_clave_unica():
    claves = [p.clave for p in verificacion.PRUEBAS]
    assert len(claves) == len(set(claves))
    assert all(p.pasos and p.titulo for p in verificacion.PRUEBAS)


async def test_solo_la_plataforma_verifica(cliente, mundo):
    r = await cliente.get(f"/api/plataforma/verificacion?tenant_id={mundo.alfa.id}", headers=mundo.alfa.cabeceras(permissions.ADMIN))
    assert r.status_code == 403


async def test_la_saliente_se_comprueba_con_el_cdr(cliente, mundo):
    plataforma = mundo.cabeceras_plataforma()
    await _limpiar_verificaciones(mundo.alfa.id)
    try:
        lista = (await cliente.get(f"/api/plataforma/verificacion?tenant_id={mundo.alfa.id}", headers=plataforma)).json()
        assert {p["clave"] for p in lista} == set(verificacion.POR_CLAVE) and all(p["ultima"] is None for p in lista)
        v = (await cliente.post("/api/plataforma/verificacion", headers=plataforma,
                                json={"tenant_id": mundo.alfa.id, "clave": "saliente"})).json()
        assert v["estado"] == "en_curso"
        r = (await cliente.post(f"/api/plataforma/verificacion/{v['id']}/comprobar", headers=plataforma)).json()
        assert r["encontrada"] is False and r["estado"] == "en_curso"

        # Una saliente por el proveedor, contestada, después de empezar.
        async with async_session() as s:
            s.add(CallLog(tenant_id=mundo.alfa.id, uuid=f"j1-{uuidlib.uuid4()}", direction="outbound", status="answered",
                          caller_number="1000", callee_number="3001234567", billsec=12, via_trunk=True,
                          started_at=datetime.utcnow() + timedelta(seconds=1)))
            await s.commit()
        r = (await cliente.post(f"/api/plataforma/verificacion/{v['id']}/comprobar", headers=plataforma)).json()
        assert r["encontrada"] is True and r["estado"] == "ok" and "3001234567" in r["evidencia"]
        lista = (await cliente.get(f"/api/plataforma/verificacion?tenant_id={mundo.alfa.id}", headers=plataforma)).json()
        assert next(p for p in lista if p["clave"] == "saliente")["ultima"]["estado"] == "ok"
    finally:
        await _limpiar_verificaciones(mundo.alfa.id)


async def test_la_transferencia_se_comprueba_con_la_auditoria(mundo):
    desde = datetime.utcnow() - timedelta(seconds=1)
    async with async_session() as s:
        assert await verificacion.comprobar(s, "transferencia_directa", mundo.alfa.id, desde) is None
        s.add(AuditLog(tenant_id=mundo.alfa.id, actor="ana (asesor)", action="POST /api/llamada/transferir", result="ok",
                       created_at=datetime.utcnow()))
        # La de otra empresa no cuenta.
        s.add(AuditLog(tenant_id=mundo.beta.id, actor="x", action="POST /api/llamada/transferencia/completar", result="ok",
                       created_at=datetime.utcnow()))
        await s.commit()
        assert "ana" in (await verificacion.comprobar(s, "transferencia_directa", mundo.alfa.id, desde) or "")
        assert await verificacion.comprobar(s, "transferencia_consultada", mundo.alfa.id, desde) is None


async def test_las_manuales_se_cierran_a_mano(cliente, mundo):
    plataforma = mundo.cabeceras_plataforma()
    await _limpiar_verificaciones(mundo.alfa.id)
    try:
        v = (await cliente.post("/api/plataforma/verificacion", headers=plataforma,
                                json={"tenant_id": mundo.alfa.id, "clave": "musica_posicion"})).json()
        assert (await cliente.post(f"/api/plataforma/verificacion/{v['id']}/resultado", headers=plataforma,
                                   json={"estado": "raro"})).status_code == 422
        r = await cliente.post(f"/api/plataforma/verificacion/{v['id']}/resultado", headers=plataforma,
                               json={"estado": "fallo", "nota": "No dijo la posición"})
        assert r.json()["estado"] == "fallo" and r.json()["nota"] == "No dijo la posición"
        assert (await cliente.post("/api/plataforma/verificacion", headers=plataforma,
                                   json={"tenant_id": mundo.alfa.id, "clave": "no-existe"})).status_code == 422
    finally:
        await _limpiar_verificaciones(mundo.alfa.id)


# --- J3: errores del panel y la app ----------------------------------------------------------

from app.models import ErrorCliente  # noqa: E402
from app.services import errores_cliente  # noqa: E402


def test_se_limpian_tokens_y_numeros():
    t = errores_cliente.limpiar(
        "fallo con Bearer abc.def y token=xyz123 para 3001234567 eyJhbGciOi.eyJzdWIiOjF9.firma en /api/x?clave=sec", 300
    )
    assert "abc.def" not in t and "xyz123" not in t and "3001234567" not in t and "eyJhbGciOi" not in t and "sec" not in t
    # La firma no cambia por números ni líneas.
    f1 = errores_cliente.firma("panel", "No existe la campaña 12", "at f (a.js:10:5)")
    f2 = errores_cliente.firma("panel", "No existe la campaña 99", "at f (a.js:88:1)")
    assert f1 == f2 != errores_cliente.firma("app", "No existe la campaña 12", "at f (a.js:10:5)")


async def test_los_errores_se_agrupan_y_los_ve_la_plataforma(cliente, mundo):
    async with async_session() as s:
        await s.execute(delete(ErrorCliente))
        await s.commit()
    asesor = mundo.alfa.cabeceras(permissions.ASESOR)
    admin = mundo.alfa.cabeceras(permissions.ADMIN)
    cuerpo = {"origen": "panel", "mensaje": "TypeError: x is undefined", "pila": "TypeError\n at Ficha (ficha.js:12:3)",
              "ruta": "/calls?token=secreto"}
    try:
        assert (await cliente.post("/api/errores", json=cuerpo)).status_code == 401  # sin sesión, no
        assert (await cliente.post("/api/errores", headers=asesor, json=cuerpo)).status_code == 204
        assert (await cliente.post("/api/errores", headers=asesor, json=cuerpo)).status_code == 204
        assert (await cliente.post("/api/errores", headers=admin, json=cuerpo)).status_code == 204
        assert (await cliente.post("/api/errores", headers=asesor, json={**cuerpo, "origen": "otro"})).status_code == 422
        # Solo la plataforma los lee.
        assert (await cliente.get("/api/plataforma/errores", headers=admin)).status_code == 403
        plataforma = mundo.cabeceras_plataforma()
        lista = (await cliente.get("/api/plataforma/errores", headers=plataforma)).json()
        assert len(lista) == 1
        e = lista[0]
        assert (e["veces"], e["usuarios"], e["ruta"], e["empresa"]) == (3, 2, "/calls", "Empresa alfa")
        assert (await cliente.put(f"/api/plataforma/errores/{e['id']}/resuelto", headers=plataforma)).status_code == 204
        assert (await cliente.get("/api/plataforma/errores", headers=plataforma)).json() == []
        # Vuelve a pasar: reaparece.
        await cliente.post("/api/errores", headers=asesor, json=cuerpo)
        assert len((await cliente.get("/api/plataforma/errores", headers=plataforma)).json()) == 1
    finally:
        async with async_session() as s:
            await s.execute(delete(ErrorCliente))
            await s.commit()


# --- J2: calidad de audio por llamada ------------------------------------------------------

from app.services import calidad_audio  # noqa: E402


def test_calidad_desde_las_variables_del_cdr():
    d = calidad_audio.de_cdr({"rtp_audio_in_mos": "4.21", "rtp_audio_in_quality_percentage": "98.5",
                              "rtp_audio_in_packet_count": "990", "rtp_audio_in_skip_packet_count": "10",
                              "sip_gateway_name": "proveedor_a"})
    assert d == {"audio_mos": 4.21, "audio_calidad": 98.5, "audio_perdida": 1.0, "troncal": "proveedor_a"}
    # Sin medir (llamada no contestada) o basura: nada.
    assert calidad_audio.de_cdr({}) == {"audio_mos": None, "audio_calidad": None, "audio_perdida": None, "troncal": None}
    assert calidad_audio.de_cdr({"rtp_audio_in_mos": "nan"})["audio_mos"] is None
    assert calidad_audio.de_cdr({"rtp_audio_in_mos": "0"})["audio_mos"] is None


async def test_el_cdr_guarda_el_audio_y_el_reporte_lo_agrupa(cliente, mundo):
    from .conftest import FS_SECRET

    uuids = [f"j2-{uuidlib.uuid4()}" for _ in range(3)]
    base = {"nspbx_tenant_id": str(mundo.alfa.id), "direction": "outbound", "billsec": "30", "caller_id_number": "1000",
            "destination_number": "3001234567", "hangup_cause": "NORMAL_CLEARING"}
    try:
        for uuid, mos, gw in zip(uuids, ("4.4", "2.9", "4.1"), ("prov_a", "prov_b", "prov_a")):
            r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
                **base, "uuid": uuid, "rtp_audio_in_mos": mos, "sip_gateway_name": gw,
                "start_uepoch": str(int(datetime.utcnow().timestamp() * 1_000_000)),
            }})
            assert r.status_code == 200
        admin = mundo.alfa.cabeceras(permissions.ADMIN)
        hoy = datetime.utcnow().date().isoformat()
        rep = (await cliente.get(f"/api/reportes/audio?desde={hoy}&hasta={hoy}", headers=admin)).json()
        por = {f["clave"]: f for f in rep["por_troncal"]}
        assert por["prov_b"]["malas"] == 1 and por["prov_b"]["mos"] == 2.9
        assert por["prov_a"]["llamadas"] >= 2 and por["prov_a"]["malas"] == 0
        # El peor primero.
        assert rep["por_troncal"][0]["clave"] == "prov_b"
        # Otra empresa no ve estas llamadas.
        beta = (await cliente.get(f"/api/reportes/audio?desde={hoy}&hasta={hoy}", headers=mundo.beta.cabeceras(permissions.ADMIN))).json()
        assert not any(f["clave"] in ("prov_a", "prov_b") for f in beta["por_troncal"])
    finally:
        async with async_session() as s:
            await s.execute(delete(CallLog).where(CallLog.uuid.in_(uuids)))
            await s.commit()


# --- J4: retención de lo que se habló, conservar y aviso -------------------------------------

import os  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models import MensajeBuzon  # noqa: E402
from app.services import retencion  # noqa: E402
from app.workers.maintenance import MaintenanceWorker  # noqa: E402


def _viejo(ruta, dias):
    t = (datetime.utcnow() - timedelta(days=dias)).timestamp()
    os.utime(ruta, (t, t))


async def test_la_retencion_borra_lo_hablado_salvo_lo_conservado(mundo, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    monkeypatch.setattr(settings, "fs_recordings_dir", "/var/lib/freeswitch/recordings")
    monkeypatch.setattr("app.api.calls.RECORDINGS_DIR", str(tmp_path))
    carpeta = tmp_path / f"t{mundo.alfa.id}" / "2026" / "01" / "01"
    carpeta.mkdir(parents=True)
    for nombre in ("vieja.wav", "conservada.wav", "nueva.wav"):
        (carpeta / nombre).write_bytes(b"RIFF")
    saludo = tmp_path / f"t{mundo.alfa.id}" / "buzon" / "1000" / "saludo.wav"
    saludo.parent.mkdir(parents=True)
    saludo.write_bytes(b"RIFF")
    for f in (carpeta / "vieja.wav", carpeta / "conservada.wav", saludo):
        _viejo(f, 200)
    _viejo(carpeta / "nueva.wav", 87)  # se borra en 3 días con 90 de retención

    ruta_fs = f"/var/lib/freeswitch/recordings/t{mundo.alfa.id}/2026/01/01"
    hace = datetime.utcnow() - timedelta(days=200)
    async with async_session() as s:
        vieja = CallLog(tenant_id=mundo.alfa.id, uuid=f"j4-{uuidlib.uuid4()}", direction="inbound", status="answered",
                        started_at=hace, recording_path=f"{ruta_fs}/vieja.wav", summary="Pidió un crédito",
                        transcripcion=[{"rol": "Hablante 1", "texto": "hola"}])
        guardada = CallLog(tenant_id=mundo.alfa.id, uuid=f"j4-{uuidlib.uuid4()}", direction="inbound", status="answered",
                           started_at=hace, recording_path=f"{ruta_fs}/conservada.wav", summary="Reclamo", conservar=True)
        beta = CallLog(tenant_id=mundo.beta.id, uuid=f"j4-{uuidlib.uuid4()}", direction="inbound", status="answered",
                       started_at=hace, summary="Beta guarda un año")
        msj = MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", ruta="/r/x.wav", duracion=3, transcripcion="Llámame",
                           created_at=hace)
        s.add_all([vieja, guardada, beta, msj])
        await s.commit()
    try:
        async with async_session() as s:
            aviso = retencion.proximas(mundo.alfa.id, 90, await retencion.rutas_conservadas(s))
        assert aviso["archivos"] == 1  # solo la nueva; ni el saludo ni la conservada
        await MaintenanceWorker()._limpiar_grabaciones(90, 100.0, {mundo.alfa.id: 90})
        assert not (carpeta / "vieja.wav").exists()
        assert (carpeta / "conservada.wav").exists() and (carpeta / "nueva.wav").exists() and saludo.exists()

        async with async_session() as s:
            await retencion.purgar_transcripciones(s, {mundo.alfa.id: 90, mundo.beta.id: 365})
            v, g, b, m = (await s.get(CallLog, vieja.id), await s.get(CallLog, guardada.id),
                          await s.get(CallLog, beta.id), await s.get(MensajeBuzon, msj.id))
            assert v.summary is None and v.transcripcion is None
            assert g.summary == "Reclamo" and b.summary == "Beta guarda un año" and m.transcripcion is None
    finally:
        async with async_session() as s:
            await s.execute(delete(CallLog).where(CallLog.id.in_([vieja.id, guardada.id, beta.id])))
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id == msj.id))
            await s.commit()


async def test_conservar_solo_quien_ve_todas(cliente, mundo):
    async with async_session() as s:
        c = CallLog(tenant_id=mundo.alfa.id, uuid=f"j4-{uuidlib.uuid4()}", direction="inbound", status="answered",
                    caller_number="3001112222", callee_number="1000", started_at=datetime.utcnow())
        s.add(c)
        await s.commit()
    try:
        asesor = mundo.alfa.cabeceras(permissions.ASESOR)
        assert (await cliente.put(f"/api/calls/{c.id}/conservar", headers=asesor, json={"conservar": True})).status_code == 403
        sup = mundo.alfa.cabeceras(permissions.SUPERVISOR)
        r = await cliente.put(f"/api/calls/{c.id}/conservar", headers=sup, json={"conservar": True})
        assert r.status_code == 200 and r.json()["conservar"] is True
        # Otra empresa no la encuentra.
        otra = await cliente.put(f"/api/calls/{c.id}/conservar", headers=mundo.beta.cabeceras(permissions.SUPERVISOR),
                                 json={"conservar": False})
        assert otra.status_code == 404
        aviso = (await cliente.get("/api/system/retencion", headers=mundo.alfa.cabeceras(permissions.ADMIN))).json()
        assert aviso["conservadas"] >= 1 and aviso["aviso_dias"] == 7
    finally:
        async with async_session() as s:
            await s.execute(delete(CallLog).where(CallLog.id == c.id))
            await s.commit()


# --- J5: preguntas sin guía ----------------------------------------------------------------

from app.models import PreguntaSinGuia  # noqa: E402
from app.services import preguntas_sin_guia  # noqa: E402


def test_solo_las_de_como_hacer_y_sin_datos():
    assert preguntas_sin_guia.es_como("¿Cómo exporto los contactos a Excel?")
    assert preguntas_sin_guia.es_como("donde cambio el logo de la empresa")
    assert not preguntas_sin_guia.es_como("hola")
    assert not preguntas_sin_guia.es_como("¿Cuántas llamadas hubo hoy?")
    assert preguntas_sin_guia.clave("¿Cómo   EXPORTO los contactos?") == preguntas_sin_guia.clave("como exporto los contactos")
    limpio = preguntas_sin_guia.limpiar("como llamo al 3001234567 o escribo a ana@correo.com")
    assert "3001234567" not in limpio and "ana@correo.com" not in limpio


async def test_se_agrupan_y_las_ve_la_plataforma(cliente, mundo):
    async with async_session() as s:
        await s.execute(delete(PreguntaSinGuia))
        await s.commit()
    asesor = mundo.alfa.cabeceras(permissions.ASESOR)
    try:
        for texto in ("¿Cómo exporto los contactos?", "como exporto los contactos", "hola, ¿qué tal?"):
            r = await cliente.post("/api/assistant/sin-guia", headers=asesor, json={"pregunta": texto})
            assert r.status_code == 204
        await cliente.post("/api/assistant/sin-guia", headers=asesor, json={"pregunta": "¿Dónde cambio el logo?", "origen": "app"})
        assert (await cliente.get("/api/plataforma/preguntas-sin-guia", headers=mundo.alfa.cabeceras(permissions.ADMIN))).status_code == 403
        plataforma = mundo.cabeceras_plataforma()
        lista = (await cliente.get("/api/plataforma/preguntas-sin-guia", headers=plataforma)).json()
        assert [(p["veces"], p["origen"]) for p in lista] == [(2, "panel"), (1, "app")]
        assert (await cliente.delete(f"/api/plataforma/preguntas-sin-guia/{lista[0]['id']}", headers=plataforma)).status_code == 204
        assert len((await cliente.get("/api/plataforma/preguntas-sin-guia", headers=plataforma)).json()) == 1
    finally:
        async with async_session() as s:
            await s.execute(delete(PreguntaSinGuia))
            await s.commit()
