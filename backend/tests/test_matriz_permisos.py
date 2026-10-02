"""Matriz rol × ruta completa: para CADA ruta de la API y cada rol de
empresa, si al rol le falta el permiso que la ruta exige, el backend
responde 403. El permiso de cada ruta se lee de sus dependencias, así que
una ruta nueva entra sola a la prueba.

Además:
- toda ruta declara un permiso o está en _SIN_PERMISO con su motivo;
- docs/matriz-permisos.md es la tabla generada de esto mismo. Si cambia un
  permiso, la prueba falla hasta regenerarla:
      ACTUALIZAR_MATRIZ=1 python -m pytest tests/test_matriz_permisos.py
"""

import os
import re
from pathlib import Path

import pytest

from app.core import permissions
from app.core.database import async_session
from app.core.security import crear_token, hash_password
from app.models import User

from .matriz import ROLES_DE_EMPRESA, rutas_con_guardia

# Rutas sin permiso de rol, con el motivo. Cualquier otra que no declare uno falla.
_SIN_PERMISO = {
    "/api/auth/": "la propia cuenta: entrar, salir, contraseña, 2 pasos, sesiones, su extensión y su teléfono",
    "/api/appointments/agent/": "agente externo: se autentica con X-Agent-Secret, sin sesión de usuario",
    "/api/webcall/": "widget de llamada web: visitantes anónimos, Turnstile y límites",
    "/api/v1/": "API pública: la autentica una clave de API con sus propios permisos (test_api_v1.py)",
    "/api/assistant/chat": "asistente: solo consulta, y responde con los datos que el rol puede ver",
    "/api/csp-report": "avisos de CSP del navegador, sin sesión",
}

_RUTAS = rutas_con_guardia()
_DOC = Path(__file__).resolve().parents[2] / "docs" / "matriz-permisos.md"


def _sin_permiso_justificado(ruta: str) -> bool:
    return any(ruta.startswith(p) if p.endswith("/") else ruta == p for p in _SIN_PERMISO)


def test_toda_ruta_declara_su_permiso():
    sin = [f"{m} {r}" for m, r, g in _RUTAS if g.vacia() and not _sin_permiso_justificado(r)]
    assert not sin, (
        "Rutas sin permiso de rol: agrega requiere(...) o, si de verdad no lo necesitan, "
        f"anótalas en _SIN_PERMISO con el motivo: {sin}"
    )


def test_la_lectura_de_permisos_no_quedo_vacia():
    """Si una actualización de FastAPI cambia cómo se guardan las dependencias,
    la matriz quedaría vacía y todo pasaría sin probar nada."""
    con_permiso = [r for _, r, g in _RUTAS if not g.vacia()]
    assert len(con_permiso) >= 100, f"solo {len(con_permiso)} rutas con permiso detectado"


@pytest.fixture(scope="module")
async def cabeceras_por_rol(mundo):
    """Un usuario de alfa por rol (el coordinador no viene en el mundo)."""
    cab = {}
    async with async_session() as s:
        for rol in ROLES_DE_EMPRESA:
            uid = mundo.alfa.usuarios.get(rol)
            if uid is None:
                u = User(tenant_id=mundo.alfa.id, username=f"{rol}-matriz", full_name=f"{rol} matriz",
                         password_hash=hash_password("clave-de-prueba"), role=rol, enabled=True)
                s.add(u)
                await s.flush()
                uid = u.id
            cab[rol] = {"Authorization": f"Bearer {crear_token(uid, rol, mundo.alfa.id)[0]}"}
        await s.commit()
    return cab


_NEGADOS = [
    (rol, metodo, ruta)
    for metodo, ruta, g in _RUTAS
    for rol in ROLES_DE_EMPRESA
    if g.global_ or any(not permissions.puede(rol, p) for p in g.exige(metodo))
]


@pytest.mark.parametrize("rol,metodo,ruta", _NEGADOS, ids=[f"{r}:{m} {p}" for r, m, p in _NEGADOS])
async def test_sin_el_permiso_se_niega(cliente, mundo, cabeceras_por_rol, rol, metodo, ruta):
    url = re.sub(r"\{\w+\}", "999999", ruta)
    resp = await cliente.request(metodo, url, headers=cabeceras_por_rol[rol], json={} if metodo in ("POST", "PUT", "PATCH") else None)
    assert resp.status_code == 403, f"{rol}: {metodo} {ruta} respondió {resp.status_code} sin tener el permiso"


_LECTURAS_PERMITIDAS = [
    (rol, ruta)
    for metodo, ruta, g in _RUTAS
    for rol in ROLES_DE_EMPRESA
    if metodo == "GET" and "{" not in ruta and not g.vacia() and not g.global_
    and all(permissions.puede(rol, p) for p in g.exige("GET"))
]


@pytest.mark.parametrize("rol,ruta", _LECTURAS_PERMITIDAS, ids=[f"{r}:{p}" for r, p in _LECTURAS_PERMITIDAS])
async def test_con_el_permiso_se_entra(cliente, mundo, cabeceras_por_rol, rol, ruta):
    """Control positivo, solo con lecturas (no cambian nada): el 403 de la
    prueba anterior se debe al permiso y no a otra cosa."""
    resp = await cliente.get(ruta, headers=cabeceras_por_rol[rol])
    assert resp.status_code != 403, f"{rol}: GET {ruta} respondió 403 teniendo el permiso: {resp.text[:200]}"


# --- Documento ---------------------------------------------------------------

_ETIQUETA = {permissions.ADMIN: "Admin", permissions.SUPERVISOR: "Supervisor", permissions.COORDINADOR: "Coordinador", permissions.ASESOR: "Asesor"}


def _documento() -> str:
    lineas = [
        "# Matriz de permisos (rol × ruta)",
        "",
        "Generada de las dependencias de cada ruta por `backend/tests/test_matriz_permisos.py`, que",
        "además prueba cada celda ✗ contra el backend (403). No se edita a mano: después de cambiar",
        "un permiso, `ACTUALIZAR_MATRIZ=1 python -m pytest tests/test_matriz_permisos.py`.",
        "",
        "Son los permisos por omisión de cada rol; cada empresa puede ajustarlos en Roles y permisos.",
        "«global» = solo con una empresa en la instalación (si hay varias, solo la plataforma).",
        "",
        "| Método | Ruta | Permiso | " + " | ".join(_ETIQUETA[r] for r in ROLES_DE_EMPRESA) + " |",
        "|---|---|---|" + "---|" * len(ROLES_DE_EMPRESA),
    ]
    for metodo, ruta, g in _RUTAS:
        if g.vacia():
            permiso = "sesión (" + next(v for k, v in _SIN_PERMISO.items() if (ruta.startswith(k) if k.endswith("/") else ruta == k)).split(":")[0] + ")" if _sin_permiso_justificado(ruta) else "—"
            celdas = ["✓"] * len(ROLES_DE_EMPRESA)
        else:
            exigidos = sorted(g.exige(metodo))
            permiso = ", ".join(f"`{p}`" for p in exigidos) + (" · global" if g.global_ else "")
            celdas = ["✗" if g.global_ or any(not permissions.puede(r, p) for p in exigidos) else "✓" for r in ROLES_DE_EMPRESA]
        lineas.append(f"| {metodo} | `{ruta}` | {permiso} | " + " | ".join(celdas) + " |")
    return "\n".join(lineas) + "\n"


def test_el_documento_esta_al_dia():
    texto = _documento()
    if os.getenv("ACTUALIZAR_MATRIZ"):
        _DOC.write_text(texto, encoding="utf-8")
    actual = _DOC.read_text(encoding="utf-8") if _DOC.exists() else ""
    assert actual == texto, "docs/matriz-permisos.md no coincide con los permisos del código: regenerarla (ver arriba)"
