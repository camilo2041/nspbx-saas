"""Burbuja de llamada web por empresa.

Antes el widget estaba fijo a la empresa 1: cualquier otra empresa que lo
activara veía la burbuja de la empresa 1 (o ninguna). Ahora el snippet
lleva `data-empresa="<slug>"` y la credencial temporal recuerda de qué
empresa es, así que el directorio le da el dominio y el contexto aislado
de esa empresa.
"""

import pytest
from sqlalchemy import update

from app.core.database import async_session
from app.models import SystemSettings
from app.services import webcall

from .conftest import FS_SECRET


@pytest.fixture(autouse=True)
def registro_limpio(monkeypatch):
    monkeypatch.setattr(webcall, "registry", webcall.WebcallRegistry())


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
