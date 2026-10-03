"""Fase 6: reportes. Las cifras tienen que cuadrar con la bitácora.

Se siembra una jornada conocida (tramos de agente, CDRs, métricas del
predictivo) en un día fijo y se compara cada cifra con lo esperado a mano.
El día es local (Bogotá, UTC-5): el 15/09/2026 va de 05:00 UTC a 05:00 UTC
del día siguiente.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import permissions
from app.core.database import async_session, sesion_de_empresa
from app.core.security import crear_token
from app.models import CallLog, Campaign, CodigoPausa, Disposicion, EstadoAgente, MetricaCampana, SesionAgente, SystemSettings
from app.services import agentes, reportes

from .test_agentes import papa  # noqa: F401  (fixture)

DIA = date(2026, 9, 15)


def utc(h, m=0, dia=DIA):
    """Hora LOCAL del día → UTC naive (Bogotá es UTC-5, sin horario de verano)."""
    return datetime(dia.year, dia.month, dia.day, h, m) + timedelta(hours=5)


@pytest.fixture
async def jornada(papa):  # noqa: F811
    t, a0, a1 = papa["tenant"], papa["agentes"][0], papa["agentes"][1]
    camp = papa["camp"]["progresivo"]
    async with sesion_de_empresa(t) as s:
        await agentes.asegurar_catalogos(s, t)
        await s.flush()
        brk = (await s.execute(select(CodigoPausa).where(CodigoPausa.codigo == "BREAK"))).scalar_one()
        disp = {d.codigo: d for d in (await s.execute(select(Disposicion))).scalars()}
        ses = SesionAgente(tenant_id=t, user_id=a0, campanas=[camp], inicio=utc(8), fin=utc(12))
        # Empezó a las 23:00 del día anterior: del 15 cuenta solo 00:00-01:00.
        noche = SesionAgente(tenant_id=t, user_id=a1, campanas=[camp], inicio=utc(23, 0, DIA - timedelta(days=1)), fin=utc(1))
        s.add_all([ses, noche])
        await s.flush()
        tramos = [
            ("PAUSA", utc(8), utc(8, 20), brk.id, None),
            ("LISTO", utc(8, 20), utc(8, 30), None, None),
            ("TIMBRANDO", utc(8, 30), utc(8, 31), None, "u1"),
            ("EN_LLAMADA", utc(8, 31), utc(8, 41), None, "u1"),
            ("DISPO", utc(8, 41), utc(8, 43), None, "u1"),
            ("LISTO", utc(8, 43), utc(11), None, None),
            ("PAUSA", utc(11), utc(11, 10), brk.id, None),
            ("LISTO", utc(11, 10), utc(12), None, None),
        ]
        for estado, ini, fin, pausa, uuid in tramos:
            s.add(EstadoAgente(tenant_id=t, user_id=a0, sesion_id=ses.id, estado=estado, codigo_pausa_id=pausa,
                               campaign_id=camp if uuid else None, call_uuid=uuid, inicio=ini, fin=fin))
        s.add(EstadoAgente(tenant_id=t, user_id=a1, sesion_id=noche.id, estado="LISTO", inicio=noche.inicio, fin=noche.fin))

        def cdr(uuid, estado, hora, **kw):
            return CallLog(tenant_id=t, campaign_id=camp, uuid=f"{uuid}-{t}", direction="outbound", status=estado,
                           callee_number=kw.pop("tel", "3001112233"), started_at=hora, **kw)

        s.add_all([
            cdr("c1", "answered", utc(8, 30), billsec=300, ring_ms=8000, agente_id=a0, disposicion_id=disp["VENTA"].id),
            cdr("c2", "answered", utc(9), billsec=3, ring_ms=4000, abandonada=True),
            cdr("c3", "busy", utc(9, 5)),
            cdr("c4", "no_answer", utc(9, 10)),
            cdr("c5", "answered", utc(10), billsec=100, agente_id=a0, disposicion_id=disp["NO_INTERESADO"].id),
            # Del día anterior: fuera del rango.
            cdr("c6", "answered", utc(20, 0, DIA - timedelta(days=1)), billsec=50),
        ])
        s.add(MetricaCampana(tenant_id=t, campaign_id=camp, fecha=DIA, intentos=400, contestadas=100, asignadas=95, abandonadas=5))
        await s.commit()
    return {"camp": camp, "a0": a0, "a1": a1}


async def _r(papa, tipo, **f):  # noqa: F811
    async with sesion_de_empresa(papa["tenant"]) as s:
        return await reportes.generar(s, tipo, reportes.rango_utc(DIA, DIA), **f)


async def test_agentes_cuadra_con_la_bitacora(papa, jornada):  # noqa: F811
    datos = await _r(papa, "agentes")
    por = {f["user_id"]: f for f in datos["filas"]}
    a = por[jornada["a0"]]
    assert a["login_s"] == 4 * 3600
    # Los tramos cubren la sesión sin huecos: la suma de estados es el tiempo conectado.
    assert sum(a[f"{e.lower()}_s"] for e in reportes.ESTADOS) == a["login_s"]
    assert (a["pausa_s"], a["listo_s"], a["timbrando_s"], a["en_llamada_s"], a["dispo_s"]) == (1800, 600 + 8220 + 3000, 60, 600, 120)
    assert a["pausas"] == [{"codigo_pausa_id": a["pausas"][0]["codigo_pausa_id"], "nombre": "Descanso", "veces": 2, "total_s": 1800, "promedio_s": 900.0}]
    assert a["llamadas"] == 1 and a["aht_s"] == 720.0
    assert a["ocupacion_pct"] == round(100 * 720 / (14400 - 1800), 1)
    assert a["utilizacion_pct"] == 5.0
    # La sesión que cruzó la medianoche cuenta solo su parte del día.
    assert por[jornada["a1"]]["login_s"] == 3600
    assert datos["total"]["login_s"] == 4 * 3600 + 3600


async def test_campanas(papa, jornada):  # noqa: F811
    f = (await _r(papa, "campanas"))["filas"]
    assert len(f) == 1
    c = f[0]
    assert (c["intentos"], c["contestadas"], c["abandonadas"], c["ocupado"], c["no_contesta"], c["fallidas"]) == (5, 3, 1, 1, 1, 0)
    assert c["contacto_pct"] == 60.0 and c["abandono_pct"] == 33.3
    assert c["ring_promedio_s"] == 6.0
    assert c["aht_s"] == round((300 + 3 + 100) / 2, 1)  # sin la abandonada
    assert (c["contactos"], c["ventas"], c["conversion_pct"]) == (2, 1, 50.0)


async def test_disposiciones_por_agente_y_callbacks(papa, jornada):  # noqa: F811
    d = await _r(papa, "disposiciones", agrupar="agente")
    assert d["total"] == 2
    assert {(x["grupo"], x["codigo"], x["cantidad"], x["pct"]) for x in d["filas"]} == {
        ("Agente 0", "VENTA", 1, 50.0), ("Agente 0", "NO_INTERESADO", 1, 50.0)}
    assert d["callbacks"]["total"] == 0


async def test_cumplimiento(papa, jornada):  # noqa: F811
    t, camp = papa["tenant"], jornada["camp"]
    async with async_session() as s:
        await s.execute(update(Campaign).where(Campaign.id == camp).values(ai_intent="cobranza"))
        await s.execute(update(SystemSettings).where(SystemSettings.tenant_id == t).values(campaign_hours_weekdays="08:00-19:00"))
        s.add_all([
            # A las 6:00 locales: fuera de horario.
            CallLog(tenant_id=t, campaign_id=camp, uuid=f"madrugada-{t}", direction="outbound", status="no_answer",
                    callee_number="3009998877", started_at=utc(6)),
            # Segunda contestada al mismo número la misma semana (otro formato del número).
            CallLog(tenant_id=t, campaign_id=camp, uuid=f"otra-{t}", direction="outbound", status="answered",
                    callee_number="+57 300 111 2233", started_at=utc(15), billsec=40),
        ])
        await s.commit()
    c = await _r(papa, "cumplimiento")
    assert c["abandono"] == [{"fecha": "2026-09-15", "campaign_id": camp, "campana": c["abandono"][0]["campana"], "contestadas": 100,
                              "abandonadas": 5, "abandono_pct": 5.0, "objetivo_pct": 3.0, "cumple": False}]
    assert c["abandono_incumplido"] == 1
    assert c["fuera_de_horario_total"] == 1 and c["fuera_de_horario"][0]["telefono"] == "3009998877"
    excesos = c["contactos_semana"]
    assert len(excesos) == 1 and excesos[0]["contestadas"] == 4 and excesos[0]["semana"] == "2026-S38"
    # Con un tope más alto, no hay exceso.
    assert (await _r(papa, "cumplimiento", max_contactos_semana=5))["contactos_semana_total"] == 0


async def test_api_csv_y_permisos(cliente, papa, jornada):  # noqa: F811
    cab = {"Authorization": f"Bearer {crear_token(papa['agentes'][0], permissions.ASESOR, papa['tenant'])[0]}"}
    url = f"/api/reportes/campanas?desde={DIA}&hasta={DIA}"
    assert (await cliente.get(url, headers=cab)).status_code == 403
    from .test_supervision import _cab, _usuario

    coord = await _usuario(papa, permissions.COORDINADOR)
    cab = _cab(papa, coord, permissions.COORDINADOR)
    r = await cliente.get(url, headers=cab)
    assert r.status_code == 200 and r.json()["filas"][0]["intentos"] == 5
    r = await cliente.get(url + "&formato=csv", headers=cab)
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    lineas = r.text.lstrip("\ufeff").splitlines()
    assert lineas[0].startswith("Campaña;Método;Intentos") and ";5;3;1;" in lineas[1]
    r = await cliente.get(f"/api/reportes/cumplimiento?desde={DIA}&hasta={DIA}&formato=csv&seccion=contactos_semana", headers=cab)
    assert r.status_code == 200
    # Rango inválido.
    assert (await cliente.get(f"/api/reportes/agentes?desde={DIA}&hasta={DIA - timedelta(days=1)}", headers=cab)).status_code == 400
    assert (await cliente.get(f"/api/reportes/agentes?desde=2020-01-01&hasta={DIA}", headers=cab)).status_code == 400


async def test_otra_empresa_no_aparece(cliente, mundo):
    r = await cliente.get("/api/reportes/campanas?desde=2000-01-01&hasta=2000-12-31", headers=mundo.alfa.cabeceras())
    assert r.status_code == 200
    hoy = date.today()
    r = await cliente.get(f"/api/reportes/campanas?desde={hoy - timedelta(days=300)}&hasta={hoy + timedelta(days=30)}", headers=mundo.alfa.cabeceras())
    assert r.status_code == 200 and mundo.beta.marca not in r.text and mundo.beta.telefono not in r.text


def test_csv_neutraliza_formulas():
    texto = reportes.a_csv([{"a": "=HYPERLINK(\"x\")", "b": "+573001112233", "c": -3.5, "d": True}],
                           [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])
    import csv

    fila = list(csv.reader(texto.lstrip("\ufeff").splitlines(), delimiter=";"))[1]
    assert fila == ["'=HYPERLINK(\"x\")", "+573001112233", "-3,5", "sí"]
