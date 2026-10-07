"""Fase C de la auditoría: reporte de llamadas entrantes (nivel de servicio,
abandono, espera), alertas de operación por correo y la ficha de quien llama."""

import uuid as uuidlib
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.api.calls import datos_de_cola
from app.core import permissions
from app.core.database import async_session
from app.models import CallLog, Contacto, License, NoLlamar, Nota, SecurityAlert, Trunk
from app.services import alertas, esl, reportes_programados

from .conftest import FS_SECRET
from .test_alertas import zeta  # noqa: F401 (fixture)

# --- Datos de la cola en el CDR --------------------------------------------------------


def test_datos_de_cola_del_cdr():
    base = {"cc_queue": "ventas@a.test", "cc_queue_joined_epoch": "1000", "cc_side": "member"}
    assert datos_de_cola({**base, "cc_queue_answered_epoch": "1012", "cc_agent": "101@a.test"}) == {
        "cola": "ventas", "cola_espera_s": 12, "cola_resultado": "atendida", "cola_agente": "101",
    }
    colgo = datos_de_cola({**base, "cc_queue_canceled_epoch": "1040", "cc_cancel_reason": "BREAK_OUT"})
    assert (colgo["cola_resultado"], colgo["cola_espera_s"]) == ("abandonada", 40)
    tiempo = datos_de_cola({**base, "cc_queue_canceled_epoch": "1060", "cc_cancel_reason": "TIMEOUT"})
    assert (tiempo["cola_resultado"], tiempo["cola_espera_s"]) == ("desbordada", 60)
    # La pata del agente también trae cc_queue: no se cuenta dos veces.
    assert datos_de_cola({**base, "cc_side": "agent", "cc_queue_answered_epoch": "1012"}) == {}
    assert datos_de_cola({"destination_number": "101"}) == {}


async def test_el_cdr_guarda_la_cola(cliente, mundo):
    u = f"cc-{uuidlib.uuid4()}"
    r = await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
        "uuid": u, "nspbx_tenant_id": str(mundo.alfa.id), "direction": "inbound", "billsec": "30",
        "hangup_cause": "NORMAL_CLEARING", "caller_id_number": "3005550000",
        "cc_queue": f"soporte@{mundo.alfa.dominio}", "cc_side": "member",
        "cc_queue_joined_epoch": "1700000000", "cc_queue_answered_epoch": "1700000008", "cc_agent": f"1000@{mundo.alfa.dominio}",
    }})
    assert r.status_code == 200
    async with async_session() as s:
        c = (await s.execute(select(CallLog).where(CallLog.uuid == u))).scalar_one()
    assert (c.cola, c.cola_espera_s, c.cola_resultado, c.cola_agente) == ("soporte", 8, "atendida", "1000")


# --- Reporte de entrantes -----------------------------------------------------------------


@pytest.fixture
async def llamadas_de_cola(mundo):
    """Hoy, en alfa: 10 llamadas a «ventas» y 2 a «soporte»; en beta, 3 que no
    deben aparecer en el reporte de alfa."""
    hoy = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    filas = [
        # (empresa, cola, espera, resultado, agente)
        *[(mundo.alfa.id, "ventas", 10, "atendida", "1000")] * 5,
        *[(mundo.alfa.id, "ventas", 45, "atendida", "1000")] * 2,
        (mundo.alfa.id, "ventas", 30, "abandonada", None),
        (mundo.alfa.id, "ventas", 2, "abandonada", None),  # colgó al instante
        (mundo.alfa.id, "ventas", 60, "desbordada", None),
        (mundo.alfa.id, "soporte", 5, "atendida", "1000"),
        (mundo.alfa.id, "soporte", 5, "atendida", "1000"),
        *[(mundo.beta.id, "ventas", 1, "atendida", "1000")] * 3,
    ]
    marca = uuidlib.uuid4().hex[:8]
    async with async_session() as s:
        for i, (tid, cola, espera, resultado, agente) in enumerate(filas):
            s.add(CallLog(
                tenant_id=tid, uuid=f"rep-{marca}-{i}", direction="inbound", status="answered" if agente else "cancelled",
                billsec=120 if agente else 0, started_at=hoy, cola=cola, cola_espera_s=espera,
                cola_resultado=resultado, cola_agente=agente,
            ))
        await s.commit()
    yield marca
    async with async_session() as s:
        await s.execute(delete(CallLog).where(CallLog.uuid.like(f"rep-{marca}-%")))
        await s.commit()


async def test_reporte_de_entrantes(cliente, mundo, llamadas_de_cola):
    hoy = date.today().isoformat()
    desde = (date.today() - timedelta(days=1)).isoformat()
    r = await cliente.get(f"/api/reportes/entrantes?desde={desde}&hasta={hoy}&umbral_s=20", headers=mundo.alfa.cabeceras())
    assert r.status_code == 200, r.text
    d = r.json()
    ventas = next(f for f in d["filas"] if f["cola"] == "ventas")
    assert (ventas["ofrecidas"], ventas["atendidas"], ventas["abandonadas"], ventas["desbordadas"]) == (10, 7, 2, 1)
    # A tiempo: 5 de 9 (el abandono de 2 s no cuenta en el nivel de servicio).
    assert ventas["atendidas_en_umbral"] == 5 and ventas["nivel_servicio_pct"] == 55.6
    assert ventas["abandono_pct"] == 20.0 and ventas["espera_max_s"] == 60
    assert ventas["espera_promedio_s"] == round((5 * 10 + 2 * 45) / 7, 1)
    assert d["total"]["ofrecidas"] == 12  # sin las de beta
    assert sum(h["ofrecidas"] for h in d["por_hora"]) == 12 and len(d["por_hora"]) == 24
    agente = d["por_agente"][0]
    assert agente["extension"] == "1000" and agente["atendidas"] == 9 and agente["nombre"] == f"Recepcion {mundo.alfa.marca}"
    # Con otra meta cambia el nivel de servicio.
    r60 = (await cliente.get(f"/api/reportes/entrantes?desde={desde}&hasta={hoy}&umbral_s=60&cola=ventas",
                             headers=mundo.alfa.cabeceras())).json()
    assert [f["cola"] for f in r60["filas"]] == ["ventas"] and r60["filas"][0]["nivel_servicio_pct"] == 77.8
    csv = await cliente.get(f"/api/reportes/entrantes?desde={desde}&hasta={hoy}&formato=csv", headers=mundo.alfa.cabeceras())
    assert csv.status_code == 200 and "Nivel de servicio %" in csv.text and "ventas" in csv.text
    # El asesor no ve reportes.
    asesor = await cliente.get(f"/api/reportes/entrantes?desde={desde}&hasta={hoy}", headers=mundo.alfa.cabeceras(permissions.ASESOR))
    assert asesor.status_code == 403


# --- Alertas de operación ----------------------------------------------------------------------


def _de(hallazgos, tenant_id):
    return {k: d for t, k, d in hallazgos if t == tenant_id}


async def test_licencia_por_vencer_y_vencida(zeta):
    ahora = datetime.utcnow()
    async with async_session() as s:
        lic = (await s.execute(select(License).where(License.tenant_id == zeta["tenant"]))).scalar_one()
        lic.expires_at = ahora + timedelta(days=3, hours=1)
        await s.commit()
        assert "vence en 3 día" in _de(await alertas.detectar_operacion(s, ahora), zeta["tenant"])["licencia_vence"]
        lic.expires_at = ahora - timedelta(hours=1)
        await s.commit()
        assert "licencia_vencida" in _de(await alertas.detectar_operacion(s, ahora), zeta["tenant"])


async def test_proveedor_desconectado(zeta, monkeypatch):
    async with async_session() as s:
        s.add(Trunk(tenant_id=zeta["tenant"], name="claro", gateway_host="sip.claro.test", register_enabled=True))
        s.add(Trunk(tenant_id=zeta["tenant"], name="porip", gateway_host="sip.ip.test", register_enabled=False))
        await s.commit()
    pedidos = []

    async def estado(nombre, tenant_id=None):
        pedidos.append((nombre, tenant_id))
        return {"state": "FAIL_WAIT"}

    monkeypatch.setattr(esl, "gateway_status", estado)
    async with async_session() as s:
        detalle = _de(await alertas.detectar_operacion(s), zeta["tenant"])["troncal_caida"]
    assert "«claro»" in detalle
    assert not any(n.endswith("porip") for n, _ in pedidos)  # sin registro no hay estado que mirar
    # Se pregunta en el servidor de la empresa de la troncal.
    assert {t for n, t in pedidos if n.endswith("claro")} == {zeta["tenant"]}

    async def conectado(nombre, tenant_id=None):
        return {"state": "REGED"}

    monkeypatch.setattr(esl, "gateway_status", conectado)
    async with async_session() as s:
        assert "troncal_caida" not in _de(await alertas.detectar_operacion(s), zeta["tenant"])
    async with async_session() as s:
        await s.execute(delete(Trunk).where(Trunk.tenant_id == zeta["tenant"]))
        await s.commit()


async def test_abandono_alto_en_un_grupo(zeta):
    ahora = datetime.utcnow()
    async with async_session() as s:
        for i, resultado in enumerate(["abandonada"] * 2 + ["atendida"] * 3):
            s.add(CallLog(tenant_id=zeta["tenant"], uuid=f"ab-{zeta['tenant']}-{i}", direction="inbound",
                          status="answered", started_at=ahora - timedelta(minutes=5), cola="ventas",
                          cola_espera_s=30, cola_resultado=resultado))
        await s.commit()
        hallado = _de(await alertas.detectar_operacion(s, ahora), zeta["tenant"])
    assert "2 de 5" in hallado["abandono_alto"]
    # Una hora después ya no está en la ventana.
    async with async_session() as s:
        assert "abandono_alto" not in _de(await alertas.detectar_operacion(s, ahora + timedelta(hours=1)), zeta["tenant"])


async def test_las_alertas_llegan_por_correo_a_los_administradores(zeta, monkeypatch):
    enviados = []

    async def correo(para, asunto, cuerpo, adjuntos):
        enviados.append((para, asunto, cuerpo))

    monkeypatch.setattr(reportes_programados, "correo_configurado", lambda: True)
    monkeypatch.setattr(reportes_programados, "enviar_correo", correo)
    async with async_session() as s:
        from app.models import User

        admin = (await s.execute(select(User).where(User.tenant_id == zeta["tenant"]))).scalar_one()
        admin.email = "jefe@zeta.test"
        lic = (await s.execute(select(License).where(License.tenant_id == zeta["tenant"]))).scalar_one()
        lic.expires_at = datetime.utcnow() + timedelta(days=2)
        await s.commit()
    ahora = datetime.utcnow()
    async with async_session() as s:
        creadas = await alertas.revisar(s, ahora)
    assert any(a.tenant_id == zeta["tenant"] and a.kind == "licencia_vence" for a in creadas)
    mio = [e for e in enviados if e[0] == ["jefe@zeta.test"]]
    assert mio and "por vencer" in mio[0][1]
    # La de licencia se repite a lo sumo una vez al día.
    async with async_session() as s:
        otra = await alertas.revisar(s, ahora + timedelta(hours=7))
    assert not [a for a in otra if a.tenant_id == zeta["tenant"] and a.kind == "licencia_vence"]
    async with async_session() as s:
        await s.execute(delete(SecurityAlert).where(SecurityAlert.tenant_id == zeta["tenant"]))
        await s.commit()


# --- Ficha de quien llama ------------------------------------------------------------------------


async def test_ficha_de_quien_llama(cliente, mundo):
    tel = f"31{uuidlib.uuid4().int % 10**8:08d}"
    async with async_session() as s:
        c = Contacto(tenant_id=mundo.alfa.id, nombre="Ana Cliente", telefono=tel, telefono_clave=tel, ciudad="Cali")
        s.add(c)
        await s.flush()
        s.add(Nota(tenant_id=mundo.alfa.id, contacto_id=c.id, texto="Prefiere que la llamen en la tarde", autor="Luis"))
        s.add(NoLlamar(tenant_id=mundo.alfa.id, telefono=tel, telefono_clave=tel, motivo="pidió"))
        s.add(CallLog(tenant_id=mundo.alfa.id, uuid=f"fi-{tel}", direction="inbound", status="answered",
                      caller_number=f"+57{tel}", started_at=datetime.utcnow(), cola="ventas"))
        await s.commit()
    asesor = mundo.alfa.cabeceras(permissions.ASESOR)
    r = await cliente.get(f"/api/llamada/ficha?numero=%2B57{tel}", headers=asesor)
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["contacto"]["nombre"] == "Ana Cliente" and f["contacto"]["ciudad"] == "Cali"
    assert f["no_llamar"] is True
    assert [n["texto"] for n in f["notas"]] == ["Prefiere que la llamen en la tarde"]
    assert f["llamadas"][0]["cola"] == "ventas"
    # Otra empresa con el mismo número no ve nada de alfa.
    ajena = (await cliente.get(f"/api/llamada/ficha?numero={tel}", headers=mundo.beta.cabeceras(permissions.ASESOR))).json()
    assert ajena["contacto"] is None and ajena["notas"] == [] and ajena["llamadas"] == [] and not ajena["no_llamar"]
    # Una extensión interna no se busca.
    corta = (await cliente.get("/api/llamada/ficha?numero=1001", headers=asesor)).json()
    assert corta["contacto"] is None and corta["llamadas"] == []
