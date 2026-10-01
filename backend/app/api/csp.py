"""Avisos de la política de contenido (CSP) que mandan los navegadores.

La CSP completa del panel está en modo "solo reporte" (ver
frontend/next.config.ts): el navegador avisa qué bloquearía sin
bloquearlo. Antes esos avisos solo se veían en la consola de cada
navegador, así que nadie podía decidir con datos cuándo aplicarla. Ahora
llegan acá, se agrupan y la plataforma los ve en Empresas: cuando la lista
quede vacía (o solo con extensiones del navegador), se puede pasar a
aplicarla sin miedo a dejar el softphone mudo.

La ruta es abierta (el navegador no manda el token) y por eso: tope por
IP, cuerpo chico, solo se guarda el origen bloqueado (esquema + host, sin
ruta ni parámetros, que pueden traer datos) y un máximo de grupos.
"""

import json
import logging
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response

from app.core.limitador import LimiteIntentos, ip_cliente, limitar_uso

logger = logging.getLogger(__name__)

router = APIRouter(tags=["csp"])

_POR_IP = LimiteIntentos(maximo=60, ventana=60, bloqueo=60)
_MAX_CUERPO = 16 * 1024
_MAX_GRUPOS = 500
_grupos: dict[tuple[str, str, str], dict] = {}


def _origen(url: str | None) -> str:
    """Solo esquema y host: 'https://cdn.ejemplo.com'. Valores especiales
    ('inline', 'eval', 'data', 'blob') se dejan como vienen."""
    if not url:
        return "?"
    url = str(url)[:300]
    partes = urlsplit(url)
    if partes.scheme and partes.netloc:
        return f"{partes.scheme}://{partes.netloc}"
    return (partes.scheme or url).split(":")[0][:40]


def _pagina(url: str | None) -> str:
    return (urlsplit(str(url or ""))[2] or "/")[:120]


def _normalizar(cuerpo) -> list[tuple[str, str, str]]:
    """Acepta el formato viejo (report-uri) y el de la Reporting API."""
    salida = []
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("csp-report"), dict):
        r = cuerpo["csp-report"]
        directiva = r.get("effective-directive") or r.get("violated-directive") or "?"
        salida.append((str(directiva).split(" ")[0][:40], _origen(r.get("blocked-uri")), _pagina(r.get("document-uri"))))
    elif isinstance(cuerpo, list):
        for item in cuerpo[:20]:
            if isinstance(item, dict) and item.get("type") == "csp-violation" and isinstance(item.get("body"), dict):
                b = item["body"]
                salida.append((str(b.get("effectiveDirective") or "?")[:40], _origen(b.get("blockedURL")),
                               _pagina(b.get("documentURL"))))
    return salida


@router.post("/api/csp-report", status_code=204)
async def recibir(request: Request):
    limitar_uso(_POR_IP, ip_cliente(request))
    crudo = await request.body()
    if len(crudo) > _MAX_CUERPO:
        raise HTTPException(status_code=413, detail="Reporte demasiado grande")
    try:
        cuerpo = json.loads(crudo or b"null")
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    ahora = datetime.utcnow()
    for clave in _normalizar(cuerpo):
        grupo = _grupos.get(clave)
        if grupo is None:
            if len(_grupos) >= _MAX_GRUPOS:
                continue
            grupo = _grupos[clave] = {"veces": 0, "primera": ahora}
            logger.warning("CSP bloquearía %s desde %s en %s", *clave)
        grupo["veces"] += 1
        grupo["ultima"] = ahora
    return Response(status_code=204)


def resumen() -> list[dict]:
    filas = [
        {"directiva": d, "origen": o, "pagina": p, **g}
        for (d, o, p), g in _grupos.items()
    ]
    return sorted(filas, key=lambda f: -f["veces"])


def reiniciar() -> None:
    _grupos.clear()
