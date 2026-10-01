"""Verificación en dos pasos (core/mfa.py y /api/auth/mfa/*)."""

import pytest

from app.core import mfa, permissions
from app.core.config import settings
from app.core.database import async_session
from app.core.security import hash_password
from app.models import User

# RFC 6238, apéndice B: secreto ASCII "12345678901234567890" en base32.
_SECRETO_RFC = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.mark.parametrize("instante,esperado", [(59, "287082"), (1111111109, "081804"), (2000000000, "279037")])
def test_vectores_de_la_rfc(instante, esperado):
    assert mfa.codigo(_SECRETO_RFC, mfa.paso_actual(instante)) == esperado


def test_ventana_y_no_reuso():
    ahora = 1_700_000_000
    paso = mfa.paso_actual(ahora)
    assert mfa.verificar(_SECRETO_RFC, mfa.codigo(_SECRETO_RFC, paso - 1), ahora=ahora) == paso - 1
    assert mfa.verificar(_SECRETO_RFC, mfa.codigo(_SECRETO_RFC, paso + 1), ahora=ahora) == paso + 1
    assert mfa.verificar(_SECRETO_RFC, mfa.codigo(_SECRETO_RFC, paso - 2), ahora=ahora) is None
    assert mfa.verificar(_SECRETO_RFC, mfa.codigo(_SECRETO_RFC, paso), ultimo_paso=paso, ahora=ahora) is None
    for malo in ("", "12345", "abcdef", "1234567"):
        assert mfa.verificar(_SECRETO_RFC, malo, ahora=ahora) is None


def test_uri_y_codigos_de_recuperacion():
    assert mfa.uri("ABC", "ana").startswith("otpauth://totp/NSPBX%3Aana?secret=ABC&issuer=NSPBX")
    codigos = mfa.nuevos_codigos_recuperacion()
    assert len(set(codigos)) == mfa.CODIGOS_RECUPERACION
    assert mfa.hash_recuperacion(codigos[0].upper()) == mfa.hash_recuperacion(codigos[0])


@pytest.fixture
def obligatorio(monkeypatch):
    monkeypatch.setattr(settings, "mfa_obligatorio", "plataforma,admin")


@pytest.fixture
async def admin_nuevo(mundo):
    """Un admin de alfa sin MFA, que entra por el login de verdad."""
    import secrets

    nombre = f"mfa-{secrets.token_hex(3)}"
    async with async_session() as s:
        u = User(
            tenant_id=mundo.alfa.id, username=nombre, full_name="Admin MFA",
            password_hash=hash_password("clave-de-prueba-mfa"), role=permissions.ADMIN, enabled=True,
        )
        s.add(u)
        await s.commit()
        return {"id": u.id, "username": nombre, "password": "clave-de-prueba-mfa"}


async def _login(cliente, u) -> dict:
    resp = await cliente.post("/api/auth/login", json={"username": u["username"], "password": u["password"]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _cab(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _activar(cliente, token: str) -> tuple[str, dict]:
    ini = await cliente.post("/api/auth/mfa/iniciar", headers=_cab(token))
    assert ini.status_code == 200, ini.text
    secreto = ini.json()["secreto"]
    assert ini.json()["uri"].startswith("otpauth://totp/")
    malo = await cliente.post("/api/auth/mfa/activar", headers=_cab(token), json={"codigo": "000000"})
    assert malo.status_code == 400
    ok = await cliente.post(
        "/api/auth/mfa/activar", headers=_cab(token), json={"codigo": mfa.codigo(secreto, mfa.paso_actual())}
    )
    assert ok.status_code == 200, ok.text
    return secreto, ok.json()


async def test_admin_sin_mfa_solo_puede_activarlo(cliente, admin_nuevo, obligatorio):
    sesion = await _login(cliente, admin_nuevo)
    assert sesion["mfa_pendiente"] is True and sesion["mfa_activo"] is False
    bloqueada = await cliente.get("/api/extensions", headers=_cab(sesion["token"]))
    assert bloqueada.status_code == 403 and bloqueada.headers.get("x-mfa-requerido") == "1"
    assert (await cliente.get("/api/auth/me", headers=_cab(sesion["token"]))).status_code == 200

    _, activado = await _activar(cliente, sesion["token"])
    assert len(activado["codigos_recuperacion"]) == mfa.CODIGOS_RECUPERACION
    # La sesión vieja se abrió sin segundo paso: queda cerrada.
    assert (await cliente.get("/api/auth/me", headers=_cab(sesion["token"]))).status_code == 401
    nueva = activado["sesion"]
    assert nueva["mfa_activo"] is True and nueva["mfa_pendiente"] is False
    assert (await cliente.get("/api/extensions", headers=_cab(nueva["token"]))).status_code == 200


async def test_login_con_mfa_pide_el_codigo(cliente, admin_nuevo, obligatorio):
    secreto, activado = await _activar(cliente, (await _login(cliente, admin_nuevo))["token"])

    paso1 = await _login(cliente, admin_nuevo)
    assert paso1 == {"mfa_requerido": True, "mfa_token": paso1["mfa_token"]}, "sin sesión todavía"
    # El token intermedio no sirve como sesión.
    assert (await cliente.get("/api/auth/me", headers=_cab(paso1["mfa_token"]))).status_code == 401

    # El código ya usado al activar no vuelve a servir.
    usado = mfa.codigo(secreto, mfa.paso_actual())
    repetido = await cliente.post("/api/auth/mfa/verificar", json={"mfa_token": paso1["mfa_token"], "codigo": usado})
    assert repetido.status_code == 401
    # El siguiente sí.
    siguiente = mfa.codigo(secreto, mfa.paso_actual() + 1)
    ok = await cliente.post("/api/auth/mfa/verificar", json={"mfa_token": paso1["mfa_token"], "codigo": siguiente})
    assert ok.status_code == 200, ok.text
    assert (await cliente.get("/api/extensions", headers=_cab(ok.json()["token"]))).status_code == 200

    # Código de recuperación: sirve una vez.
    recuperacion = activado["codigos_recuperacion"][0]
    paso1 = await _login(cliente, admin_nuevo)
    ok = await cliente.post("/api/auth/mfa/verificar", json={"mfa_token": paso1["mfa_token"], "codigo": recuperacion})
    assert ok.status_code == 200
    paso1 = await _login(cliente, admin_nuevo)
    otra_vez = await cliente.post("/api/auth/mfa/verificar", json={"mfa_token": paso1["mfa_token"], "codigo": recuperacion})
    assert otra_vez.status_code == 401


async def test_token_intermedio_alterado_o_de_sesion_no_sirve(cliente, mundo):
    for token in ("basura", mundo.alfa.token()):
        resp = await cliente.post("/api/auth/mfa/verificar", json={"mfa_token": token, "codigo": "123456"})
        assert resp.status_code == 401


async def test_un_rol_obligado_no_puede_desactivarla(cliente, admin_nuevo, obligatorio):
    _, activado = await _activar(cliente, (await _login(cliente, admin_nuevo))["token"])
    resp = await cliente.post(
        "/api/auth/mfa/desactivar", headers=_cab(activado["sesion"]["token"]),
        json={"password": admin_nuevo["password"], "codigo": activado["codigos_recuperacion"][1]},
    )
    assert resp.status_code == 403


async def test_otro_admin_la_restablece_y_nadie_la_propia(cliente, mundo, admin_nuevo, obligatorio):
    _, activado = await _activar(cliente, (await _login(cliente, admin_nuevo))["token"])
    token_viejo = activado["sesion"]["token"]

    propia = await cliente.post(f"/api/users/{admin_nuevo['id']}/mfa/reset", headers=_cab(token_viejo))
    assert propia.status_code == 400

    # En las pruebas los admins sembrados no tienen MFA: se les activa en la
    # base para que puedan operar con la obligación encendida.
    sembrados = [mundo.alfa.usuarios[permissions.ADMIN], mundo.beta.usuarios[permissions.ADMIN]]
    async with async_session() as s:
        for uid in sembrados:
            u = await s.get(User, uid)
            u.mfa_enabled, u.mfa_secret = True, mfa.nuevo_secreto()
        await s.commit()
    try:
        resp = await cliente.post(f"/api/users/{admin_nuevo['id']}/mfa/reset", headers=mundo.alfa.cabeceras())
        assert resp.status_code == 200 and resp.json()["mfa_enabled"] is False
        # Sus sesiones se cerraron, y al entrar vuelve a tener que activarla.
        assert (await cliente.get("/api/auth/me", headers=_cab(token_viejo))).status_code == 401
        assert (await _login(cliente, admin_nuevo))["mfa_pendiente"] is True
        # Otra empresa no puede restablecer usuarios de alfa.
        ajena = await cliente.post(f"/api/users/{admin_nuevo['id']}/mfa/reset", headers=mundo.beta.cabeceras())
        assert ajena.status_code == 404
    finally:
        async with async_session() as s:
            for uid in sembrados:
                u = await s.get(User, uid)
                u.mfa_enabled, u.mfa_secret = False, None
            await s.commit()


async def test_consola_de_logs_exige_mfa_a_quien_le_falta(mundo, obligatorio):
    from app.api.logs_ws import _usuario_del_token
    from app.core.database import app_session

    async with app_session() as session:
        assert await _usuario_del_token(mundo.alfa.token(), session) is None
