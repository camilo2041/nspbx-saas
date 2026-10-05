"""Sesiones abiertas: cada uno ve en qué equipos tiene la sesión abierta y
puede cerrar una o todas; un administrador saca a un usuario de todos sus
equipos y la plataforma a toda una empresa. Y el panel web no recibe un
refresh token que no usa."""

import uuid as uuidlib

import pytest

from app.core import permissions
from app.core.database import async_session
from app.core.security import hash_password
from app.models import License, Tenant, User

CLAVE = "clave-de-prueba-sesiones"  # gitleaks:allow


async def _usuario(tenant_id: int, rol: str = permissions.ASESOR) -> str:
    nombre = f"ses-{uuidlib.uuid4().hex[:8]}"
    async with async_session() as s:
        s.add(User(tenant_id=tenant_id, username=nombre, full_name=nombre, password_hash=hash_password(CLAVE), role=rol, enabled=True))
        await s.commit()
    return nombre


async def _entrar(cliente, usuario: str, **cliente_info) -> dict:
    r = await cliente.post("/api/auth/login", json={"username": usuario, "password": CLAVE, **cliente_info})
    assert r.status_code == 200, r.text
    return r.json()


def _cab(sesion: dict) -> dict:
    return {"Authorization": f"Bearer {sesion['token']}"}


async def test_la_app_recibe_refresh_y_el_panel_no(cliente, mundo):
    u = await _usuario(mundo.alfa.id)
    assert (await _entrar(cliente, u, plataforma="web"))["refresh_token"] is None
    assert (await _entrar(cliente, u, plataforma="android", dispositivo="Samsung SM-A515F · Android 13"))["refresh_token"]
    # Una app vieja que no dice de dónde entra lo sigue recibiendo.
    assert (await _entrar(cliente, u))["refresh_token"]


async def test_lista_cerrar_una_y_conservar_el_nombre_al_renovar(cliente, mundo):
    u = await _usuario(mundo.alfa.id)
    tel = await _entrar(cliente, u, plataforma="android", dispositivo="Moto G · Android 14")
    tablet = await _entrar(cliente, u, plataforma="ios", dispositivo="iPad")

    renovada = (await cliente.post("/api/auth/refresh", json={"refresh_token": tel["refresh_token"]})).json()
    lista = (await cliente.get("/api/auth/sesiones", headers=_cab(renovada))).json()
    assert sorted(x["dispositivo"] for x in lista) == ["Moto G · Android 14", "iPad"]

    ipad = next(x for x in lista if x["dispositivo"] == "iPad")
    assert (await cliente.delete(f"/api/auth/sesiones/{ipad['id']}", headers=_cab(renovada))).status_code == 204
    assert (await cliente.post("/api/auth/refresh", json={"refresh_token": tablet["refresh_token"]})).status_code == 401
    assert [x["dispositivo"] for x in (await cliente.get("/api/auth/sesiones", headers=_cab(renovada))).json()] == ["Moto G · Android 14"]


async def test_no_se_cierra_la_sesion_de_otro(cliente, mundo):
    dueno = await _entrar(cliente, await _usuario(mundo.alfa.id), plataforma="android")
    otro = await _entrar(cliente, await _usuario(mundo.beta.id), plataforma="android")
    id_otro = (await cliente.get("/api/auth/sesiones", headers=_cab(otro))).json()[0]["id"]
    assert (await cliente.delete(f"/api/auth/sesiones/{id_otro}", headers=_cab(dueno))).status_code == 404
    assert (await cliente.post("/api/auth/refresh", json={"refresh_token": otro["refresh_token"]})).status_code == 200


async def test_cerrar_todas_corta_tambien_la_actual(cliente, mundo):
    u = await _usuario(mundo.alfa.id)
    panel = await _entrar(cliente, u, plataforma="web")
    app = await _entrar(cliente, u, plataforma="android")
    assert (await cliente.post("/api/auth/sesiones/cerrar-todas", headers=_cab(panel))).status_code == 204
    assert (await cliente.get("/api/auth/me", headers=_cab(panel))).status_code == 401
    assert (await cliente.get("/api/auth/me", headers=_cab(app))).status_code == 401
    assert (await cliente.post("/api/auth/refresh", json={"refresh_token": app["refresh_token"]})).status_code == 401
    # Y puede volver a entrar con su contraseña.
    assert (await cliente.get("/api/auth/me", headers=_cab(await _entrar(cliente, u, plataforma="web")))).status_code == 200


async def test_el_administrador_saca_a_un_usuario(cliente, mundo):
    u = await _usuario(mundo.alfa.id)
    sesion = await _entrar(cliente, u, plataforma="android")
    async with async_session() as s:
        from sqlalchemy import select

        uid = (await s.execute(select(User.id).where(User.username == u))).scalar_one()
    # Un asesor no puede.
    assert (await cliente.post(f"/api/users/{uid}/cerrar-sesiones", headers=mundo.alfa.cabeceras(permissions.ASESOR))).status_code == 403
    assert (await cliente.post(f"/api/users/{uid}/cerrar-sesiones", headers=mundo.alfa.cabeceras())).status_code == 204
    assert (await cliente.get("/api/auth/me", headers=_cab(sesion))).status_code == 401
    assert (await cliente.post("/api/auth/refresh", json={"refresh_token": sesion["refresh_token"]})).status_code == 401


@pytest.fixture
async def kilo():
    async with async_session() as s:
        t = Tenant(name="Kilo", slug=f"kilo{uuidlib.uuid4().hex[:6]}", sip_domain=f"k{uuidlib.uuid4().hex[:6]}.test", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="pro", status="active"))
        await s.commit()
        return t.id


async def test_la_plataforma_saca_a_toda_una_empresa(cliente, mundo, kilo):
    de_kilo = [await _entrar(cliente, await _usuario(kilo), plataforma="android") for _ in range(2)]
    de_alfa = await _entrar(cliente, await _usuario(mundo.alfa.id), plataforma="android")
    r = await cliente.post(f"/api/tenants/{kilo}/cerrar-sesiones", headers=mundo.cabeceras_plataforma())
    assert r.status_code == 200 and r.json()["usuarios"] == 2
    for s in de_kilo:
        assert (await cliente.get("/api/auth/me", headers=_cab(s))).status_code == 401
    assert (await cliente.get("/api/auth/me", headers=_cab(de_alfa))).status_code == 200
