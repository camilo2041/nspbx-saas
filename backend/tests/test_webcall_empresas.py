"""Burbuja de llamada web por empresa.

Antes el widget estaba fijo a la empresa 1: cualquier otra empresa que lo
activara veía la burbuja de la empresa 1 (o ninguna). Ahora el snippet
lleva `data-empresa="<slug>"` y la credencial temporal recuerda de qué
empresa es, así que el directorio le da el dominio y el contexto aislado
de esa empresa.
"""

import pytest
from sqlalchemy import delete, text, update

from app.core.database import async_session
from app.models import SesionWebcall, SystemSettings
from app.services import webcall

from .conftest import FS_SECRET


@pytest.fixture(autouse=True)
async def registro_limpio(mundo):
    async with async_session() as s:
        await s.execute(delete(SesionWebcall))
        await s.commit()


async def _activar(empresa, **kw):
    async with async_session() as s:
        await s.execute(
            update(SystemSettings)
            .where(SystemSettings.tenant_id == empresa.id)
            .values(webcall_enabled=True, webcall_queue_id=empresa.ids["queue"], webcall_button_text=f"Hablar con {empresa.marca}", **kw)
        )
        await s.commit()


async def test_cada_empresa_tiene_su_burbuja(cliente, mundo):
    await _activar(mundo.beta)
    r = await cliente.get("/api/webcall/config", params={"empresa": mundo.beta.slug})
    assert r.json()["enabled"] and r.json()["button_text"] == f"Hablar con {mundo.beta.marca}"
    # Alfa no la activó: su burbuja sigue apagada.
    r = await cliente.get("/api/webcall/config", params={"empresa": mundo.alfa.slug})
    assert r.json() == {"enabled": False}
    r = await cliente.get("/api/webcall/config", params={"empresa": "no-existe"})
    assert r.json() == {"enabled": False}


async def test_la_credencial_entra_al_contexto_de_su_empresa(cliente, mundo):
    await _activar(mundo.beta)
    r = await cliente.post("/api/webcall/session", params={"empresa": mundo.beta.slug}, json={})
    assert r.status_code == 200, r.text
    sesion = r.json()
    assert sesion["domain"] == mundo.beta.dominio
    r = await cliente.get("/fs/directory", params={"secret": FS_SECRET, "user": sesion["username"]})
    assert r.status_code == 200
    assert f'name="{mundo.beta.dominio}"' in r.text
    assert f'value="webcall_{mundo.beta.slug}"' in r.text
    # Sin activar, la otra empresa no entrega credenciales.
    r = await cliente.post("/api/webcall/session", params={"empresa": mundo.alfa.slug}, json={})
    assert r.status_code == 404


async def test_el_tope_de_llamadas_es_por_empresa(cliente, mundo):
    await _activar(mundo.beta, webcall_max_concurrent=1)
    await webcall.registry.create("10.0.0.9", mundo.alfa.id)  # una llamada de otra empresa
    r = await cliente.post("/api/webcall/session", params={"empresa": mundo.beta.slug}, json={})
    assert r.status_code == 200
    r = await cliente.post("/api/webcall/session", params={"empresa": mundo.beta.slug}, json={})
    assert r.status_code == 503


async def test_ajustes_dan_el_identificador_para_el_snippet(cliente, mundo):
    r = await cliente.get("/api/system/settings", headers=mundo.beta.cabeceras())
    assert r.status_code == 200, r.text
    assert r.json()["webcall_empresa"] == mundo.beta.slug


async def test_el_registro_se_comparte_entre_replicas(mundo):
    """Dos registros (dos réplicas del backend) ven las mismas sesiones: la
    que crea una la encuentra el directorio servido por la otra."""
    una, otra = webcall.WebcallRegistry(), webcall.WebcallRegistry()
    sesion = await una.create("10.1.1.1", mundo.alfa.id)
    vista = await otra.get(sesion.username)
    assert vista is not None and vista.password == sesion.password and vista.tenant_id == mundo.alfa.id
    assert await otra.active_count(mundo.alfa.id) == 1
    await otra.end(sesion.username)
    assert await una.get(sesion.username) is None
    assert await una.active_count(mundo.alfa.id) == 0
    # La clave no queda en claro en la base.
    async with async_session() as s:
        crudo = (await s.execute(text("SELECT password FROM webcall_sesiones WHERE username = :u"), {"u": sesion.username})).scalar_one()
    assert sesion.password not in crudo


async def test_expiracion_y_limite_por_ip(mundo, monkeypatch):
    reg = webcall.WebcallRegistry()
    ahora = [1_000_000.0]
    monkeypatch.setattr(webcall.time, "time", lambda: ahora[0])
    sin_usar = await reg.create("10.2.2.2", mundo.alfa.id)
    usada = await reg.create("10.2.2.2", mundo.alfa.id)
    assert await reg.get(usada.username) is not None  # FreeSWITCH la pidió: queda registrada
    ahora[0] += webcall._REGISTER_TTL + 1
    # La que nadie usó vence a los 2 minutos; la usada sigue.
    assert await reg.get(sin_usar.username) is None
    assert await reg.get(usada.username) is not None
    assert await reg.active_count(mundo.alfa.id) == 1
    for _ in range(webcall._RATE_MAX - 2):
        await reg.create("10.2.2.2", mundo.alfa.id)
    assert not await reg.rate_ok("10.2.2.2") and await reg.rate_ok("10.3.3.3")
    # Pasada la ventana, el barrido borra lo vencido y la IP vuelve a poder.
    ahora[0] += webcall._SESSION_MAX + 1
    await reg.sweep()
    assert await reg.rate_ok("10.2.2.2")
    async with async_session() as s:
        assert (await s.execute(text("SELECT count(*) FROM webcall_sesiones"))).scalar_one() == 0
