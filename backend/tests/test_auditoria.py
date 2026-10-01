"""Registro de auditoría y request_id (core/auditoria.py)."""

import logging

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core import auditoria, permissions
from app.core.database import app_engine, async_session, engine
from app.models import AuditLog

from .conftest import requiere_rls


async def _ultimas(n: int = 20, **filtros) -> list[AuditLog]:
    async with async_session() as s:
        consulta = select(AuditLog).order_by(AuditLog.id.desc()).limit(n)
        for campo, valor in filtros.items():
            consulta = consulta.where(getattr(AuditLog, campo) == valor)
        return list((await s.execute(consulta)).scalars().all())


async def test_un_cambio_queda_registrado_sin_secretos(cliente, mundo):
    ext = mundo.alfa.ids["extension"]
    resp = await cliente.put(
        f"/api/extensions/{ext}", headers={**mundo.alfa.cabeceras(), "User-Agent": "prueba/1.0"},
        json={"password": "Otra-Clave-Segura-77", "caller_id_name": "Recepcion alfa"},  # gitleaks:allow (clave de prueba)
    )
    assert resp.status_code == 200, resp.text
    rid = resp.headers["x-request-id"]
    [fila] = await _ultimas(1, request_id=rid)
    assert fila.tenant_id == mundo.alfa.id
    assert fila.user_id == mundo.alfa.usuarios[permissions.ADMIN]
    assert fila.actor == "admin-alfa (admin)"
    assert fila.action == "PUT /api/extensions/{extension_id}"
    assert fila.resource == f"extension_id={ext}"
    assert fila.result == "ok"
    assert fila.user_agent == "prueba/1.0"
    assert fila.detail == {"password": "***", "caller_id_name": "Recepcion alfa"}
    assert "Otra-Clave-Segura-77" not in str(fila.detail)
    # Se deja la extensión como estaba para el resto de las pruebas.
    await cliente.put(f"/api/extensions/{ext}", headers=mundo.alfa.cabeceras(), json={"password": "clave-sip-alfa"})


async def test_un_intento_sobre_otra_empresa_queda_como_denegado(cliente, mundo):
    resp = await cliente.delete(f"/api/trunks/{mundo.beta.ids['trunk']}", headers=mundo.alfa.cabeceras())
    assert resp.status_code == 404
    [fila] = await _ultimas(1, request_id=resp.headers["x-request-id"])
    assert fila.result == "denegado"
    assert fila.tenant_id == mundo.alfa.id, "queda en la empresa de quien lo intentó"


async def test_login_fallido_registra_quien_sin_la_contrasenia(cliente, mundo):
    resp = await cliente.post("/api/auth/login", json={"username": "admin-alfa", "password": "no-es-esta-clave"})
    assert resp.status_code == 401
    [fila] = await _ultimas(1, request_id=resp.headers["x-request-id"])
    assert fila.action == "POST /api/auth/login" and fila.result == "denegado"
    assert fila.tenant_id == mundo.alfa.id and fila.actor == "admin-alfa"
    assert fila.detail["password"] == "***"


async def test_login_de_usuario_inexistente_queda_sin_empresa(cliente, mundo):
    resp = await cliente.post("/api/auth/login", json={"username": "nadie-zz", "password": "x" * 12})
    [fila] = await _ultimas(1, request_id=resp.headers["x-request-id"])
    assert fila.tenant_id is None and fila.actor == "nadie-zz"


async def test_escuchar_una_grabacion_queda_registrado(cliente, mundo):
    resp = await cliente.get(f"/api/calls/{mundo.alfa.ids['call']}/recording", headers=mundo.alfa.cabeceras())
    [fila] = await _ultimas(1, request_id=resp.headers["x-request-id"])
    assert fila.action == "GET /api/calls/{call_id}/recording"


async def test_las_lecturas_comunes_no_se_registran(cliente, mundo):
    resp = await cliente.get("/api/extensions", headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200
    assert not await _ultimas(1, request_id=resp.headers["x-request-id"])


@pytest.mark.parametrize(
    "entrante,se_respeta",
    [("abc12345-def", True), ("corto", False), ("con espacios no vale", False), ("x" * 100, False)],
)
async def test_request_id_entrante(cliente, mundo, entrante, se_respeta):
    resp = await cliente.get("/health", headers={"X-Request-ID": entrante})
    assert (resp.headers["x-request-id"] == entrante) is se_respeta


async def test_cada_empresa_ve_solo_su_auditoria(cliente, mundo):
    await cliente.put(
        f"/api/campaigns/{mundo.beta.ids['campaign']}", headers=mundo.beta.cabeceras(), json={"retries": 1}
    )
    propia = (await cliente.get("/api/security/auditoria", headers=mundo.alfa.cabeceras())).json()
    assert propia and all("zzbeta" not in str(f) and "admin-beta" not in str(f["actor"]) for f in propia)
    ajena = (await cliente.get("/api/security/auditoria", headers=mundo.beta.cabeceras())).json()
    assert any(f["actor"] == "admin-beta (admin)" for f in ajena)
    todas = (await cliente.get("/api/plataforma/auditoria", headers=mundo.cabeceras_plataforma())).json()
    actores = {f["actor"] for f in todas}
    assert "admin-beta (admin)" in actores and "admin-alfa (admin)" in actores
    assert (await cliente.get("/api/security/auditoria", headers=mundo.alfa.cabeceras(permissions.SUPERVISOR))).status_code == 403


async def test_filtros_de_la_auditoria(cliente, mundo):
    filas = (
        await cliente.get("/api/security/auditoria", headers=mundo.alfa.cabeceras(), params={"resultado": "denegado"})
    ).json()
    assert filas and all(f["resultado"] == "denegado" for f in filas)


@requiere_rls
async def test_la_aplicacion_no_puede_reescribir_ni_borrar_la_auditoria(mundo):
    for sql in ("UPDATE audit_log SET result = 'ok'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        async with app_engine.connect() as conn:
            tx = await conn.begin()
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mundo.alfa.id)})
            with pytest.raises(DBAPIError, match="permission denied"):
                await conn.execute(text(sql))
            await tx.rollback()


async def test_ni_el_duenio_puede_modificar_una_fila(mundo):
    async with engine.connect() as conn:
        tx = await conn.begin()
        with pytest.raises(DBAPIError, match="solo agregar"):
            await conn.execute(text("UPDATE audit_log SET result = 'ok'"))
        await tx.rollback()


def test_ocultar_secretos():
    datos = {
        "username": "ana", "password": "x", "fs_esl_password": "y", "ai_llm_api_key": "z",
        "turnstile_secret": "w", "texto": "a" * 500, "anidado": [{"token": "t", "ok": 1}],
    }
    limpio = auditoria.ocultar_secretos(datos)
    assert limpio["username"] == "ana"
    assert {limpio[k] for k in ("password", "fs_esl_password", "ai_llm_api_key", "turnstile_secret")} == {"***"}
    assert limpio["anidado"] == [{"token": "***", "ok": 1}]
    assert len(limpio["texto"]) < 210


def test_los_telefonos_quedan_enmascarados():
    """El registro no se puede borrar: el teléfono de un tercero no entra entero."""
    datos = {"numbers": [{"phone": "+57 300 123 4567"}], "telefono": "3001234567", "destination": 1001,
             "softphone": True, "name": "Ana"}
    limpio = auditoria.ocultar_secretos(datos)
    assert limpio["numbers"] == [{"phone": "…4567"}]
    assert limpio["telefono"] == "…4567"
    assert limpio["destination"] == "…"
    assert limpio["softphone"] is True and limpio["name"] == "Ana"


def test_los_logs_llevan_el_request_id():
    token = auditoria.request_id_actual.set("rid-de-prueba")
    try:
        registro = logging.LogRecord("x", logging.INFO, __file__, 1, "hola", None, None)
        assert auditoria.FiltroRequestId().filter(registro)
        assert registro.request_id == "rid-de-prueba"
    finally:
        auditoria.request_id_actual.reset(token)


async def test_la_retencion_borra_solo_lo_viejo(mundo):
    from datetime import datetime, timedelta

    from app.workers.maintenance import maintenance

    async with async_session() as s:
        s.add(AuditLog(action="PRUEBA vieja", result="ok", created_at=datetime.utcnow() - timedelta(days=400)))
        s.add(AuditLog(action="PRUEBA nueva", result="ok", created_at=datetime.utcnow() - timedelta(days=10)))
        await s.commit()
    await maintenance._purgar_auditoria()
    acciones = {f.action for f in await _ultimas(500)}
    assert "PRUEBA nueva" in acciones and "PRUEBA vieja" not in acciones


# Rutas que modifican algo y NO se auditan, cada una con su motivo. Agregar
# una acá tiene que ser una decisión, no un olvido.
_SIN_AUDITORIA = {
    "/api/webcall/": "widget anónimo de los sitios de los clientes: mucho volumen y sin usuario",
    "/api/auth/refresh": "renovación rutinaria de la sesión de la app móvil",
    "/api/csp-report": "avisos de CSP de los navegadores, sin usuario (app/api/csp.py)",
}


def test_toda_ruta_que_modifica_queda_auditada():
    """El middleware audita por método, no por lista de rutas: una ruta nueva
    queda auditada sola. Esto lo comprueba contra TODAS las de la aplicación
    (incluidas las de emergencia, salientes, campañas y la API pública)."""
    from fastapi.routing import APIRoute

    from app.main import app

    sin = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"):
            continue
        for metodo in r.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            if not auditoria.se_audita(metodo, r.path) and not r.path.startswith(tuple(_SIN_AUDITORIA)):
                sin.append(f"{metodo} {r.path}")
    assert not sin, f"Rutas que modifican y no se auditan: {sin}"
    assert set(_SIN_AUDITORIA) == set(auditoria._EXCLUIDAS), "la lista de excluidas cambió: revisar el motivo acá"


async def test_acciones_de_fraude_quedan_registradas(cliente, mundo, monkeypatch):
    """Lo que §5.6 exige registrar: rutas salientes, campañas y los
    controles de emergencia, con quién lo hizo."""
    from app.services import esl

    async def api(cmd):
        return "+OK"

    monkeypatch.setattr(esl, "api", api)
    cab = mundo.alfa.cabeceras()
    await cliente.put(f"/api/outbound-routes/{mundo.alfa.ids['outbound_route']}", json={"priority": 12}, headers=cab)
    await cliente.post(f"/api/campaigns/{mundo.alfa.ids['campaign']}/stop", headers=cab)
    await cliente.post("/api/system/salientes/colgar", headers=cab)
    async with engine.connect() as conn:
        acciones = set((await conn.execute(text(
            "SELECT action FROM audit_log WHERE tenant_id = :t AND actor LIKE 'admin-alfa%'"
        ), {"t": mundo.alfa.id})).scalars())
    for esperada in ("PUT /api/outbound-routes/{route_id}", "POST /api/campaigns/{campaign_id}/stop",
                     "POST /api/system/salientes/colgar"):
        assert esperada in acciones, (esperada, sorted(acciones)[:20])
