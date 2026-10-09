"""I6: un administrador de empresa no afecta a otras ni a la plataforma.

Con dos o más empresas, lo que es de toda la instalación (empresas,
licencias, diagnóstico, respaldos, consola de FreeSWITCH) queda solo para
el rol plataforma. Ver app/core/alcance.py.
"""

import pytest

from app.core import alcance, permissions
from app.core.database import app_session, fijar_tenant
from app.models import User

_GLOBALES = [
    ("GET", "/api/tenants", None),
    ("POST", "/api/tenants", {"name": "Intrusa", "slug": "intrusa"}),
    ("PUT", "/api/tenants/{beta}", {"enabled": False}),
    ("DELETE", "/api/tenants/{beta}", None),
    ("GET", "/api/tenants/{beta}/licencia", None),
    ("PUT", "/api/tenants/{beta}/licencia", {"status": "suspended"}),
    ("PUT", "/api/tenants/{alfa}/licencia", {"plan": "enterprise", "status": "active"}),
    ("GET", "/api/system/diagnostics", None),
    ("GET", "/api/system/maintenance", None),
    ("POST", "/api/system/maintenance/backup-now", None),
    ("GET", "/api/plataforma/salientes", None),
    ("PUT", "/api/plataforma/salientes", {"outbound_blocked": True}),
    ("GET", "/api/plataforma/destinos-bloqueados", None),
    ("POST", "/api/tenants/{beta}/cerrar-sesiones", None),
    ("PUT", "/api/plataforma/destinos-bloqueados", {"prefijos": ""}),
    ("PUT", "/api/tenants/{alfa}", {"outbound_blocked": False}),
]


@pytest.mark.parametrize("metodo,ruta,cuerpo", _GLOBALES, ids=[f"{m} {r}" for m, r, _ in _GLOBALES])
@pytest.mark.parametrize("rol", [permissions.ADMIN, permissions.SUPERVISOR, permissions.ASESOR])
async def test_administrador_de_empresa_no_toca_lo_global(cliente, mundo, metodo, ruta, cuerpo, rol):
    url = ruta.format(alfa=mundo.alfa.id, beta=mundo.beta.id)
    resp = await cliente.request(metodo, url, headers=mundo.alfa.cabeceras(rol), json=cuerpo)
    assert resp.status_code == 403, f"{rol} de alfa: {metodo} {url} respondió {resp.status_code}"


async def test_administrador_de_empresa_no_es_operador_global(mundo):
    """Decide también el acceso a la consola de FreeSWITCH (/ws/logs)."""
    async with app_session() as s:
        fijar_tenant(s, mundo.alfa.id)
        admin = await s.get(User, mundo.alfa.usuarios[permissions.ADMIN])
        assert not await alcance.es_operador_global(admin, s)


async def test_plataforma_si_es_operador_global(cliente, mundo):
    resp = await cliente.get("/api/tenants", headers=mundo.cabeceras_plataforma())
    assert resp.status_code == 200
    assert "beta" in resp.text and "alfa" in resp.text


_SOLO_ADMIN = [
    "/api/trunks",
    "/api/extensions",
    "/api/inbound-routes",
    "/api/outbound-routes",
    "/api/users",
    "/api/role-permissions",
    "/api/system/settings",
    "/api/security/bans",
    "/api/system/recursos",
]


@pytest.mark.parametrize("ruta", _SOLO_ADMIN)
@pytest.mark.parametrize("rol", [permissions.SUPERVISOR, permissions.ASESOR])
async def test_configuracion_sensible_solo_para_admin(cliente, mundo, ruta, rol):
    """Troncales, extensiones y ajustes traen credenciales en claro."""
    resp = await cliente.get(ruta, headers=mundo.alfa.cabeceras(rol))
    assert resp.status_code == 403, f"{rol}: GET {ruta} respondió {resp.status_code}"


async def test_asesor_solo_ve_sus_propias_llamadas(cliente, mundo):
    """La llamada sembrada es de la extensión 1000, que es la del asesor;
    otra llamada de la misma empresa a un número ajeno no le corresponde."""
    from datetime import datetime

    from app.core.database import async_session
    from app.models import CallLog

    async with async_session() as s:
        ajena = CallLog(
            tenant_id=mundo.alfa.id, uuid="uuid-alfa-ajena", caller_number="1999",
            callee_number="3110000000", direction="outbound", status="answered", started_at=datetime.utcnow(),
        )
        s.add(ajena)
        await s.commit()
        ajena_id = ajena.id

    resp = await cliente.get(f"/api/calls/{ajena_id}", headers=mundo.alfa.cabeceras(permissions.ASESOR))
    assert resp.status_code == 404
    listado = await cliente.get("/api/calls", headers=mundo.alfa.cabeceras(permissions.ASESOR))
    assert "3110000000" not in listado.text
