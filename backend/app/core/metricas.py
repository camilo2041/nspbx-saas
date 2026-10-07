"""Métricas para Prometheus (`GET /metrics`, solo con METRICS_TOKEN).

Contadores de las peticiones HTTP (por plantilla de ruta, no por URL: así
no explota la cantidad de series) y, al pedirlas, lo que dice el sistema en
ese momento: llamadas y canales, grupos de atención, webhooks pendientes,
respaldos. Formato de texto de Prometheus, sin dependencias.
"""

import time
from collections import defaultdict

_peticiones: dict[tuple[str, str, str], int] = defaultdict(int)
_duracion: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])


class MiddlewareMetricas:
    """ASGI puro: cuenta cada petición y su duración por método y ruta."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        inicio = time.perf_counter()
        codigo = {"v": 500}

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                codigo["v"] = mensaje.get("status", 500)
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        finally:
            ruta = getattr(scope.get("route"), "path", None) or "otra"
            metodo = scope.get("method", "?")
            _peticiones[(metodo, ruta, f"{codigo['v'] // 100}xx")] += 1
            d = _duracion[(metodo, ruta)]
            d[0] += time.perf_counter() - inicio
            d[1] += 1


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _linea(nombre: str, valor, **etiquetas) -> str:
    if etiquetas:
        e = ",".join(f'{k}="{_esc(v)}"' for k, v in etiquetas.items())
        return f"{nombre}{{{e}}} {valor}"
    return f"{nombre} {valor}"


def http() -> list[str]:
    salida = [
        "# HELP nspbx_http_peticiones_total Peticiones HTTP atendidas por esta réplica.",
        "# TYPE nspbx_http_peticiones_total counter",
    ]
    salida += [_linea("nspbx_http_peticiones_total", n, metodo=m, ruta=r, codigo=c) for (m, r, c), n in sorted(_peticiones.items())]
    salida += [
        "# HELP nspbx_http_segundos Tiempo de respuesta HTTP (suma y cantidad).",
        "# TYPE nspbx_http_segundos summary",
    ]
    for (m, r), (suma, n) in sorted(_duracion.items()):
        salida.append(_linea("nspbx_http_segundos_sum", round(suma, 6), metodo=m, ruta=r))
        salida.append(_linea("nspbx_http_segundos_count", n, metodo=m, ruta=r))
    return salida


async def sistema() -> list[str]:
    """Lo de ahora mismo. Cada parte es independiente: si una falla, las demás salen."""
    from sqlalchemy import func, select

    from app.core.database import async_session
    from app.models import EntregaWebhook, SystemSettings, Tenant
    from app.services import esl, operacion
    from app.services.lider import lider
    from app.services.vigia_colas import vigia

    salida = [_linea("nspbx_lider", 1 if lider.es_lider else 0)]
    try:
        async with async_session() as s:
            empresas = dict((await s.execute(select(Tenant.id, Tenant.slug))).all())
            pendientes = (
                await s.execute(select(func.count()).select_from(EntregaWebhook).where(EntregaWebhook.estado == "pendiente"))
            ).scalar_one()
            ultimo = (
                await s.execute(select(SystemSettings.last_backup_at, SystemSettings.last_backup_ok)
                                .order_by(SystemSettings.last_backup_at.desc().nulls_last()).limit(1))
            ).first()
        salida.append(_linea("nspbx_webhooks_pendientes", pendientes))
        if ultimo and ultimo[0]:
            salida.append(_linea("nspbx_respaldo_ultimo_timestamp", int(ultimo[0].timestamp())))
            salida.append(_linea("nspbx_respaldo_ultimo_ok", 1 if ultimo[1] else 0))
    except Exception:
        empresas = {}
        salida.append(_linea("nspbx_base_ok", 0))
    else:
        salida.append(_linea("nspbx_base_ok", 1))
    # Copia externa cifrada y simulacro de restauración (scripts del servidor).
    externa, sim = operacion.copia_externa(), operacion.simulacro()
    if externa["horas"] is not None:
        salida.append(_linea("nspbx_respaldo_externo_edad_horas", externa["horas"]))
    if sim["ok"] is not None:
        salida.append(_linea("nspbx_simulacro_ok", 1 if sim["ok"] else 0))
        salida.append(_linea("nspbx_simulacro_edad_dias", sim["dias"]))
    for tid, slug in sorted(empresas.items()):
        for g in vigia.foto(tid):
            salida.append(_linea("nspbx_grupo_esperando", g.get("esperando", 0), empresa=slug, grupo=g.get("nombre")))
            salida.append(_linea("nspbx_grupo_espera_max_segundos", g.get("espera_max_s", 0), empresa=slug, grupo=g.get("nombre")))
            salida.append(_linea("nspbx_grupo_agentes_libres", (g.get("agentes") or {}).get("libres", 0), empresa=slug, grupo=g.get("nombre")))
    try:
        canales = await esl.api("show channels count")
        n = int(next((p for p in canales.split() if p.isdigit()), "0"))
        salida.append(_linea("nspbx_canales", n))
        salida.append(_linea("nspbx_central_ok", 1))
    except Exception:
        salida.append(_linea("nspbx_central_ok", 0))
    return salida


async def texto() -> str:
    return "\n".join(http() + await sistema()) + "\n"
