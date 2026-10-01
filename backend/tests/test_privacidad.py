"""Derechos del titular (consultar y suprimir) y borrado de empresas.

El mismo teléfono existe en alfa y en beta a propósito: la solicitud que
atiende alfa no puede mostrar ni tocar lo que beta guarda de esa persona.
"""

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import async_session, engine
from app.models import (
    AiCallUsage, Appointment, AuditLog, CallLog, Campaign, CampaignNumber, Debt, PaymentPromise, Tenant, VoiceBot,
)
from app.services import greetings

from .conftest import foto_de_empresa

TEL = "3157778899"


async def _sembrar_titular(tenant_id: int, marca: str) -> dict:
    """Todo lo que una empresa puede guardar de una persona, con TEL escrito
    de distintas formas, más una llamada de otra persona como control."""
    ruta = os.path.join(settings.recordings_dir, f"t{tenant_id}", f"titular-{marca}.wav")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(b"RIFF" + marca.encode())
    async with async_session() as s:
        camp = (await s.execute(select(Campaign).where(Campaign.tenant_id == tenant_id))).scalars().first()
        deuda = Debt(tenant_id=tenant_id, phone=f"+57 {TEL}", debtor_name=f"Titular {marca}", amount=10)
        s.add(deuda)
        await s.flush()
        filas = [
            Appointment(tenant_id=tenant_id, patient_name=f"Titular {marca}", phone=TEL,
                        appointment_date=datetime.utcnow() + timedelta(days=2)),
            PaymentPromise(tenant_id=tenant_id, debt_id=deuda.id, phone=f"57{TEL}", debtor_name=f"Titular {marca}",
                           promise_date=datetime.utcnow()),
            CampaignNumber(tenant_id=tenant_id, campaign_id=camp.id, phone=TEL, extra_data=f'{{"cliente": "{marca}"}}'),
            CallLog(tenant_id=tenant_id, uuid=f"tit-in-{marca}", caller_number=f"57{TEL}", caller_name=f"Titular {marca}",
                    callee_number="1000", direction="inbound", status="answered", summary=f"Habló de su salud {marca}",
                    recording_path=f"{settings.fs_recordings_dir}/t{tenant_id}/titular-{marca}.wav"),
            CallLog(tenant_id=tenant_id, uuid=f"tit-out-{marca}", caller_number="1000", callee_number=TEL,
                    direction="outbound", status="answered"),
            CallLog(tenant_id=tenant_id, uuid=f"otro-{marca}", caller_number="3001110000", callee_number="1000",
                    direction="inbound", status="answered", summary=f"Otra persona {marca}"),
            AiCallUsage(tenant_id=tenant_id, call_uuid=f"tit-ia-{marca}", phone=TEL, action_patient_name=f"Titular {marca}"),
        ]
        s.add_all(filas)
        await s.commit()
    return {"grabacion": ruta}


@pytest.fixture(scope="module")
async def titular(mundo):
    datos = {e: await _sembrar_titular(getattr(mundo, e).id, getattr(mundo, e).marca) for e in ("alfa", "beta")}
    yield datos
    async with engine.begin() as conn:
        for t in ("payment_promises", "appointments", "debts", "campaign_numbers", "ai_call_usage"):
            await conn.execute(text(f"DELETE FROM {t} WHERE regexp_replace(phone, '[^0-9]', '', 'g') LIKE :p"),
                               {"p": f"%{TEL}"})
        await conn.execute(text("DELETE FROM call_logs WHERE uuid LIKE 'tit-%' OR uuid LIKE 'otro-%'"))
        await conn.execute(text("DELETE FROM ai_call_usage WHERE call_uuid LIKE 'tit-ia-%'"))


async def test_consultar_devuelve_todo_lo_del_titular_y_nada_de_otra_empresa(mundo, cliente, titular):
    resp = await cliente.post("/api/privacidad/titular/consultar", json={"telefono": f"+57 {TEL}"},
                              headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, resp.text
    datos = resp.json()["datos"]
    assert {k: len(v) for k, v in datos.items()} == {
        "citas": 1, "deudas": 1, "promesas_de_pago": 1, "numeros_de_campana": 1,
        "llamadas": 2, "conversaciones_voicebot": 1,
    }
    assert "Titular alfa" in resp.text and "Habló de su salud alfa" in resp.text
    assert mundo.beta.marca not in resp.text
    assert "Otra persona" not in resp.text
    assert "recording_path" not in resp.text and "tenant_id" not in resp.text
    assert any(c["tiene_grabacion"] for c in datos["llamadas"])


@pytest.mark.parametrize("telefono", ["", "1000", "12345", "anonymous"])
async def test_un_numero_corto_no_identifica_a_nadie(mundo, cliente, titular, telefono):
    """Una extensión o un caller-ID vacío coincidiría con medio mundo."""
    resp = await cliente.post("/api/privacidad/titular/consultar", json={"telefono": telefono},
                              headers=mundo.alfa.cabeceras())
    assert resp.status_code == 422


async def test_solo_el_administrador(mundo, cliente, titular):
    for rol in ("supervisor", "asesor"):
        resp = await cliente.post("/api/privacidad/titular/consultar", json={"telefono": TEL},
                                  headers=mundo.alfa.cabeceras(rol))
        assert resp.status_code == 403, rol
    resp = await cliente.post("/api/privacidad/titular/consultar", json={"telefono": TEL},
                              headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 403


async def test_suprimir_exige_confirmacion(mundo, cliente, titular):
    resp = await cliente.post("/api/privacidad/titular/suprimir",
                              json={"telefono": TEL, "confirmacion": "3150000000"}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 422
    async with async_session() as s:
        assert (await s.execute(select(Appointment).where(Appointment.phone == TEL))).scalars().all()


async def test_suprimir_borra_lo_de_alfa_y_deja_intacto_lo_de_beta(mundo, cliente, titular):
    beta_antes = await foto_de_empresa(mundo.beta.id)

    resp = await cliente.post("/api/privacidad/titular/suprimir",
                              json={"telefono": TEL, "confirmacion": f"+57 {TEL}"}, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "promesas_de_pago": 1, "citas": 1, "deudas": 1, "numeros_de_campana": 1,
        "llamadas_anonimizadas": 2, "grabaciones_borradas": 1, "conversaciones_anonimizadas": 1,
    }

    # Nada de alfa vuelve a aparecer en una consulta.
    resp = await cliente.post("/api/privacidad/titular/consultar", json={"telefono": TEL},
                              headers=mundo.alfa.cabeceras())
    assert all(v == [] for v in resp.json()["datos"].values()), resp.text

    async with engine.connect() as conn:
        llamadas = (await conn.execute(text(
            "SELECT uuid, caller_number, caller_name, callee_number, summary, recording_path "
            "FROM call_logs WHERE tenant_id = :t AND (uuid LIKE 'tit-%' OR uuid LIKE 'otro-%') ORDER BY uuid"
        ), {"t": mundo.alfa.id})).all()
        uso = (await conn.execute(text(
            "SELECT phone, action_patient_name FROM ai_call_usage WHERE call_uuid = 'tit-ia-alfa'"
        ))).one()
        texto_alfa = str((await foto_de_empresa(mundo.alfa.id)))
    por_uuid = {fila[0]: fila[1:] for fila in llamadas}
    # La llamada se conserva (facturación, métricas) sin identificar a nadie.
    assert por_uuid["tit-in-alfa"] == ("anonimizado", None, "1000", None, None)
    assert por_uuid["tit-out-alfa"] == ("1000", None, "anonimizado", None, None)
    # La de otra persona no se toca.
    assert por_uuid["otro-alfa"][0] == "3001110000" and por_uuid["otro-alfa"][3] == "Otra persona alfa"
    assert uso == (None, None)
    assert TEL not in texto_alfa and "Titular alfa" not in texto_alfa
    assert not os.path.exists(titular["alfa"]["grabacion"])

    # Beta: mismo teléfono, nada cambió (ni la grabación en disco).
    assert await foto_de_empresa(mundo.beta.id) == beta_antes
    assert os.path.exists(titular["beta"]["grabacion"])


async def test_la_auditoria_no_guarda_el_telefono_completo(mundo, cliente, titular):
    await cliente.post("/api/privacidad/titular/consultar", json={"telefono": TEL}, headers=mundo.alfa.cabeceras())
    async with engine.connect() as conn:
        filas = (await conn.execute(text(
            "SELECT detail::text FROM audit_log WHERE tenant_id = :t AND action LIKE '%/api/privacidad/%'"
        ), {"t": mundo.alfa.id})).scalars().all()
    assert filas and all(TEL not in f for f in filas)
    assert any("8899" in f for f in filas)


async def test_borrar_empresa_borra_sus_datos_y_sus_archivos(mundo, cliente):
    """Antes fallaba con cualquier empresa que tuviera actividad: la clave
    foránea de la auditoría intentaba modificar registros de solo agregar."""
    resp = await cliente.post(
        "/api/tenants", headers=mundo.cabeceras_plataforma(),
        json={"name": "Empresa efimera", "slug": "efimera", "sip_domain": "efimera.test",
              "admin_username": "admin-efimera", "admin_full_name": "Admin efimera"},
    )
    assert resp.status_code in (200, 201), resp.text
    tid = resp.json()["id"]

    async with async_session() as s:
        bot = VoiceBot(tenant_id=tid, name="bot-efimero", bot_type="ivr")
        s.add(bot)
        s.add(AuditLog(tenant_id=tid, action="POST /api/x", result="ok"))
        await s.commit()
        bot_id = bot.id
    greetings.save_greeting(bot_id, "greeting.wav", b"RIFF")
    carpeta = os.path.join(settings.recordings_dir, f"t{tid}", "2026", "01", "01")
    os.makedirs(carpeta, exist_ok=True)
    open(os.path.join(carpeta, "llamada.wav"), "wb").close()
    cola = os.path.join(settings.recordings_dir, f"queue_t{tid}_x.wav")
    vecina = os.path.join(settings.recordings_dir, f"queue_t{tid}0_x.wav")
    open(cola, "wb").close()
    open(vecina, "wb").close()
    alfa_antes = await foto_de_empresa(mundo.alfa.id)

    resp = await cliente.delete(f"/api/tenants/{tid}", headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 204, resp.text

    async with async_session() as s:
        assert await s.get(Tenant, tid) is None
        assert (await s.execute(select(VoiceBot).where(VoiceBot.tenant_id == tid))).first() is None
    async with engine.connect() as conn:
        # La auditoría sobrevive y sigue diciendo de qué empresa era.
        assert (await conn.execute(text("SELECT count(*) FROM audit_log WHERE tenant_id = :t"), {"t": tid})).scalar() >= 1
    assert not os.path.exists(os.path.join(settings.recordings_dir, f"t{tid}"))
    assert not os.path.exists(cola)
    assert os.path.exists(vecina)  # queue_t<id>0_ es de otra empresa
    os.unlink(vecina)
    assert not list(greetings._local_bots_dir().glob(f"bot_{bot_id}.*"))
    assert await foto_de_empresa(mundo.alfa.id) == alfa_antes
