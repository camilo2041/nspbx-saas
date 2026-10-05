"""Todas las rutas de la aplicación, para las pruebas que las recorren
(aislamiento, rutas abiertas, auditoría, API v1).

Desde FastAPI 0.13x, `app.routes` ya no lista las rutas de los routers
incluidos: los envuelve en un objeto propio y las expande al despachar.
Recorrer `app.routes` devolvía UNA ruta en vez de ~170, y las pruebas que
atacan cada ruta seguían en verde sin atacar casi nada. Por eso hay un solo
lugar que las enumera (con la función pública de FastAPI) y una prueba que
falla si la enumeración se queda corta (test_rutas_abiertas.py).
"""

from fastapi.routing import APIRoute

from app.main import app

try:
    from fastapi.routing import iter_route_contexts
except ImportError:  # FastAPI anterior: app.routes ya trae las rutas expandidas
    iter_route_contexts = None


def rutas_api() -> list[tuple[str, frozenset[str]]]:
    """(ruta, métodos) de cada ruta HTTP de la API, con el prefijo completo."""
    salida = []
    if iter_route_contexts is not None:
        for ctx in iter_route_contexts(app.routes):
            if isinstance(ctx.original_route, APIRoute) and ctx.path.startswith("/api/"):
                salida.append((ctx.path, frozenset(ctx.methods or ())))
    else:
        for r in app.routes:
            if isinstance(r, APIRoute) and r.path.startswith("/api/"):
                salida.append((r.path, frozenset(r.methods)))
    return salida


# Piso de cordura: hoy son ~165. Si una actualización vuelve a esconder las
# rutas, la enumeración cae muy por debajo y test_rutas_abiertas lo dice.
MINIMO_DE_RUTAS = 120
