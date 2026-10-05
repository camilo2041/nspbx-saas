"""Fase 4 del contact center: proporcional y predictivo.

- Las cuentas (binomial, tasa de contacto, prudencia) y su piso: el
  progresivo.
- El simulador, en varios escenarios: abandono bajo el objetivo y más
  ocupación que el progresivo donde el predictivo tiene sentido.
- El motor con FreeSWITCH simulado: lanza, asigna al agente que más espera,
  abandona con mensaje si no hay agente y recicla el lead con prioridad.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.database import async_session, sesion_de_empresa
from app.models import CallLog, Campaign, CampaignNumber, MetricaCampana
from app.services import agentes, predictivo
from app.services.simulador_predictivo import Parametros, simular

from .conftest import FS_SECRET
from .test_agentes import FS, _accion, _entrar, _evento, _vivo, papa  # noqa: F401  (fixtures)


@pytest.fixture
def fs(monkeypatch):
    return FS(monkeypatch)


# --- Las cuentas -------------------------------------------------------------------------


def test_nunca_menos_que_el_progresivo_ni_mas_que_el_tope():
    for libres in (1, 3, 10):
        for p in (0.05, 0.2, 0.4):
            n = predictivo.llamadas_en_curso(libres, p, 3.0, nivel_max=3.0)
            assert libres <= n <= libres * 3
    assert predictivo.llamadas_en_curso(0, 0.2, 3.0, 3.0) == 0


def test_mas_llamadas_con_menos_contacto_y_mas_agentes():
    assert predictivo.llamadas_en_curso(10, 0.1, 3.0, 8.0) > predictivo.llamadas_en_curso(10, 0.3, 3.0, 8.0)
    # Con más agentes el exceso se reparte: más llamadas por agente.
    por_agente = [predictivo.llamadas_en_curso(a, 0.2, 3.0, 8.0) / a for a in (2, 10, 30)]
    assert por_agente == sorted(por_agente)


def test_con_contacto_alto_no_se_sobremarca():
    assert predictivo.llamadas_en_curso(10, 0.6, 3.0, 8.0) == 10


def test_la_tasa_de_contacto_arranca_prudente():
    assert predictivo.tasa_contacto(0, 0) == pytest.approx(0.9)
    assert predictivo.tasa_contacto(30, 100) == pytest.approx((30 + 18) / 120)
    assert predictivo.tasa_contacto(300, 1000) == pytest.approx(0.3, abs=0.02)


def test_la_prudencia_sube_con_abandono_y_baja_despacio():
    assert predictivo.ajustar_factor(1.5, None, 4.0, 3.0, 20.0) == pytest.approx(1.875)
    assert predictivo.ajustar_factor(1.5, 3.5, 0.5, 3.0, 20.0) == pytest.approx(1.875)  # el día manda
    assert predictivo.ajustar_factor(1.5, None, 0.5, 3.0, 20.0) == pytest.approx(1.425)
    assert predictivo.ajustar_factor(1.5, None, 2.0, 3.0, 20.0) == 1.5  # cerca del objetivo: quieto
    assert predictivo.ajustar_factor(1.5, None, 0.5, 3.0, 2.0) == 1.5  # agentes sin esperar: quieto
    assert predictivo.ajustar_factor(1.0, None, 0.0, 3.0, 99.0) == predictivo.FACTOR_MIN


def test_el_proporcional_en_nivel_uno_es_el_progresivo():
    assert predictivo.a_lanzar(5, 3, 2, 1, 1.0) == 5 - 2 - 1
    assert predictivo.a_lanzar(5, 0, 0, 0, 2.0) == 10


# --- Simulador -----------------------------------------------------------------------------


@pytest.mark.parametrize("contacto,agentes", [(0.15, 10), (0.15, 30), (0.3, 10), (0.3, 30), (0.5, 10), (0.8, 30)])
def test_simulador_abandono_bajo_el_objetivo(contacto, agentes):
    p = Parametros(contacto=contacto, agentes=agentes, nivel_max=8.0, duracion_s=2 * 3600)
    r = simular(p, "predictivo")
    assert r.contestadas > 100
    assert r.abandono_pct <= p.objetivo_pct


def test_simulador_el_predictivo_rinde_mas_que_el_progresivo():
    p = Parametros(contacto=0.15, agentes=30, nivel_max=8.0, duracion_s=2 * 3600)
    progresivo, pred = simular(p, "progresivo"), simular(p, "predictivo")
    assert pred.ocupacion(p) > progresivo.ocupacion(p) + 0.10
    assert pred.conversaciones > progresivo.conversaciones


# --- El motor --------------------------------------------------------------------------------


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
async def campana(papa):  # noqa: F811
    """La campaña "progresivo" de la fixture convertida en predictiva y en curso."""
    cid = papa["camp"]["progresivo"]
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == cid).values(
            metodo="predictivo", status="running", max_concurrency=20, temporizador_abandono=2,
            audio_abandono="/usr/share/freeswitch/sounds/bots/abandono_c1.mp3",
        ))
        s.add_all([CampaignNumber(tenant_id=papa["tenant"], campaign_id=cid, phone=f"30088800{i:02d}") for i in range(20)])
        await s.commit()
    yield cid
    # Que el motor de otras pruebas no la siga marcando.
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == cid).values(status="paused"))
        await s.commit()


async def _proporcional(campana, nivel=2.0):
    """Proporcional fijo: deja tener dos llamadas con un solo agente."""
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == campana).values(metodo="proporcional", nivel_marcacion=nivel))
        await s.commit()


async def _lanzar(motor, papa, campana):  # noqa: F811
    """Una vuelta del motor solo para esta campaña (el ciclo recorre todas)."""
    await motor.atender_esperas()
    async with sesion_de_empresa(papa["tenant"]) as s:
        n = await motor._campana(s, campana)
        await s.commit()
    return n


def _originados(fs, campana):
    return [c for c in fs.bgapi if "&park()" in c and f"nspbx_campaign_id={campana}," in c]


async def _motor(papa, fs, campana, *agentes_listos):  # noqa: F811
    for i in agentes_listos:
        await _entrar(papa, fs, i, [campana])
        await _accion(papa, i, agentes.listo)
    reloj = Reloj()
    return predictivo.Motor(reloj=reloj), reloj


def _ev(papa, campana, nombre, uuid, **extra):
    ev = {"Event-Name": nombre, "Unique-ID": uuid, "variable_nspbx_tenant_id": str(papa["tenant"]),
          "variable_nspbx_pred": "1", "variable_nspbx_campaign_id": str(campana)}
    ev.update(extra)
    return ev


async def test_lanza_sin_agente_y_asigna_al_que_mas_espera(papa, fs, campana):  # noqa: F811
    motor, reloj = await _motor(papa, fs, campana, 0, 1)
    lanzadas = await _lanzar(motor, papa, campana)
    assert lanzadas >= 2  # al menos una por agente listo
    originados = _originados(fs, campana)
    assert len(originados) == lanzadas and all("nspbx_pred=1" in c for c in originados)
    assert all("nspbx_agente_id" not in c for c in originados)
    # Vuelve a pasar: no lanza de más mientras las otras timbran.
    assert await _lanzar(motor, papa, campana) == 0

    uuid = fs.uuid(originados[0])
    await motor.recibir(_ev(papa, campana, "CHANNEL_ANSWER", uuid))
    agente0 = papa["agentes"][0]  # entró y quedó listo primero: el que más espera
    assert f"uuid_setvar {uuid} nspbx_agente_id {agente0}" in fs.api
    assert any(c.startswith(f"uuid_transfer {uuid} conference:agente_{papa['tenant']}_{agente0}@nspbx_agente") for c in fs.api)
    vivo = await _vivo(papa, 0)
    assert vivo.estado == agentes.EN_LLAMADA and vivo.call_uuid == uuid and vivo.contestada_at
    assert motor.llamadas[uuid].estado == "asignada"

    # Al colgar, el motor de agentes lo pasa a disposición (FreeSWITCH manda
    # el agente en el canal porque se le fijó con uuid_setvar).
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", uuid, agente=agente0)
    await motor.recibir(_ev(papa, campana, "CHANNEL_HANGUP_COMPLETE", uuid, **{"variable_nspbx_agente_id": str(agente0)}))
    assert (await _vivo(papa, 0)).estado == agentes.DISPO
    assert uuid not in motor.llamadas
    async with sesion_de_empresa(papa["tenant"]) as s:
        m = (await s.execute(select(MetricaCampana).where(MetricaCampana.campaign_id == campana))).scalar_one()
    assert (m.intentos, m.contestadas, m.asignadas, m.abandonadas) == (lanzadas, 1, 1, 0)


async def test_sin_agente_a_tiempo_es_abandono_con_mensaje(papa, fs, campana):  # noqa: F811
    await _proporcional(campana)
    motor, reloj = await _motor(papa, fs, campana, 0)
    assert await _lanzar(motor, papa, campana) == 2
    uno, dos = [fs.uuid(c) for c in _originados(fs, campana)]
    await motor.recibir(_ev(papa, campana, "CHANNEL_ANSWER", uno))  # se lo lleva el único agente
    await motor.recibir(_ev(papa, campana, "CHANNEL_ANSWER", dos))  # no queda nadie
    assert motor.llamadas[dos].estado == "espera"
    reloj.t += 1
    await motor.atender_esperas()
    assert motor.llamadas[dos].estado == "espera"  # todavía dentro del temporizador
    reloj.t += 1.5
    await motor.atender_esperas()
    assert dos not in motor.llamadas
    assert f"uuid_setvar {dos} nspbx_abandonada true" in fs.api
    assert f"uuid_transfer {dos} playback:/usr/share/freeswitch/sounds/bots/abandono_c1.mp3,hangup inline" in fs.api
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = (await s.execute(select(CampaignNumber).where(CampaignNumber.last_error.like("Abandonada%")))).scalar_one()
        m = (await s.execute(select(MetricaCampana).where(MetricaCampana.campaign_id == campana))).scalar_one()
        stats = await predictivo.metricas_de_hoy(s, campana)
    assert lead.status == "pending" and lead.prioridad == predictivo.PRIORIDAD_ABANDONO
    assert lead.proximo_intento_at > datetime.utcnow() + timedelta(minutes=9)
    assert (m.contestadas, m.asignadas, m.abandonadas) == (2, 1, 1) and stats["abandono_pct"] == 50.0


async def test_un_agente_que_se_libera_a_tiempo_lo_recibe(papa, fs, campana):  # noqa: F811
    await _proporcional(campana)
    motor, reloj = await _motor(papa, fs, campana, 0)
    assert await _lanzar(motor, papa, campana) == 2
    uno, dos = [fs.uuid(c) for c in _originados(fs, campana)]
    await motor.recibir(_ev(papa, campana, "CHANNEL_ANSWER", uno))
    await motor.recibir(_ev(papa, campana, "CHANNEL_ANSWER", dos))
    # El agente termina y dispone dentro del temporizador.
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", uno, agente=papa["agentes"][0])
    async with sesion_de_empresa(papa["tenant"]) as s:
        from .test_agentes import _usuario

        vivo = await agentes.vivo_de(s, papa["agentes"][0])
        disp = (await s.execute(select(agentes.Disposicion.id).where(agentes.Disposicion.codigo == "VENTA"))).scalar_one()
        await agentes.disponer(s, vivo, await _usuario(s, papa["agentes"][0]), disp)
        await s.commit()
    reloj.t += 1
    await motor.atender_esperas()
    assert motor.llamadas[dos].estado == "asignada"
    assert (await _vivo(papa, 0)).call_uuid == dos


async def test_si_el_cliente_cuelga_esperando_tambien_es_abandono(papa, fs, campana):  # noqa: F811
    motor, reloj = await _motor(papa, fs, campana)  # sin agentes: el ciclo no lanza
    assert await _lanzar(motor, papa, campana) == 0
    motor.llamadas["x-1"] = predictivo.Llamada("x-1", papa["tenant"], campana, 0, "espera", reloj.t, reloj.t, reloj.t + 2)
    await motor.recibir(_ev(papa, campana, "CHANNEL_HANGUP_COMPLETE", "x-1"))
    assert "x-1" not in motor.llamadas
    assert not any("x-1" in c for c in fs.api)  # ya colgó: no hay nada que transferir
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await predictivo.metricas_de_hoy(s, campana))["abandonadas"] == 1


async def test_no_contesto_recicla_el_lead(papa, fs, campana):  # noqa: F811
    motor, reloj = await _motor(papa, fs, campana, 0)
    assert await _lanzar(motor, papa, campana) == 1
    uuid = fs.uuid(_originados(fs, campana)[0])
    lead_id = motor.llamadas[uuid].lead_id
    await motor.recibir(_ev(papa, campana, "CHANNEL_HANGUP_COMPLETE", uuid, **{"Hangup-Cause": "NO_ANSWER"}))
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, lead_id)
    assert lead.status == "pending" and lead.last_error == "NO_ANSWER"
    assert motor.ventana(campana).contacto(reloj.t) < 0.9  # la tasa ya aprende


async def test_sin_agentes_listos_no_marca_y_los_otros_motores_no_la_tocan(papa, fs, campana, monkeypatch):  # noqa: F811
    motor, _ = await _motor(papa, fs, campana)
    await _entrar(papa, fs, 0, [campana])  # en pausa
    assert await _lanzar(motor, papa, campana) == 0
    await _accion(papa, 0, agentes.listo)
    assert await agentes.motor.ciclo() == 0  # el progresivo no toma campañas predictivas


async def test_el_cdr_marca_la_abandonada(cliente, papa):  # noqa: F811
    u = "abandonada-1"
    await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
        "uuid": u, "nspbx_tenant_id": str(papa["tenant"]), "nspbx_abandonada": "true",
        "direction": "outbound", "billsec": "3", "hangup_cause": "NORMAL_CLEARING",
    }})
    async with async_session() as s:
        assert (await s.execute(select(CallLog.abandonada).where(CallLog.uuid == u))).scalar_one() is True


async def test_guardar_una_campana_predictiva_genera_el_mensaje(cliente, mundo, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tts

    dichos = []

    async def sintetizar(texto, voz):
        dichos.append(texto)
        return b"ID3-mp3"

    monkeypatch.setattr(tts, "synthesize", sintetizar)
    monkeypatch.setattr(settings, "fs_sounds_dir", str(tmp_path))
    cab = mundo.alfa.cabeceras()
    r = await cliente.post("/api/campaigns", headers=cab, json={"name": "pred-msg", "metodo": "predictivo"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["audio_abandono"] == f"/usr/share/freeswitch/sounds/bots/abandono_c{c['id']}.mp3"
    assert "Empresa alfa" in dichos[0] and (tmp_path / "bots" / f"abandono_c{c['id']}.mp3").exists()
    r = await cliente.put(f"/api/campaigns/{c['id']}", headers=cab, json={"mensaje_abandono": "Le llamaba Alfa; volvemos a llamar."})
    assert dichos[-1] == "Le llamaba Alfa; volvemos a llamar."
    stats = (await cliente.get(f"/api/campaigns/{c['id']}/stats", headers=cab)).json()
    assert stats["predictivo"]["intentos"] == 0 and stats["predictivo"]["abandono_pct"] is None
    await cliente.delete(f"/api/campaigns/{c['id']}", headers=cab)


async def test_si_no_se_puede_generar_el_mensaje_igual_se_guarda(cliente, mundo, monkeypatch):
    from app.services import tts

    async def falla(texto, voz):
        raise RuntimeError("sin red")

    monkeypatch.setattr(tts, "synthesize", falla)
    r = await cliente.post("/api/campaigns", headers=mundo.alfa.cabeceras(), json={"name": "pred-sin-red", "metodo": "proporcional"})
    assert r.status_code == 201 and r.json()["audio_abandono"] is None
    await cliente.delete(f"/api/campaigns/{r.json()['id']}", headers=mundo.alfa.cabeceras())


# --- Lo que impide marcar a toda la campaña, y el diagnóstico -------------------------------


async def test_sin_troncal_espera_sin_quemar_los_numeros(papa, fs, campana):  # noqa: F811
    """Antes cada número tomado quedaba «fallido» por falta de troncal: la
    campaña quemaba la base entera sin llamar a nadie."""
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == campana).values(trunk_id=None))
        await s.commit()
    motor, _ = await _motor(papa, fs, campana, 0, 1)
    assert await _lanzar(motor, papa, campana) == 0
    assert "troncal" in motor.motivos[campana]
    assert not _originados(fs, campana)
    async with sesion_de_empresa(papa["tenant"]) as s:
        estados = set((await s.execute(select(CampaignNumber.status).where(CampaignNumber.campaign_id == campana))).scalars())
    assert estados == {"pending"}


async def test_el_diagnostico_dice_que_falta_y_luego_que_esta_listo(papa, fs, campana):  # noqa: F811
    from app.services import diagnostico_campana

    async def revisar():
        async with sesion_de_empresa(papa["tenant"]) as s:
            return await diagnostico_campana.revisar(s, await s.get(Campaign, campana))

    d = await revisar()
    falta = {i["clave"] for i in d["items"] if not i["ok"]}
    assert not d["listo"] and "conectados" in falta and "agente" in d["resumen"]
    await _motor(papa, fs, campana, 0)  # entra y queda listo
    d = await revisar()
    assert d["listo"], d
    assert d["agentes"] == {"conectados": 1, "con_audio": 1, "listos": 1}

    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == campana).values(trunk_id=None))
        await s.commit()
    d = await revisar()
    assert not d["listo"] and "troncal" in d["resumen"]


async def test_iniciar_sin_troncal_avisa_en_vez_de_quedar_en_curso(cliente, mundo, monkeypatch):
    async def sin_audio(campana, empresa):
        return None

    monkeypatch.setattr(predictivo, "generar_audio_abandono", sin_audio)
    cab = mundo.alfa.cabeceras()
    camp = (await cliente.post("/api/campaigns", json={"name": "sin-troncal", "metodo": "predictivo"}, headers=cab)).json()
    r = await cliente.post(f"/api/campaigns/{camp['id']}/numbers", json={"numbers": [{"phone": "3001112233"}]}, headers=cab)
    assert r.status_code == 201, r.text
    r = await cliente.post(f"/api/campaigns/{camp['id']}/start", headers=cab)
    assert r.status_code == 400 and "troncal" in r.json()["detail"]
    d = (await cliente.get(f"/api/campaigns/{camp['id']}/diagnostico", headers=cab)).json()
    assert not d["listo"] and {"troncal", "iniciada", "asignados"} <= {i["clave"] for i in d["items"] if not i["ok"]}
