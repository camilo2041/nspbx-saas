import asyncio
import logging
import re
from urllib.parse import quote

from app.core import validacion
from app.core.runtime_settings import runtime_settings

logger = logging.getLogger(__name__)


class ESLClient:
    """Cliente ESL minimalista (protocolo de FreeSWITCH) sobre asyncio."""

    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self.connected = False

    async def connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=5
        )
        await self._read_headers()  # greeting
        await self._send(f"auth {self.password}")
        headers = await self._read_headers()
        if "+OK accepted" not in headers.get("reply-text", ""):
            raise PermissionError(f"ESL auth rechazada: {headers}")
        self.connected = True

    async def close(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self.connected = False

    async def _send(self, data: str):
        # Un salto de línea dentro de un comando ES otro comando: el
        # protocolo ESL termina cada uno con una línea en blanco, así que
        # "originate ...<salto><salto>api system <cmd>" ejecuta <cmd> en el
        # servidor de FreeSWITCH. Ningún comando legítimo lleva saltos, de
        # modo que se rechazan todos acá, sin importar quién armó el texto:
        # es la barrera final si alguna validación de entrada falla.
        if "\n" in data or "\r" in data or "\x00" in data:
            raise ValueError("Comando ESL con caracteres de control")
        self._writer.write(data.encode() + b"\n\n")
        await self._writer.drain()

    async def _read_headers(self) -> dict:
        raw = await self._reader.readline()
        headers: dict = {}
        while raw and raw.strip():
            line = raw.decode().rstrip("\r\n")
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()
            raw = await self._reader.readline()
        return headers

    async def _read_body(self, headers: dict) -> str:
        length = int(headers.get("content-length", 0) or 0)
        if length <= 0:
            return ""
        body = await self._reader.readexactly(length)
        return body.decode(errors="replace")

    async def api(self, command: str) -> str:
        async with self._lock:
            try:
                await self._send(f"api {command}")
                headers = await self._read_headers()
            except (ConnectionError, OSError) as exc:
                # El socket murió (p.ej. FreeSWITCH se reinició) — se marca
                # muerto para que get_client() reconecte en la próxima
                # llamada, en vez de seguir usando esta conexión rota
                # indefinidamente (antes se quedaba "conectada" para
                # siempre, devolviendo errores vacíos sin nunca recuperarse
                # sola).
                self.connected = False
                raise RuntimeError(f"Conexión ESL perdida: {exc}") from exc
            if not headers:
                # readline() devolvió vacío = EOF = el otro lado cerró la
                # conexión sin avisar (mismo síntoma que arriba).
                self.connected = False
                raise RuntimeError("Conexión ESL cerrada por FreeSWITCH (EOF)")
            body = await self._read_body(headers)
            reply = headers.get("reply-text", "")
            if reply and not reply.startswith("+OK"):
                raise RuntimeError(f"ESL api error ({reply}): {body}")
            return body or reply.replace("+OK ", "")

    async def bgapi(self, command: str) -> str:
        async with self._lock:
            try:
                await self._send(f"bgapi {command}")
                headers = await self._read_headers()
            except (ConnectionError, OSError) as exc:
                self.connected = False
                raise RuntimeError(f"Conexión ESL perdida: {exc}") from exc
            if not headers:
                self.connected = False
                raise RuntimeError("Conexión ESL cerrada por FreeSWITCH (EOF)")
            body = await self._read_body(headers)
            reply = headers.get("reply-text", "")
            if not reply.startswith("+OK"):
                raise RuntimeError(f"ESL bgapi error: {reply} {body}")
            return reply.replace("+OK ", "").strip()


_client: ESLClient | None = None

_event_reader: asyncio.StreamReader | None = None
_event_writer: asyncio.StreamWriter | None = None
_pending_jobs: dict[str, "asyncio.Future[str]"] = {}
_event_listener_lock = asyncio.Lock()


async def _read_headers_raw(reader: asyncio.StreamReader) -> dict:
    headers: dict = {}
    raw = await reader.readline()
    while raw and raw.strip():
        line = raw.decode().rstrip("\r\n")
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        raw = await reader.readline()
    return headers


async def _read_body_raw(reader: asyncio.StreamReader, headers: dict) -> str:
    length = int(headers.get("content-length", 0) or 0)
    if length <= 0:
        return ""
    body = await reader.readexactly(length)
    return body.decode(errors="replace")


async def _ensure_event_listener():
    """Conexión ESL dedicada, suscrita a BACKGROUND_JOB, para conocer el
    resultado real (contestada/ocupado/no contesta/colgada) de cada
    `originate` lanzado en background — bgapi por sí solo solo confirma que
    FreeSWITCH aceptó la orden, no el desenlace de la llamada."""
    global _event_reader, _event_writer
    async with _event_listener_lock:
        if _event_writer is not None and not _event_writer.is_closing():
            return
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(runtime_settings.fs_esl_host, runtime_settings.fs_esl_port), timeout=5
        )
        await _read_headers_raw(reader)  # greeting
        writer.write(f"auth {runtime_settings.fs_esl_password}\n\n".encode())
        await writer.drain()
        auth_headers = await _read_headers_raw(reader)
        if "+OK accepted" not in auth_headers.get("reply-text", ""):
            raise PermissionError("ESL auth rechazada (event listener)")
        writer.write(b"event plain BACKGROUND_JOB\n\n")
        await writer.drain()
        await _read_headers_raw(reader)  # command/reply del "event"
        _event_reader, _event_writer = reader, writer
        asyncio.create_task(_event_loop(reader))


async def _event_loop(reader: asyncio.StreamReader):
    global _event_writer
    try:
        while True:
            headers = await _read_headers_raw(reader)
            if not headers:
                break
            body = await _read_body_raw(reader, headers)
            if headers.get("content-type") != "text/event-plain":
                continue
            event_headers, _, result = body.partition("\n\n")
            job_uuid = None
            for line in event_headers.split("\n"):
                if line.lower().startswith("job-uuid:"):
                    job_uuid = line.partition(":")[2].strip()
                    break
            if job_uuid and job_uuid in _pending_jobs:
                fut = _pending_jobs.pop(job_uuid)
                if not fut.done():
                    fut.set_result(result.strip())
    except Exception:
        logger.exception("Event listener de ESL caído")
    finally:
        if _event_writer:
            _event_writer.close()
        _event_writer = None


async def bgapi_wait(command: str, timeout: int = 40) -> str:
    """Como bgapi, pero espera el evento BACKGROUND_JOB y devuelve/lanza el
    resultado real del comando (p.ej. la llamada fue contestada, colgada,
    ocupada, sin respuesta, etc.), en vez de solo confirmar que se encoló."""
    await _ensure_event_listener()
    client = await get_client()
    reply = await client.bgapi(command)
    m = re.search(r"Job-UUID:\s*(\S+)", reply)
    if not m:
        raise RuntimeError(f"No se obtuvo Job-UUID: {reply}")
    job_uuid = m.group(1)
    fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    _pending_jobs[job_uuid] = fut
    try:
        result = await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        _pending_jobs.pop(job_uuid, None)
        raise RuntimeError("Timeout esperando el resultado de la llamada")
    if result.startswith("-ERR"):
        raise RuntimeError(result)
    return result


_client_lock = asyncio.Lock()


async def get_client() -> ESLClient:
    global _client
    # Sin lock, dos corrutinas concurrentes podían ver `_client is None` a
    # la vez y abrir dos conexiones — la primera quedaba huérfana (nunca
    # cerrada) y cualquier callback pendiente en ella se perdía.
    async with _client_lock:
        if _client is None or not _client.connected:
            if _client:
                await _client.close()
            _client = ESLClient(
                runtime_settings.fs_esl_host,
                runtime_settings.fs_esl_port,
                runtime_settings.fs_esl_password,
            )
            await _client.connect()
        return _client


async def invalidate_client():
    """Fuerza una reconexión (con los parámetros vigentes) en la próxima llamada."""
    global _client, _event_writer, _event_reader
    if _client:
        await _client.close()
    _client = None
    if _event_writer:
        _event_writer.close()
    _event_writer = None
    _event_reader = None


async def api(command: str) -> str:
    client = await get_client()
    return await client.api(command)


async def status() -> dict:
    body = await api("status")
    out: dict = {}
    m = re.search(r"FreeSWITCH \(Version (.+?)\) is ready", body)
    if m:
        out["version"] = m.group(1)
    m = re.search(r"(\d+) session\(s\) since startup", body)
    if m:
        out["sessions_since_startup"] = int(m.group(1))
    m = re.search(r"(\d+) session\(s\) - peak (\d+)", body)
    if m:
        out["current_sessions"] = int(m.group(1))
        out["peak_sessions"] = int(m.group(2))
    m = re.search(r"(\d+) session\(s\) per Sec out of max (\d+)", body)
    if m:
        out["sessions_per_sec"] = int(m.group(1))
        out["max_sessions_per_sec"] = int(m.group(2))
    m = re.search(r"(\d+) session\(s\) max", body)
    if m:
        out["max_sessions"] = int(m.group(1))
    m = re.search(r"min idle cpu ([\d.]+)/([\d.]+)", body)
    if m:
        out["min_idle_cpu"] = m.group(1)
        out["current_cpu"] = m.group(2)
    m = re.search(r"UP (.+?)\n", body)
    if m:
        out["uptime"] = m.group(1).strip()
    return out


async def sofia_status() -> str:
    return await api("sofia status")


async def internal_profile_ip() -> str | None:
    """IP de red local que el propio FreeSWITCH tiene funcionando ahora
    mismo para el perfil "internal" (softphones/WebRTC) — la fuente más
    confiable para sugerir `sip_server_ip` en Ajustes. Un truco de socket
    hecho desde el contenedor del backend da la IP interna de la red de
    Docker (ej. 172.23.0.3), no la IP LAN real: quedó comprobado en vivo
    que en Docker Desktop/Windows esas dos redes están aisladas entre sí.
    FreeSWITCH sí conoce la de verdad porque a esa la marcan los
    softphones reales de la LAN cuando se registran contra ella."""
    body = await sofia_status()
    m = re.search(r"^\s*internal\s+profile\s+sip:mod_sofia@([\d.]+):", body, re.MULTILINE)
    return m.group(1) if m else None


async def gateway_status(name: str) -> dict:
    """Consulta el estado real de una troncal (gateway) vía ESL."""
    validacion.exigir(validacion.NOMBRE_RE, name, "Nombre de troncal")
    body = await api(f"sofia status gateway {name}")
    out: dict = {"state": None, "status": None, "ping_ms": None, "contact_ip": None}
    if "Invalid Gateway" in body or not body.strip():
        return out
    m = re.search(r"^State\s+(\S+)", body, re.MULTILINE)
    if m:
        out["state"] = m.group(1)
    m = re.search(r"^Status\s+(\S+)", body, re.MULTILINE)
    if m:
        out["status"] = m.group(1)
    m = re.search(r"^PingTime\s+(\S+)", body, re.MULTILINE)
    if m:
        out["ping_ms"] = m.group(1)
    # La IP que el troncal le está anunciando al proveedor para que le
    # mande las llamadas entrantes de vuelta — si es privada o loopback,
    # el registro se ve "REGED" igual (el proveedor no valida esto), pero
    # ninguna llamada real va a poder entrar. Ver diagnostics() en
    # app/api/system.py, que usa este dato para avisarlo antes de que
    # alguien tenga que descubrirlo con una llamada real fallida.
    m = re.search(r"^Contact\s+<sip:[^@]*@([\d.]+)(?::(\d+))?", body, re.MULTILINE)
    if m:
        out["contact_ip"] = m.group(1)
    return out


async def dnd_status(extension: str) -> bool:
    """Lee el "no molestar" de una extensión desde la base interna de
    FreeSWITCH — el mismo lugar que consulta el dialplan en cada llamada
    (ver app/services/config_generator.py:_append_dnd_hook), así que esto
    siempre refleja el estado real, nunca uno guardado aparte que se
    pueda desincronizar."""
    validacion.exigir(validacion.EXTENSION_RE, extension, "Extensión")
    body = await api(f"db select/dnd/{extension}")
    return body.strip() == "on"


async def dnd_set(extension: str, enabled: bool) -> None:
    """Prende o apaga el DND de una extensión. Es lo mismo que hace
    marcar *78/*79 desde un teléfono — un botón en la app es solo otra
    forma de llegar al mismo estado."""
    validacion.exigir(validacion.EXTENSION_RE, extension, "Extensión")
    if enabled:
        await api(f"db insert/dnd/{extension}/on")
    else:
        await api(f"db delete/dnd/{extension}/on")


async def reloadxml() -> str:
    return await api("reloadxml")


async def rescan_profile(profile: str = "external") -> str:
    return await api(f"sofia profile {profile} rescan")


async def originate(
    dest: str,
    endpoint: str | list[str] = "sofia/external",
    caller_id: str = "NSPBX",
    caller_id_number: str | None = None,
    timeout: int = 30,
    exten: str | None = None,
    wait_timeout: int | None = None,
    extra_vars: dict[str, str] | None = None,
    contexto: str = "default",
) -> str:
    """Origina una llamada. endpoint ej: sofia/gateway/trunkX.

    `endpoint` también acepta una LISTA de tramos ya armados (uno por
    troncal, cada uno con su propio destino y, si aplica, su propio
    `{origination_caller_id_number=...}` — ver dialer.py) para reintento
    en cadena: FreeSWITCH prueba el primero y, si esa troncal no contesta
    o rechaza la llamada, pasa sola al siguiente. Con un solo string se
    arma "endpoint/dest" igual que siempre.

    `timeout` es cuánto timbra CADA tramo, no el total: en una cadena de
    varias troncales, el intento completo puede tardar hasta
    `timeout * cantidad_de_tramos`. Por eso existe `wait_timeout` aparte
    —cuánto esperamos NOSOTROS el resultado final—: si no se indica, se
    asume una sola troncal y alcanza con `timeout + 10`; quien arma una
    cadena más larga debe pasar un `wait_timeout` acorde (ver dialer.py),
    o el resultado de la segunda troncal podría llegar después de que ya
    dimos la llamada por perdida acá.

    `exten`: extensión del dialplan a ejecutar al contestar (ej. "bot_5" para
    correr el IVR de un voizbot). Si no se indica, la llamada queda en park()
    (silencio) tras contestar — comportamiento previo, sin bot asociado.

    `caller_id` es el NOMBRE a mostrar y `caller_id_number` el NÚMERO. Antes
    solo existía `caller_id` y se pasaba en la posición del nombre, dejando
    el número marcado en la del número: a quien contestaba le aparecía SU
    PROPIO número llamándolo (se lee como suplantación y es la vía rápida a
    que el operador bloquee la troncal). Sin número explícito se manda
    `_undef_`, que hace que sofia use el caller ID propio del gateway.

    `extra_vars`: variables de canal adicionales (ej. el saludo
    personalizado de una campaña de confirmación — ver dialer.py). Los
    valores se codifican con URL-encoding: sin esto, una coma o una `}` en
    el texto (un nombre compuesto, una frase con "por ejemplo, ...") rompe
    la sintaxis `{var=val,...}` del comando originate. Del otro lado,
    ai_agent.py los decodifica al leerlos.

    `contexto`: el contexto de dialplan en el que se ejecuta `exten` al
    contestar. Con varias empresas cada una tiene el suyo (`ctx_<slug>`,
    ver docs/arquitectura-multitenant.md); quien origina para una empresa
    tiene que pasarlo, o el "XML default" de antes quedaba apuntando a un
    contexto que ya no existe."""
    # Todo lo que se interpola en el comando se valida acá y no solo en el
    # esquema de entrada: este es el punto donde un valor malicioso se
    # vuelve un comando de FreeSWITCH (ver también ESLClient._send).
    validacion.exigir(validacion.TELEFONO_RE, dest, "Destino")
    if exten:
        validacion.exigir(validacion.NOMBRE_RE, exten, "Extensión de destino")
    validacion.exigir(validacion.NOMBRE_RE, contexto, "Contexto")
    caller_id = validacion.limpiar_nombre_visible(caller_id)
    if caller_id_number:
        validacion.exigir(validacion.TELEFONO_RE, caller_id_number, "Caller ID")
    action = exten if exten else "&park()"
    endpoint_str = "|".join(endpoint) if isinstance(endpoint, list) else f"{endpoint}/{dest}"
    # safe="": por defecto quote() deja pasar "/" sin escapar (piensa que
    # es una ruta de URL) — y una fecha como "8/21/26" en el saludo de una
    # campaña metía barras sueltas dentro del bloque {var=val,...}, que
    # confundían el parser del dial-string de FreeSWITCH y le hacían
    # perder el resto de la cadena de troncales (CHAN_NOT_IMPLEMENTED en
    # las troncales de respaldo, aunque la primera ni siquiera fuera la
    # que fallaba). Acá no hay URLs de por medio, así que se escapa todo.
    extra = "".join(f",{k}={quote(v, safe='')}" for k, v in (extra_vars or {}).items())
    # ignore_early_media: sin esto, un 183 Session Progress con SDP (ringback
    # con audio, típico de proveedores tipo Asterisk) hace que FreeSWITCH
    # trate la llamada como "contestada" y arranque el IVR mientras el
    # destinatario SIGUE TIMBRANDO — el saludo/menú corre y termina antes de
    # que la persona alcance a contestar de verdad. Esto fuerza a esperar el
    # 200 OK real.
    # nspbx_customer: el número del CLIENTE, fijado explícitamente acá. En
    # una llamada saliente el caller ID es el del PBX, así que el voizbot no
    # puede deducir a quién está llamando desde las variables SIP estándar
    # (antes lo sacaba del caller ID, que por el bug de arriba contenía el
    # número marcado — funcionaba por accidente). Ver ai_agent.handle_call.
    cmd = (
        f"originate {{ignore_early_media=true,nspbx_customer={dest}{extra}}}{endpoint_str} "
        f"{action} XML {contexto} '{caller_id}' '{caller_id_number or '_undef_'}' {timeout}"
    )
    return await bgapi_wait(cmd, timeout=wait_timeout if wait_timeout is not None else timeout + 10)


async def originate_bridge(
    from_endpoint: str,
    bridge_target: str,
    caller_id: str = "NSPBX",
    timeout: int = 30,
) -> str:
    """Origina una llamada a `from_endpoint`; al contestar, la bridgea a `bridge_target`.

    Uso típico (click-to-call): suena la extensión del agente y, cuando
    contesta, se conecta automáticamente con el destino (interno o vía troncal).
    """
    safe_caller_id = validacion.limpiar_nombre_visible(caller_id)
    # bridge_target y from_endpoint van sin comillas dentro del comando:
    # se restringen a lo que un destino real puede contener.
    if not re.fullmatch(r"[A-Za-z0-9_.@:/+*#-]{1,255}", bridge_target or ""):
        raise ValueError("Destino de puente con formato no permitido")
    if not re.fullmatch(r"[A-Za-z0-9_.@:/+*#-]{1,255}", from_endpoint or ""):
        raise ValueError("Origen con formato no permitido")
    cmd = (
        f"originate {{origination_caller_id_name='{safe_caller_id}',"
        f"origination_caller_id_number='{safe_caller_id}',"
        f"call_timeout={timeout}}}{from_endpoint} &bridge({bridge_target})"
    )
    return await bgapi(cmd)


async def bgapi(command: str) -> str:
    client = await get_client()
    return await client.bgapi(command)


_NIVELES_LOG = ("debug", "info", "notice", "warning", "err", "crit", "alert")


async def stream_logs(level: str = "info"):
    """Streaming en vivo del log de FreeSWITCH — el equivalente web de
    pararse en `fs_cli` con `/log <nivel>` (o `asterisk -rvvvvv` para
    quien viene de ahí). Conexión ESL PROPIA, separada de la del
    cliente de comandos y de la del oyente de BACKGROUND_JOB: esta se
    queda leyendo indefinidamente mientras dure la pestaña abierta, y no
    debe competir por el mismo socket que usan `api`/`bgapi_wait`."""
    if level not in _NIVELES_LOG:
        level = "info"
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(runtime_settings.fs_esl_host, runtime_settings.fs_esl_port), timeout=5
    )
    try:
        await _read_headers_raw(reader)  # saludo
        writer.write(f"auth {runtime_settings.fs_esl_password}\n\n".encode())
        await writer.drain()
        auth_headers = await _read_headers_raw(reader)
        if "+OK accepted" not in auth_headers.get("reply-text", ""):
            raise PermissionError("ESL auth rechazada (log stream)")
        writer.write(f"log {level}\n\n".encode())
        await writer.drain()
        await _read_headers_raw(reader)  # respuesta al comando "log"
        while True:
            headers = await _read_headers_raw(reader)
            if not headers:
                return  # FreeSWITCH cerró el socket
            body = await _read_body_raw(reader, headers)
            if headers.get("content-type") == "log/data":
                yield body
    finally:
        try:
            writer.write(b"nolog\n\n")
            await writer.drain()
        except Exception:
            pass
        writer.close()
