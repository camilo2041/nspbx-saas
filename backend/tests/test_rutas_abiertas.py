"""I8: toda ruta de la API exige sesión, salvo una lista corta y explícita.

Se recorren TODAS las rutas registradas y se llaman sin token. Una ruta
nueva que nazca abierta —por un router montado fuera de la app o por un
cambio en la lista de exclusión— rompe esta prueba.

La lista de abajo repite a propósito la de app/core/auth.py: abrir una
ruta tiene que exigir tocar dos lugares, y el segundo es una prueba que
alguien revisa.
"""

import re

import pytest
from .rutas import MINIMO_DE_RUTAS, rutas_api

_ABIERTAS = {
    # Se autentican con el cuerpo o son el punto de entrada.
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
    # Segundo paso del login: se autentica con el token del paso intermedio.
    "/api/auth/mfa/verificar",
    # Avisos de CSP del navegador: sin token, tope por IP (app/api/csp.py).
    "/api/csp-report",
    # Wallboard sin usuario: token de solo lectura propio (test_supervision.py).
    "/api/wallboard",
    # Instalaciones locales: código de activación o token propio (test_instalaciones.py).
    "/api/licencia/activar",
    "/api/licencia/latido",
}
_ABIERTAS_PREFIJO = (
    # Agente de IA: secreto compartido en cabecera (X-Agent-Secret).
    "/api/appointments/agent/",
    # Widget de llamada web para visitantes anónimos: Turnstile + límites.
    "/api/webcall/",
)


def _todas():
    for ruta, metodos in rutas_api():
        for metodo in sorted(metodos - {"HEAD", "OPTIONS"}):
            yield metodo, ruta


_RUTAS = sorted(set(_todas()))


def _abierta(ruta: str) -> bool:
    return ruta in _ABIERTAS or ruta.startswith(_ABIERTAS_PREFIJO)


@pytest.mark.parametrize("metodo,ruta", [r for r in _RUTAS if not _abierta(r[1])], ids=lambda v: str(v))
async def test_sin_token_no_se_entra(cliente, mundo, metodo, ruta):
    url = re.sub(r"\{\w+\}", "1", ruta)
    resp = await cliente.request(metodo, url)
    assert resp.status_code == 401, f"{metodo} {ruta} sin token respondió {resp.status_code}"


def test_las_rutas_abiertas_existen():
    """Si una ruta abierta se renombra, la lista queda apuntando a nada y
    la nueva nace... protegida, que está bien; pero conviene enterarse."""
    rutas = {ruta for _, ruta in _RUTAS}
    for abierta in _ABIERTAS:
        assert abierta in rutas, f"{abierta} ya no existe"
    for prefijo in _ABIERTAS_PREFIJO:
        assert any(r.startswith(prefijo) for r in rutas), f"ninguna ruta empieza con {prefijo}"


async def test_agente_de_ia_sin_secreto_no_entra(cliente, mundo):
    resp = await cliente.get("/api/appointments/agent/availability", params={"date": "2030-01-01"})
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize("token", [None, "", "basura", "a.b.c"])
async def test_websocket_de_logs_sin_token_valido_no_identifica_a_nadie(mundo, token):
    """/ws/logs se autentica por su cuenta (un WebSocket de navegador no
    manda cabeceras): sin un token válido no hay usuario y se cierra."""
    from app.api.logs_ws import _usuario_del_token
    from app.core.database import app_session

    async with app_session() as session:
        assert await _usuario_del_token(token, session) is None


def test_la_enumeracion_de_rutas_no_queda_vacia():
    """Las pruebas de aislamiento, rutas abiertas y auditoría atacan cada
    ruta que encuentran: si la enumeración se queda corta (pasó al
    actualizar FastAPI: veía 1 ruta en vez de ~165) siguen en verde sin
    probar nada. Esto lo impide."""
    assert len(rutas_api()) >= MINIMO_DE_RUTAS, f"solo se encontraron {len(rutas_api())} rutas"
