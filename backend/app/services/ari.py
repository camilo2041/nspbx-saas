"""Conector con Issabel (Asterisk REST Interface, ARI).

Issabel se convierte en el motor telefónico externo: NSPBX se conecta como
una aplicación STASIS de Asterisk. Cuando Issabel enruta una llamada a
nuestra app Stasis, recibimos el evento `StasisStart` por WebSocket y
controlamos la llamada por REST; el audio del canal viaja por el MISMO
WebSocket (media frames).

Asterisk ARI en resumen:
- REST en http://<host>:8088/ari (HTTP Basic con usuario/clave de ARI).
- Eventos + media en ws://<host>:8088/ari/events?api_key=user:pass&app=<app>.
- Origen de llamadas: POST /ari/channels {endpoint, app, variables, ...}.
- Control de canal: POST /ari/channels/{id}/answer, DELETE .../channels/{id},
  POST /ari/channels/{id}/play {media: ...} para reproducir audio.

El proveedor debe exponer ARI y habilitar una app Stasis (el nombre se
configura en Ajustes → Issabel). Mientras ARI esté vacío, NSPBX usa su
propio FreeSWITCH (ver app/services/esl.py) — el conector no se activa.
"""

import asyncio
import json
import logging
from urllib.parse import quote

import httpx
import websockets

logger = logging.getLogger(__name__)

# Cuántos segundos espera el WebSocket de Stasis entre mensajes antes de
# dar la conexión por muerta y reconectar.
_WS_KEEPALIVE = 60


class AriError(RuntimeError):
    pass


class AriClient:
    """Cliente mínimo de ARI: REST para controlar canales + WebSocket de
    eventos/media de Stasis. Una instancia por proceso (el conector)."""

    def __init__(self, base_url: str, user: str, password: str, app: str):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.app = app
        self._handlers: dict[str, list] = {}
        self._task: asyncio.Task | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None

    # ---------------- REST ----------------

    async def _rest(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}/ari{path}"
        auth = (self.user, self.password)
        async with httpx.AsyncClient(timeout=20, auth=auth) as client:
            resp = await client.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise AriError(f"ARI {method} {path}: {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else None

    async def originate(
        self,
        endpoint: str,
        variables: dict[str, str] | None = None,
        caller_id: str | None = None,
        timeout: int = 45,
    ) -> dict:
        """Origina una llamada desde Issabel y la entrega a nuestra app Stasis.

        `endpoint` es el canal de Asterisk, ej. "PJSIP/20060689/573182927165"
        (troncal/destino) o "Local/1000@from-internal" para un interno. La
        llamada, al contestar, entra a Stasis y la recibimos por WebSocket.
        """
        data = {
            "endpoint": endpoint,
            "app": self.app,
            "timeout": timeout,
            "channelId": f"nspbx-{asyncio.get_running_loop().time():.0f}",
        }
        if caller_id:
            data["callerId"] = caller_id
        if variables:
            data["variables"] = {f"NSPBX_{k.upper()}": v for k, v in variables.items()}
        return await self._rest("POST", "/channels", json=data)

    async def answer(self, channel_id: str) -> None:
        await self._rest("POST", f"/channels/{channel_id}/answer")

    async def play(self, channel_id: str, media: str, lang: str = "en") -> dict:
        """Reproduce audio en el canal. `media` acepta "sound:<nombre>"
        (sonidos de Asterisk) o "recording:<nombre>". Para audio dinámico
        (TTS) hay que servir el archivo y referenciarlo por URI — ver la
        nota al final del módulo."""
        return await self._rest(
            "POST",
            f"/channels/{channel_id}/play",
            json={"media": media, "lang": lang},
        )

    async def hangup(self, channel_id: str) -> None:
        try:
            await self._rest("DELETE", f"/channels/{channel_id}")
        except AriError:
            pass  # ya colgó

    async def channel(self, channel_id: str) -> dict | None:
        try:
            return await self._rest("GET", f"/channels/{channel_id}")
        except AriError:
            return None

    # ---------------- WebSocket (Stasis) ----------------

    def on(self, event_name: str, handler) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    def _ws_url(self) -> str:
        # mediaSupport=true: el WebSocket entrega, además de los eventos,
        # los frames de audio del canal (para el STT del bot).
        q = {
            "api_key": f"{self.user}:{self.password}",
            "app": self.app,
            "subscribeAll": "true",
            "mediaSupport": "true",
            "mediaEncode": "none",  # PCM raw; cambiar según la app Stasis
        }
        qs = "&".join(f"{k}={quote(str(v))}" for k, v in q.items())
        return f"{self.base_url.replace('http', 'ws', 1)}/ari/events?{qs}"

    async def _loop(self) -> None:
        while True:
            try:
                async with websockets.connect(self._ws_url(), ping_interval=None) as ws:
                    self._ws = ws
                    logger.info("ARI Stasis conectado a %s (app '%s')", self.base_url, self.app)
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=_WS_KEEPALIVE)
                        if isinstance(raw, bytes):
                            self._dispatch_media(raw)
                            continue
                        try:
                            event = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        self._dispatch(event)
            except asyncio.TimeoutError:
                logger.warning("ARI Stasis sin actividad; reconectando…")
            except Exception as exc:
                logger.warning("ARI Stasis desconectado (%s); reconectando en 5s", exc)
            self._ws = None
            await asyncio.sleep(5)

    def _dispatch(self, event: dict) -> None:
        name = event.get("type")
        for handler in self._handlers.get(name, []):
            try:
                handler(event)
            except Exception:
                logger.exception("Error en handler de ARI %s", name)

    def _dispatch_media(self, data: bytes) -> None:
        # Frames de audio del canal (formato según mediaEncode). El handler
        # de "media" decide qué hacer (STT streaming, etc.).
        for handler in self._handlers.get("media", []):
            try:
                handler(data)
            except Exception:
                logger.exception("Error en handler de media ARI")

    async def start(self) -> None:
        """Conecta el WebSocket de Stasis en segundo plano y reconecta solo."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None


# Nota sobre el audio SALIENTE (TTS) por ARI:
# `play` acepta sonidos de Asterisk o grabaciones ya en disco. Para que el
# bot suene frases sintetizadas al vuelo hay dos caminos:
#   1) Generar el WAV, hostearlo con un endpoint HTTP propio (p. ej.
#      /ari-audio/<archivo>) y pedirle a Asterisk que lo descargue — exige
#      configurar el módulo http de Asterisk para permitir esas URIs.
#   2) Usar el WebSocket de media en sentido inverso (enviar frames) —
#      soportado en versiones recientes de ARI vía media socket.
# El conector actual deja ambas puertas: `play` para lo que Issabel ya
# conozca, y el dispatch de media para el STT entrante.
