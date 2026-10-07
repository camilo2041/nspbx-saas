"""Fase I: aviso de buzón en iPhone, desbloqueo de IP y guías en la app."""

import pytest
from sqlalchemy import delete, func, select

from app.core import permissions
from app.core.database import async_session, fijar_tenant
from app.models import DeviceToken, Extension, MensajeBuzon
from app.schemas.schemas import DeviceTokenIn
from app.services import push

# --- I2: aviso de mensaje de voz en iPhone --------------------------------------------------


def test_el_token_de_avisos_va_con_su_plataforma():
    DeviceTokenIn(platform="ios-avisos", token_type="APNS", token="abc")
    for plataforma, tipo in (("ios", "APNS"), ("ios-avisos", "APNS_VOIP"), ("android", "APNS")):
        with pytest.raises(ValueError):
            DeviceTokenIn(platform=plataforma, token_type=tipo, token="abc")


@pytest.fixture
async def iphone(mundo):
    """El asesor (extensión 1000) con un iPhone: token de llamadas y de avisos."""
    usuario = mundo.alfa.usuarios[permissions.ASESOR]
    async with async_session() as s:
        fijar_tenant(s, mundo.alfa.id)
        ext_id = (await s.execute(select(Extension.id).where(Extension.tenant_id == mundo.alfa.id, Extension.number == "1000"))).scalar_one()
        s.add_all([
            DeviceToken(tenant_id=mundo.alfa.id, user_id=usuario, extension_id=ext_id, platform="ios",
                        token_type="APNS_VOIP", token="voip-i"),
            DeviceToken(tenant_id=mundo.alfa.id, user_id=usuario, extension_id=ext_id, platform="ios-avisos",
                        token_type="APNS", token="avisos-i"),
        ])
        await s.commit()
    yield usuario
    async with async_session() as s:
        await s.execute(delete(DeviceToken).where(DeviceToken.token.in_(["voip-i", "avisos-i"])))
        await s.commit()


async def test_el_buzon_avisa_al_iphone_con_la_insignia(mundo, monkeypatch, iphone):
    enviados = []

    async def aviso_ios(token, titulo, cuerpo, datos=None, insignia=None):
        enviados.append((token, titulo, insignia))

    monkeypatch.setattr(push, "enviar_aviso_ios", aviso_ios)
    async with async_session() as s:
        fijar_tenant(s, mundo.alfa.id)
        antes = (await s.execute(select(func.count()).select_from(MensajeBuzon).where(
            MensajeBuzon.tenant_id == mundo.alfa.id, MensajeBuzon.extension == "1000", MensajeBuzon.escuchado.is_(False),
        ))).scalar_one()
        ms = [MensajeBuzon(tenant_id=mundo.alfa.id, extension="1000", caller_name="Ana", ruta="/r/x.wav", duracion=4)
              for _ in range(2)]
        s.add_all(ms)
        await s.commit()
        try:
            assert await push.avisar_mensaje_buzon(s, mundo.alfa.id, ms[1]) == 1
        finally:
            await s.execute(delete(MensajeBuzon).where(MensajeBuzon.id.in_([m.id for m in ms])))
            await s.commit()
    # Solo el token de avisos, con los sin escuchar en el ícono (los dos nuevos y los que ya había).
    assert enviados == [("avisos-i", "Mensaje de voz de Ana", antes + 2)]


async def test_las_llamadas_no_usan_el_token_de_avisos(mundo, monkeypatch, iphone):
    voip = []

    async def enviar_voip(token, evento):
        voip.append(token)

    monkeypatch.setattr(push, "enviar_voip_ios", enviar_voip)
    async with async_session() as s:
        fijar_tenant(s, mundo.alfa.id)
        n = await push.avisar_llamada(s, mundo.alfa.id, "alfa", "1000", "uuid-i2", "3001112222", "Ana")
    assert n == 1 and voip == ["voip-i"]


async def test_cerrar_sesion_en_el_iphone_borra_los_dos_tokens(cliente, mundo, iphone):
    cab = mundo.alfa.cabeceras(permissions.ASESOR)
    assert (await cliente.delete("/api/auth/dispositivo/ios", headers=cab)).status_code == 204
    async with async_session() as s:
        quedan = (await s.execute(select(DeviceToken.token).where(DeviceToken.token.in_(["voip-i", "avisos-i"])))).all()
    assert quedan == []


async def test_registrar_el_token_de_avisos(cliente, mundo):
    cab = mundo.alfa.cabeceras(permissions.ASESOR)
    try:
        r = await cliente.post("/api/auth/dispositivo", headers=cab,
                               json={"platform": "ios-avisos", "token_type": "APNS", "token": "avisos-reg"})
        assert r.status_code == 204
        malo = await cliente.post("/api/auth/dispositivo", headers=cab,
                                  json={"platform": "ios", "token_type": "APNS", "token": "x"})
        assert malo.status_code == 422
    finally:
        async with async_session() as s:
            await s.execute(delete(DeviceToken).where(DeviceToken.token == "avisos-reg"))
            await s.commit()
