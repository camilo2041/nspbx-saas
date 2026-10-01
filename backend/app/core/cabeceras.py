"""Cabeceras de seguridad en las respuestas de la API.

La API devuelve JSON con datos personales (teléfonos, grabaciones,
deudas): no debe quedar en cachés intermedias ni del navegador, ni ser
interpretada como otro tipo de contenido, ni mostrarse dentro de un iframe.
Las del panel (CSP, HSTS) están en frontend/next.config.ts.
"""

_COMUNES = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]
_SIN_CACHE = (b"cache-control", b"no-store")


class MiddlewareCabeceras:
    """ASGI puro: agrega las cabeceras sin pisar las que ponga un endpoint
    (p. ej. el Content-Type de una grabación)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        es_api = scope.get("path", "").startswith("/api/")

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                existentes = {k.lower() for k, _ in mensaje.get("headers", [])}
                agregar = [h for h in _COMUNES if h[0] not in existentes]
                if es_api and _SIN_CACHE[0] not in existentes:
                    agregar.append(_SIN_CACHE)
                mensaje["headers"] = list(mensaje.get("headers", [])) + agregar
            await send(mensaje)

        await self.app(scope, receive, enviar)
