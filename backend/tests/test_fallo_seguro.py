"""I8: ante la duda, se niega.

Tokens rotos, vencidos, firmados con otra clave, con una empresa que no
corresponde al usuario; usuarios y empresas desactivados; sesiones
cerradas; licencia suspendida. Todos tienen que terminar en 401/402/403,
nunca en acceso.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import update

from app.core import permissions
from app.core.database import async_session
from app.core.security import ALGORITMO, crear_token, hash_password
from app.models import License, Tenant, User

_RUTA = "/api/extensions"


def _firmar(datos: dict, clave: str = "x" * 48, algoritmo: str = ALGORITMO) -> str:
    return jwt.encode(datos, clave, algorithm=algoritmo)


def _datos(mundo, **cambios) -> dict:
    base = {
        "sub": str(mundo.alfa.usuarios[permissions.ADMIN]),
        "rol": permissions.ADMIN,
        "tid": mundo.alfa.id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    base.update(cambios)
    return base


async def test_control_positivo_token_bien_formado_entra(cliente, mundo):
    resp = await cliente.get(_RUTA, headers={"Authorization": f"Bearer {_firmar(_datos(mundo))}"})
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "cabecera",
    ["", "Bearer", "Bearer ", "Bearer basura", "Basic YWRtaW46YWRtaW4=", "bearer x.y.z"],
)
async def test_cabeceras_invalidas(cliente, mundo, cabecera):
    resp = await cliente.get(_RUTA, headers={"Authorization": cabecera} if cabecera else {})
    assert resp.status_code == 401


async def test_token_firmado_con_otra_clave(cliente, mundo):
    token = _firmar(_datos(mundo), clave="y" * 48)
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_sin_firma(cliente, mundo):
    token = jwt.encode(_datos(mundo), key=None, algorithm="none")
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_vencido(cliente, mundo):
    token = _firmar(_datos(mundo, exp=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


@pytest.mark.parametrize("sub", ["", "abc", "999999", None])
async def test_token_con_usuario_invalido_o_inexistente(cliente, mundo, sub):
    token = _firmar(_datos(mundo, sub=sub))
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_de_un_usuario_con_la_empresa_de_otro(cliente, mundo):
    """Usuario de beta con `tid` de alfa: aunque la firma fuera válida
    (clave filtrada, error al emitir), RLS no encuentra al usuario en alfa."""
    token = _firmar(_datos(mundo, sub=str(mundo.beta.usuarios[permissions.ADMIN]), tid=mundo.alfa.id))
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_con_empresa_inexistente(cliente, mundo):
    token = _firmar(_datos(mundo, tid=999999))
    assert (await cliente.get(_RUTA, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_de_plataforma_no_ve_datos_de_empresas(cliente, mundo):
    """Sin empresa, RLS no devuelve filas de ninguna: el rol plataforma
    administra empresas, no opera dentro de ellas."""
    resp = await cliente.get("/api/calls", headers=mundo.cabeceras_plataforma())
    assert mundo.alfa.marca not in resp.text and mundo.beta.marca not in resp.text
    assert mundo.alfa.telefono not in resp.text and mundo.beta.telefono not in resp.text


async def _usuario_temporal(tenant_id: int, nombre: str, rol: str = permissions.ADMIN) -> int:
    async with async_session() as s:
        u = User(
            tenant_id=tenant_id, username=nombre, full_name=nombre,
            password_hash=hash_password("clave-de-prueba"), role=rol, enabled=True,
        )
        s.add(u)
        await s.commit()
        return u.id


async def test_usuario_desactivado_pierde_el_acceso_al_instante(cliente, mundo):
    uid = await _usuario_temporal(mundo.alfa.id, "temporal-desactivado")
    cab = {"Authorization": f"Bearer {crear_token(uid, permissions.ADMIN, mundo.alfa.id)[0]}"}
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 200
    async with async_session() as s:
        await s.execute(update(User).where(User.id == uid).values(enabled=False))
        await s.commit()
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 401


async def test_rol_rebajado_pierde_permisos_al_instante(cliente, mundo):
    """El rol se relee de la base en cada petición, no se confía en el del token."""
    uid = await _usuario_temporal(mundo.alfa.id, "temporal-rebajado")
    cab = {"Authorization": f"Bearer {crear_token(uid, permissions.ADMIN, mundo.alfa.id)[0]}"}
    assert (await cliente.get("/api/trunks", headers=cab)).status_code == 200
    async with async_session() as s:
        await s.execute(update(User).where(User.id == uid).values(role=permissions.ASESOR))
        await s.commit()
    assert (await cliente.get("/api/trunks", headers=cab)).status_code == 403


async def test_sesiones_cerradas_invalidan_tokens_anteriores(cliente, mundo):
    uid = await _usuario_temporal(mundo.alfa.id, "temporal-sesiones")
    viejo = _firmar(_datos(mundo, sub=str(uid), iat=int(datetime.now(timezone.utc).timestamp()) - 60))
    cab = {"Authorization": f"Bearer {viejo}"}
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 200
    async with async_session() as s:
        await s.execute(update(User).where(User.id == uid).values(sesiones_desde=datetime.utcnow()))
        await s.commit()
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 401


@pytest.fixture(scope="module")
async def gamma(mundo):
    """Una tercera empresa para desactivarla y suspenderla sin afectar a las otras."""
    async with async_session() as s:
        t = Tenant(name="Gamma", slug="gamma", sip_domain="gamma.pbx.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        u = User(
            tenant_id=t.id, username="admin-gamma", full_name="admin gamma",
            password_hash=hash_password("clave-de-prueba"), role=permissions.ADMIN, enabled=True,
        )
        s.add(u)
        await s.commit()
        return t.id, u.id


async def test_licencia_suspendida_deja_ver_pero_no_operar(cliente, mundo, gamma):
    tid, uid = gamma
    cab = {"Authorization": f"Bearer {crear_token(uid, permissions.ADMIN, tid)[0]}"}
    async with async_session() as s:
        await s.execute(update(License).where(License.tenant_id == tid).values(status="suspended"))
        await s.commit()
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 200
    crear = await cliente.post(_RUTA, headers=cab, json={"number": "2000", "password": "Clave-Larga-123456"})
    assert crear.status_code == 402


async def test_empresa_desactivada_corta_a_todos_sus_usuarios(cliente, mundo, gamma):
    tid, uid = gamma
    cab = {"Authorization": f"Bearer {crear_token(uid, permissions.ADMIN, tid)[0]}"}
    async with async_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == tid).values(enabled=False))
        await s.commit()
    assert (await cliente.get(_RUTA, headers=cab)).status_code == 403


async def test_empresa_desactivada_deja_de_estar_en_freeswitch(cliente, mundo, gamma):
    from .conftest import FS_SECRET

    async with async_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == gamma[0]).values(enabled=False))
        await s.commit()
    resp = await cliente.get("/fs/directory", params={"secret": FS_SECRET})
    assert "gamma.pbx.test" not in resp.text
