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
        await s.execute(delete(VerificacionVivo).where(VerificacionVivo.tenant_id == tenant_id))
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
