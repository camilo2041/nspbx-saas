"""Integración con el CRM de la empresa (docs/plan-contact-center.md §7, fase 6).

**Webhooks de salida.** Cuando pasa algo (una llamada contestada, una
disposición, un callback, un número a no llamar) se le avisa al sistema de la
empresa con un POST JSON firmado:

    X-NSPBX-Evento: llamada.disposicionada
    X-NSPBX-Entrega: 1234            (id único: sirve para no procesar dos veces)
    X-NSPBX-Firma: t=1727900000,v1=<hex>

    v1 = HMAC-SHA256(secreto, f"{t}.{cuerpo}")

El receptor recalcula la firma con su secreto, la compara en tiempo constante
y rechaza un `t` de más de 5 minutos (repetición).

- Outbox: la entrega se escribe en la MISMA transacción que el cambio que la
  origina. Si el cambio no se guarda, no se avisa; si se guarda, el aviso
  queda en cola aunque el proceso se caiga justo después.
- Reintentos con espera creciente (30 s, 2 min, 10 min, 30 min, 2 h) y
  después «fallida»; desde el panel se reintenta a mano.
- SSRF: la URL tiene que ser https y resolver solo a direcciones públicas
  (core/urls.py), y se vuelve a comprobar en cada envío. No se siguen
  redirecciones.

**URL del CRM en la consola.** Una plantilla por campaña con {variables} del
lead; al abrirla se agregan `nspbx_ts` y `nspbx_firma` (HMAC del resto de la
URL con el secreto de la campaña) para que el CRM sepa que el enlace lo armó
NSPBX y no alguien que cambió el número a mano.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode, urlsplit

import httpx
from sqlalchemy import select

from app.core import urls
from app.core.database import async_session, sesion_de_empresa
from app.models import EntregaWebhook, Webhook

logger = logging.getLogger(__name__)

EVENTOS = {
    "llamada.contestada": "Un cliente contestó y quedó con un agente",
    "llamada.disposicionada": "El agente eligió la disposición de la llamada",
    "callback.creado": "Se agendó volver a llamar",
    "lead.no_llamar": "Un número pasó a la lista de no llamar",
}
EVENTO_PRUEBA = "ping"
ESPERAS = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30), timedelta(hours=2))
MAX_INTENTOS = len(ESPERAS) + 1
TIMEOUT_S = 10.0
_LOTE = 50


def nuevo_secreto() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def firmar(secreto: str, cuerpo: str, t: int | None = None) -> str:
    t = int(time.time()) if t is None else t
    v1 = hmac.new(secreto.encode(), f"{t}.{cuerpo}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def verificar(secreto: str, cuerpo: str, cabecera: str, tolerancia_s: int = 300, ahora: int | None = None) -> bool:
    """Lo que hace el receptor (también sirve de referencia en la documentación)."""
    try:
        partes = dict(p.split("=", 1) for p in cabecera.split(","))
        t = int(partes["t"])
    except (ValueError, KeyError):
        return False
    if abs((ahora or int(time.time())) - t) > tolerancia_s:
        return False
    esperado = firmar(secreto, cuerpo, t).split("v1=", 1)[1]
    return hmac.compare_digest(esperado, partes.get("v1", ""))


def _json(datos) -> str:
    return json.dumps(datos, ensure_ascii=False, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v))


# Webhooks activos de cada empresa: (id, eventos). Se consultan en cada
# llamada contestada y cada disposición; con decenas por segundo, ir a la base
# cada vez se notaba (docs/escala.md). Vale CACHE_S y se invalida al cambiar
# un webhook, en esta réplica y, por el bus, en las demás.
CACHE_S = 5.0
_cache: dict[int, tuple[float, list[tuple[int, list]]]] = {}


def invalidar_cache(tenant_id: int | None = None, avisar: bool = True) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)
    if avisar:
        from app.services.bus import bus

        bus.emitir_pronto("webhooks", {"tenant": tenant_id})


async def _activos(session, tenant_id: int) -> list[tuple[int, list]]:
    guardado = _cache.get(tenant_id)
    if guardado and time.monotonic() - guardado[0] < CACHE_S:
        return guardado[1]
    filas = (
        await session.execute(select(Webhook.id, Webhook.eventos).where(Webhook.tenant_id == tenant_id, Webhook.activo.is_(True)))
    ).all()
    activos = [(i, list(e or [])) for i, e in filas]
    _cache[tenant_id] = (time.monotonic(), activos)
    return activos


async def emitir(session, tenant_id: int, evento: str, datos: dict) -> int:
    """Encola el evento para cada webhook activo suscrito. No hace red: la
    entrega va aparte. Devuelve cuántas entregas encoló."""
    if evento not in EVENTOS and evento != EVENTO_PRUEBA:
        raise ValueError(evento)
    ganchos = [(i, e) for i, e in await _activos(session, tenant_id) if evento == EVENTO_PRUEBA or evento in e]
    if not ganchos:
        return 0
    ahora = datetime.utcnow()
    cuerpo = _json({"evento": evento, "empresa_id": tenant_id, "creado": ahora.isoformat() + "Z", "datos": datos})
    for webhook_id, _ in ganchos:
        session.add(EntregaWebhook(tenant_id=tenant_id, webhook_id=webhook_id, evento=evento, payload=cuerpo, estado="pendiente",
                                   proximo_intento_at=ahora))
    return len(ganchos)


def _desde_otra_replica(datos) -> None:
    invalidar_cache((datos or {}).get("tenant"), avisar=False)


def _registrar_en_bus() -> None:
    from app.services.bus import bus

    bus.registrar("webhooks", _desde_otra_replica)


_registrar_en_bus()


async def emitir_seguro(session, tenant_id: int, evento: str, datos: dict) -> None:
    """Para los motores: un problema con los webhooks nunca tumba una llamada."""
    try:
        await emitir(session, tenant_id, evento, datos)
    except Exception:
        logger.exception("No se pudo encolar el webhook %s", evento)


# --- Entrega --------------------------------------------------------------------------------------


async def _enviar(url: str, secreto: str, evento: str, entrega_id: int, payload: str) -> tuple[bool, int | None, str | None]:
    try:
        url = await urls.exigir_destino_publico(url)
    except urls.UrlNoPermitida as exc:
        return False, None, f"URL no permitida: {exc}"
    cabeceras = {
        "Content-Type": "application/json",
        "User-Agent": "NSPBX-Webhooks/1",
        "X-NSPBX-Evento": evento,
        "X-NSPBX-Entrega": str(entrega_id),
        "X-NSPBX-Firma": firmar(secreto, payload),
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as cliente:
            r = await cliente.post(url, content=payload.encode(), headers=cabeceras)
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:500]
    if 200 <= r.status_code < 300:
        return True, r.status_code, None
    return False, r.status_code, f"Respondió {r.status_code}: {r.text[:300]}"


# Mientras se envía, la entrega queda «tomada» hasta esta hora: otro ciclo no
# la repite, y si el proceso muere a mitad, vuelve a la cola sola.
_TOMA = timedelta(seconds=TIMEOUT_S + 50)


async def entregar(tenant_id: int, entrega_id: int, forzar: bool = False) -> str | None:
    """Intenta una entrega. Devuelve su estado final, o None si no tocaba (otro
    la tomó, ya salió, o todavía no es su hora y no se pidió `forzar`).

    Tres pasos cortos, sin transacción abierta durante el POST: con 50
    receptores lentos eso serían 50 conexiones a la base esperando."""
    ahora = datetime.utcnow()
    async with sesion_de_empresa(tenant_id) as session:
        entrega = (
            await session.execute(select(EntregaWebhook).where(EntregaWebhook.id == entrega_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        if entrega is None or entrega.estado != "pendiente":
            return None
        if not forzar and entrega.proximo_intento_at and entrega.proximo_intento_at > ahora:
            return None
        webhook = await session.get(Webhook, entrega.webhook_id)
        if webhook is None or not webhook.activo:
            entrega.estado, entrega.ultimo_error = "fallida", "El webhook está desactivado"
            await session.commit()
            return entrega.estado
        entrega.proximo_intento_at = ahora + _TOMA
        url, secreto, evento, payload = webhook.url, webhook.secreto, entrega.evento, entrega.payload
        await session.commit()

    ok, codigo, error = await _enviar(url, secreto, evento, entrega_id, payload)

    ahora = datetime.utcnow()
    async with sesion_de_empresa(tenant_id) as session:
        entrega = await session.get(EntregaWebhook, entrega_id, with_for_update=True)
        webhook = await session.get(Webhook, entrega.webhook_id) if entrega else None
        if entrega is None:
            return None
        entrega.intentos += 1
        entrega.ultimo_codigo, entrega.ultimo_error = codigo, error
        if ok:
            entrega.estado, entrega.entregado_at, entrega.proximo_intento_at = "ok", ahora, None
            if webhook:
                webhook.fallos_seguidos, webhook.ultimo_ok_at = 0, ahora
        else:
            if webhook:
                webhook.fallos_seguidos += 1
            if entrega.intentos >= MAX_INTENTOS:
                entrega.estado, entrega.proximo_intento_at = "fallida", None
            else:
                entrega.proximo_intento_at = ahora + ESPERAS[entrega.intentos - 1]
        await session.commit()
        return entrega.estado


class Repartidor:
    def __init__(self):
        self._tarea: asyncio.Task | None = None

    def start(self) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle())

    async def stop(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self) -> None:
        while True:
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error repartiendo webhooks")
            await asyncio.sleep(2)

    async def ciclo(self) -> int:
        """Una vuelta: las entregas vencidas de todas las empresas, en paralelo
        (un receptor lento no frena a los demás). Devuelve cuántas intentó."""
        async with async_session() as dueno:
            pendientes = (
                await dueno.execute(
                    select(EntregaWebhook.tenant_id, EntregaWebhook.id)
                    .where(EntregaWebhook.estado == "pendiente", EntregaWebhook.proximo_intento_at <= datetime.utcnow())
                    .order_by(EntregaWebhook.id)
                    .limit(_LOTE)
                )
            ).all()
        paralelo = asyncio.Semaphore(10)

        async def uno(tenant_id: int, entrega_id: int) -> None:
            async with paralelo:
                try:
                    await entregar(tenant_id, entrega_id)
                except Exception:
                    logger.exception("Entrega de webhook %s", entrega_id)

        await asyncio.gather(*(uno(t, i) for t, i in pendientes))
        return len(pendientes)


repartidor = Repartidor()


# --- Payloads de los eventos ---------------------------------------------------------------------------


def datos_llamada(vivo, telefono: str | None = None, **extra) -> dict:
    return {
        "llamada_uuid": vivo.call_uuid,
        "campana_id": vivo.campaign_id,
        "lead_id": vivo.lead_id,
        "telefono": telefono or vivo.telefono,
        "agente_id": vivo.user_id,
        **extra,
    }


# --- URL del CRM -------------------------------------------------------------------------------------------


def url_crm(plantilla: str, secreto: str, variables: dict[str, str], t: int | None = None) -> str:
    """Rellena la plantilla (valores escapados para URL) y la firma. La firma
    cubre la URL completa sin los dos parámetros de firma."""
    def valor(clave: str) -> str:
        return quote(str(variables.get(clave, "") or ""), safe="")

    import re

    url = re.sub(r"\{(\w+)\}", lambda m: valor(m.group(1)), plantilla.strip())
    t = int(time.time()) if t is None else t
    separador = "&" if urlsplit(url).query else "?"
    base = f"{url}{separador}{urlencode({'nspbx_ts': t})}"
    firma = hmac.new(secreto.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"{base}&nspbx_firma={firma}"


def validar_plantilla_crm(plantilla: str) -> str:
    """https y sin usuario; el destino lo abre el NAVEGADOR del agente (no el
    servidor), así que puede ser un CRM interno de la empresa."""
    p = urlsplit((plantilla or "").strip())
    if p.scheme != "https" or not p.hostname:
        raise urls.UrlNoPermitida("La URL del CRM debe empezar con https://")
    if p.username or p.password:
        raise urls.UrlNoPermitida("La URL no debe llevar usuario ni contraseña")
    if "{" in (p.hostname or "") or "{" in p.netloc:
        raise urls.UrlNoPermitida("Las {variables} van en la ruta o en los parámetros, no en el servidor")
    return plantilla.strip()
