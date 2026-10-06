"""Fase E de la auditoría: IVR con horario y más destinos, y calidad de
llamadas (criterios, evaluación manual y con IA, promedios)."""

import json
import uuid as uuidlib
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core import permissions
from app.core.database import async_session
from app.models import CallLog, CriterioCalidad, EvaluacionLlamada
from app.services import flow_engine, llm, webcall

# --- IVR --------------------------------------------------------------------------------------


def _bot(nodos, conexiones):
    return SimpleNamespace(id=7, name="recepcion", flow_json=json.dumps({"nodes": nodos, "edges": conexiones}))


def _generar(bot):
    seccion = ET.Element("section")
    ctx = ET.SubElement(seccion, "context", attrib={"name": "ctx_alfa"})
    assert flow_engine.build_voicebot_flow_routes(seccion, ctx, bot, "alfa.test", 1)
    return seccion


def _entrada(seccion) -> list[str]:
    ext = seccion.find(".//extension[@name='bot_7_recepcion']")
    return [f"{a.get('application')} {a.get('data')}" for a in ext.iter("action")]


NODOS = [
    {"id": "h", "type": "horario", "data": {"start": True, "horario": '{"mon": ["08:00", "18:00"]}'}},
    {"id": "menu", "type": "menu", "data": {"tts_text": "Hola"}},
    {"id": "buzon", "type": "transfer", "data": {"destino_tipo": "buzon", "extension": "101"}},
    {"id": "ventas", "type": "transfer", "data": {"destino_tipo": "grupo", "extension": "8000"}},
    {"id": "afuera", "type": "transfer", "data": {"destino_tipo": "numero", "extension": "3001234567"}},
    {"id": "malo", "type": "transfer", "data": {"destino_tipo": "grupo", "extension": "8000@otra.test"}},
    {"id": "persona", "type": "transfer", "data": {"extension": "102"}},
]
CONEXIONES = [
    {"source": "h", "target": "menu", "sourceHandle": "abierto"},
    {"source": "h", "target": "buzon", "sourceHandle": "cerrado"},
    {"source": "menu", "target": "ventas", "sourceHandle": "1"},
    {"source": "menu", "target": "afuera", "sourceHandle": "2"},
    {"source": "menu", "target": "malo", "sourceHandle": "3"},
    {"source": "menu", "target": "persona", "sourceHandle": "4"},
]


def test_ivr_horario_abierto_va_al_menu(monkeypatch):
    monkeypatch.setattr(webcall, "is_open", lambda h, ahora=None: True)
    seccion = _generar(_bot(NODOS, CONEXIONES))
    assert "transfer go XML bot_7_nmenu" in _entrada(seccion)
    ruta = seccion.find(".//context[@name='bot_7_nmenu_route']")
    acciones = {
        e.get("name"): [f"{a.get('application')} {a.get('data')}" for a in e.iter("action")]
        for e in ruta.findall("extension")
    }
    assert acciones["opcion_1"] == ["transfer 8000 XML ctx_alfa"]
    assert acciones["opcion_2"] == ["transfer 3001234567 XML ctx_alfa"]
    # Un destino que no es un número no entra al dialplan: se cuelga.
    assert acciones["opcion_3"] == ["hangup NORMAL_CLEARING"]
    assert "bridge user/102@alfa.test" in acciones["opcion_4"]


def test_ivr_horario_cerrado_va_al_buzon(monkeypatch):
    monkeypatch.setattr(webcall, "is_open", lambda h, ahora=None: False)
    seccion = _generar(_bot(NODOS, CONEXIONES))
    entrada = _entrada(seccion)
    assert "transfer *99101 XML ctx_alfa" in entrada and not any("bot_7_nmenu" in a for a in entrada)


def test_ivr_horario_sin_salida_o_en_ciclo_cuelga(monkeypatch):
    monkeypatch.setattr(webcall, "is_open", lambda h, ahora=None: True)
    nodos = [{"id": "a", "type": "horario", "data": {"start": True}}, {"id": "b", "type": "horario", "data": {}}]
    ciclo = [{"source": "a", "target": "b", "sourceHandle": "abierto"}, {"source": "b", "target": "a", "sourceHandle": "abierto"}]
    assert _entrada(_generar(_bot(nodos, ciclo)))[-1] == "hangup NORMAL_CLEARING"
    assert _entrada(_generar(_bot(nodos[:1], [])))[-1] == "hangup NORMAL_CLEARING"


# --- Calidad --------------------------------------------------------------------------------------


@pytest.fixture
async def llamada_grabada(mundo):
    async with async_session() as s:
        c = CallLog(
            tenant_id=mundo.alfa.id, uuid=f"qa-{uuidlib.uuid4()}", direction="inbound", status="answered",
            caller_number="3005550000", callee_number="1000", billsec=95, started_at=datetime.utcnow(),
            recording_path="/var/lib/freeswitch/recordings/qa.wav", cola_agente="1000",
            transcripcion=[{"rol": "Hablante 1", "texto": "Buenos días, habla Ana de Alfa."},
                           {"rol": "Hablante 2", "texto": "Quiero saber mi saldo."}],
        )
        s.add(c)
        await s.commit()
    yield c.id
    async with async_session() as s:
        await s.execute(delete(EvaluacionLlamada).where(EvaluacionLlamada.call_id == c.id))
        await s.execute(delete(CallLog).where(CallLog.id == c.id))
        await s.commit()


async def test_criterios_de_ejemplo_y_edicion(cliente, mundo):
    cab = mundo.alfa.cabeceras(permissions.SUPERVISOR)
    lista = (await cliente.get("/api/calidad/criterios", headers=cab)).json()
    assert len(lista) >= 5 and lista[0]["nombre"] == "Saludó y se presentó"
    nuevos = [{**lista[0], "peso": 2}, {"nombre": "Ofreció otro producto", "peso": 1}]
    r = await cliente.put("/api/calidad/criterios", headers=cab, json=nuevos)
    activos = [c for c in r.json() if c["activo"]]
    assert [(c["nombre"], c["peso"]) for c in activos] == [("Saludó y se presentó", 2), ("Ofreció otro producto", 1)]
    # Los quitados quedan inactivos (las evaluaciones viejas los nombran).
    assert len(r.json()) == len(lista) + 1
    # Cada empresa tiene los suyos.
    beta = (await cliente.get("/api/calidad/criterios", headers=mundo.beta.cabeceras(permissions.SUPERVISOR))).json()
    assert "Ofreció otro producto" not in {c["nombre"] for c in beta}
    # Vuelve a los de ejemplo para no afectar otras pruebas.
    async with async_session() as s:
        await s.execute(delete(CriterioCalidad).where(CriterioCalidad.tenant_id == mundo.alfa.id))
        await s.commit()


async def test_evaluar_una_llamada_y_ver_resultados(cliente, mundo, llamada_grabada):
    cab = mundo.alfa.cabeceras(permissions.SUPERVISOR)
    criterios = [c for c in (await cliente.get("/api/calidad/criterios", headers=cab)).json() if c["activo"]]
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    pendientes = (await cliente.get(f"/api/calidad/llamadas?desde={ayer}&hasta={hoy}&sin_evaluar=true", headers=cab)).json()
    assert llamada_grabada in {f["id"] for f in pendientes}

    # Hay que calificar todos los criterios, de 0 a 2.
    incompleta = {str(criterios[0]["id"]): 2}
    r = await cliente.post(f"/api/calidad/llamadas/{llamada_grabada}/evaluaciones", headers=cab, json={"puntajes": incompleta})
    assert r.status_code == 422
    fuera = {str(c["id"]): 3 for c in criterios}
    assert (await cliente.post(f"/api/calidad/llamadas/{llamada_grabada}/evaluaciones", headers=cab, json={"puntajes": fuera})).status_code == 422

    puntajes = {str(c["id"]): 2 for c in criterios}
    puntajes[str(criterios[0]["id"])] = 0
    r = await cliente.post(f"/api/calidad/llamadas/{llamada_grabada}/evaluaciones", headers=cab,
                           json={"puntajes": puntajes, "comentario": "Faltó saludar."})
    assert r.status_code == 201, r.text
    ev = r.json()
    esperado = round(100 * (2 * (len(criterios) - 1)) / (2 * len(criterios)), 1)
    assert ev["total_pct"] == esperado
    # Quien atendió sale de la extensión del grupo (1000 = el asesor de alfa).
    assert ev["agente_id"] == mundo.alfa.usuarios[permissions.ASESOR]

    ya = (await cliente.get(f"/api/calidad/llamadas?desde={ayer}&hasta={hoy}&sin_evaluar=true", headers=cab)).json()
    assert llamada_grabada not in {f["id"] for f in ya}
    resumen = (await cliente.get(f"/api/calidad/resumen?desde={ayer}&hasta={hoy}", headers=cab)).json()
    fila = next(f for f in resumen["filas"] if f["agente_id"] == mundo.alfa.usuarios[permissions.ASESOR])
    assert fila["evaluaciones"] >= 1 and fila["por_criterio"][str(criterios[0]["id"])] == 0.0

    # El asesor ve su retroalimentación, pero no evalúa ni ve las de todos.
    asesor = mundo.alfa.cabeceras(permissions.ASESOR)
    mias = (await cliente.get("/api/calidad/mias", headers=asesor)).json()
    assert any(e["comentario"] == "Faltó saludar." for e in mias["evaluaciones"])
    assert (await cliente.get(f"/api/calidad/llamadas?desde={ayer}&hasta={hoy}", headers=asesor)).status_code == 403
    # Otra empresa no alcanza la llamada.
    otra = mundo.beta.cabeceras(permissions.SUPERVISOR)
    assert (await cliente.get(f"/api/calidad/llamadas/{llamada_grabada}", headers=otra)).status_code == 404
    assert (await cliente.post(f"/api/calidad/llamadas/{llamada_grabada}/evaluaciones", headers=otra,
                               json={"puntajes": puntajes})).status_code in (404, 422)


async def test_la_ia_sugiere_la_evaluacion(cliente, mundo, llamada_grabada, monkeypatch):
    cab = mundo.alfa.cabeceras(permissions.SUPERVISOR)
    criterios = [c for c in (await cliente.get("/api/calidad/criterios", headers=cab)).json() if c["activo"]]
    async with async_session() as s:
        from app.services.ajustes import ajustes_de
        from app.core.database import fijar_tenant

        fijar_tenant(s, mundo.alfa.id)
        a = await ajustes_de(s, mundo.alfa.id)
        a.ai_llm_api_key = "clave-de-prueba-llm"
        await s.commit()
    enviados = []

    async def chat(base, modelo, clave, mensajes, **kw):
        enviados.append(mensajes)
        notas = {str(c["id"]): (2 if i else 1) for i, c in enumerate(criterios)}
        return {"content": "```json\n" + json.dumps({"puntajes": notas, "comentario": "Saludó, pero no confirmó."}) + "\n```"}, {}

    monkeypatch.setattr(llm, "chat", chat)
    r = await cliente.post(f"/api/calidad/llamadas/{llamada_grabada}/sugerencia", headers=cab)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["puntajes"][str(criterios[0]["id"])] == 1 and s["comentario"] == "Saludó, pero no confirmó."
    # Usó la transcripción guardada (no volvió a transcribir) y los criterios.
    assert "Quiero saber mi saldo" in enviados[0][1]["content"] and criterios[0]["nombre"] in enviados[0][1]["content"]
    # Nada se guardó todavía.
    async with async_session() as s2:
        assert not (await s2.execute(select(EvaluacionLlamada).where(EvaluacionLlamada.call_id == llamada_grabada))).first()
