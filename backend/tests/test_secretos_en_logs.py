"""I7: ningún secreto llega a los logs.

El log de acceso de uvicorn escribía la URL completa, y por la URL viajan
secretos: FreeSWITCH pide /fs/dialplan?secret=FS_XML_SECRET en cada llamada
(con ese secreto /fs/directory entrega las claves SIP de todas las
empresas), el CDR va a /fs/cdr/<secreto>, el log en vivo abre
/ws/logs?token=<JWT> y el push usa /fs/push/<firma>/.
"""

import logging

import pytest

from app.core import auditoria
from app.core.auditoria import FiltroSecretos, ocultar_secretos_en_texto

from .conftest import FS_SECRET


def _registro_de_acceso(ruta: str) -> logging.LogRecord:
    """Como lo arma uvicorn.access: el mensaje con la ruta como argumento."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("172.18.0.5:41234", "GET", ruta, "1.1", 200), None
    )


@pytest.mark.parametrize(
    "ruta",
    [
        f"/fs/dialplan?secret={FS_SECRET}",
        f"/fs/directory?secret={FS_SECRET}&user=1000",
        f"/fs/cdr/{FS_SECRET}?uuid=abc",
        "/ws/logs?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjF9.firma-del-token&level=info",
        "/fs/push/" + "ab" * 32 + "/alfa/1000",
    ],
)
def test_el_log_de_acceso_no_lleva_secretos(ruta):
    r = _registro_de_acceso(ruta)
    FiltroSecretos().filter(r)
    linea = r.getMessage()
    assert FS_SECRET not in linea
    assert "firma-del-token" not in linea
    assert "ab" * 32 not in linea
    assert "***" in linea
    # Y el formateador real de uvicorn lo sigue pudiendo escribir (desarma
    # `args` como tupla: con args=None fallaba con «cannot unpack»).
    from uvicorn.logging import AccessFormatter

    salida = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(r)
    assert "GET" in salida and "200" in salida and "***" in salida
    assert FS_SECRET not in salida and "firma-del-token" not in salida


def test_el_filtro_esta_instalado_en_uvicorn():
    import app.main  # noqa: F401  (configura el logging)

    for nombre in ("uvicorn.access", "uvicorn.error"):
        assert any(isinstance(f, FiltroSecretos) for f in logging.getLogger(nombre).filters), nombre

    # El manejador que arma la app para todo lo demás también lo lleva.
    raiz = logging.getLogger()
    antes, nivel = raiz.handlers[:], raiz.level
    try:
        auditoria.configurar_logging()
        assert all(any(isinstance(f, FiltroSecretos) for f in m.filters) for m in raiz.handlers)
    finally:
        raiz.handlers[:] = antes
        raiz.setLevel(nivel)


def test_los_valores_de_las_claves_se_tapan_donde_aparezcan(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "clave-de-firma-muy-larga-de-prueba")  # gitleaks:allow
    texto = f"error conectando con secreto {FS_SECRET} y clave-de-firma-muy-larga-de-prueba"
    limpio = ocultar_secretos_en_texto(texto)
    assert FS_SECRET not in limpio and "clave-de-firma" not in limpio


def test_lo_normal_no_se_toca():
    linea = '172.18.0.5:41234 - "GET /api/calls?limit=30&search=3001234567 HTTP/1.1" 200'
    assert ocultar_secretos_en_texto(linea) == linea


async def test_las_peticiones_con_claves_no_las_dejan_en_el_log(cliente, mundo, caplog):
    """Un recorrido con contraseñas y claves de verdad: login, extensión con
    clave SIP, troncal con clave del proveedor, clave del modelo de IA y el
    dialplan pedido por FreeSWITCH. Nada de eso puede quedar en el log."""
    caplog.set_level(logging.DEBUG)
    clave_sip = "Sip-Clave-Larga-9x7Q2"  # gitleaks:allow
    clave_troncal = "Proveedor-Clave-5k8W3"  # gitleaks:allow
    clave_llm = "sk-prueba-0123456789abcdef"  # gitleaks:allow
    cab = mundo.alfa.cabeceras()

    await cliente.post("/api/auth/login", json={"username": "admin-alfa", "password": "clave-de-prueba"})
    await cliente.post("/api/auth/login", json={"username": "admin-alfa", "password": "clave-equivocada-123"})  # gitleaks:allow
    await cliente.post("/api/extensions", json={"number": "1777", "password": clave_sip}, headers=cab)
    await cliente.post(
        "/api/trunks",
        json={"name": "prueba_logs", "gateway_host": "sip.logs.test", "username": "u", "password": clave_troncal, "register_enabled": True},
        headers=cab,
    )
    await cliente.put("/api/system/settings", json={"ai_llm_api_key": clave_llm}, headers=cab)
    await cliente.get("/fs/dialplan", params={"secret": FS_SECRET})

    texto = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    for secreto in (clave_sip, clave_troncal, clave_llm, "clave-de-prueba", "clave-equivocada-123", FS_SECRET):
        assert secreto not in texto, f"«{secreto[:6]}…» quedó en el log"
    # Y la auditoría, que se guarda en la base, tampoco los tiene.
    assert auditoria.ocultar_secretos({"password": clave_sip})["password"] == "***"
