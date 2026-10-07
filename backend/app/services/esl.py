import asyncio
import logging
import re
from urllib.parse import quote

from app.core import validacion

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


# Un cliente de comandos y una conexión de eventos POR SERVIDOR (clave: id
# del nodo; None = el principal). Ver services/nodos.py y docs/escala.md §4.
_clientes: dict[int | None, ESLClient] = {}
_eventos: dict[int | None, asyncio.StreamWriter] = {}
_pending_jobs: dict[str, "asyncio.Future[str]"] = {}
_event_listener_lock = asyncio.Lock()

_SIN = object()  # «no se indicó servidor» (None ya significa el principal)


async def nodo_para(tenant_id: int | None = None, nodo=_SIN) -> int | None:
    """A qué servidor va un comando: el indicado; si no, el de la empresa
    indicada; si no, el del evento que se está procesando; si no, el de la
    empresa de la tarea en curso; si no, el principal."""
    from app.core.contexto import empresa_actual, hay_evento, nodo_del_evento
    from app.services.nodos import directorio

    if nodo is not _SIN:
        return nodo
    if tenant_id is not None:
        return await directorio.nodo_de(tenant_id)
    if hay_evento.get():
        return nodo_del_evento.get()
    return await directorio.nodo_de(empresa_actual.get())


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


async def _ensure_event_listener(nodo: int | None = None):
    """Conexión ESL dedicada, suscrita a BACKGROUND_JOB, para conocer el
    resultado real (contestada/ocupado/no contesta/colgada) de cada
    `originate` lanzado en background — bgapi por sí solo solo confirma que
    FreeSWITCH aceptó la orden, no el desenlace de la llamada. Una por
    servidor."""
    from app.services.nodos import directorio

    async with _event_listener_lock:
        actual = _eventos.get(nodo)
        if actual is not None and not actual.is_closing():
            return
        destino = directorio.destino(nodo)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(destino.host, destino.port), timeout=5)
        await _read_headers_raw(reader)  # greeting
        writer.write(f"auth {destino.password}\n\n".encode())
        await writer.drain()
        auth_headers = await _read_headers_raw(reader)
        if "+OK accepted" not in auth_headers.get("reply-text", ""):
            writer.close()
            raise PermissionError("ESL auth rechazada (event listener)")
        from app.services.lider import lider
        from app.services.tiempo_real import EVENTOS

        # BACKGROUND_JOB para el resultado de los originate; los de canal
        # para las llamadas en vivo (services/tiempo_real.py), SOLO en la
        # réplica líder: si dos los procesaran, cada agente cambiaría de
        # estado dos veces (services/lider.py).
        # CUSTOM callcenter::info: alguien entró a un grupo de atención (aviso
        # a la app móvil, services/push_colas.py).
        canal = f" {' '.join(EVENTOS)} CUSTOM callcenter::info" if lider.es_lider else ""
        writer.write(f"event plain BACKGROUND_JOB{canal}\n\n".encode())
        await writer.drain()
        await _read_headers_raw(reader)  # command/reply del "event"
        _eventos[nodo] = writer
        asyncio.create_task(_event_loop(reader, nodo, writer))


async def _event_loop(reader: asyncio.StreamReader, nodo: int | None = None, writer=None):
    from app.core.contexto import hay_evento, nodo_del_evento

    # Todo lo que se haga al procesar estos eventos (y las tareas que se
    # creen) va al servidor de donde vinieron (core/contexto.py).
    nodo_del_evento.set(nodo)
    hay_evento.set(True)
    try:
        while True:
            headers = await _read_headers_raw(reader)
            if not headers:
                break
            body = await _read_body_raw(reader, headers)
            if headers.get("content-type") != "text/event-plain":
                continue
            event_headers, _, result = body.partition("\n\n")
            if "\nEvent-Name: BACKGROUND_JOB\n" not in f"\n{event_headers}\n":
                from app.services.lider import lider

                if lider.es_lider:
                    await _a_tiempo_real(event_headers)
                continue
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
        logger.exception("Event listener de ESL caído (servidor %s)", nodo or "principal")
    finally:
        if writer is not None:
            writer.close()
        if _eventos.get(nodo) is writer:
            _eventos.pop(nodo, None)
        from app.services.tiempo_real import tiempo_real

        # Solo las llamadas de ESE servidor: las de los demás siguen al día.
        tiempo_real.reiniciar(nodo=nodo)


async def _a_tiempo_real(cabeceras: str) -> None:
    from app.services import agentes, predictivo
    from app.services.tiempo_real import leer_evento, tiempo_real

    ev = leer_evento(cabeceras)
    # Si ese canal se está asignando en paralelo (predictivo), su siguiente
    # evento espera: el orden por llamada se mantiene (docs/escala.md).
    await predictivo.motor.esperar(ev.get("Unique-ID") or "")
    try:
        await tiempo_real.recibir(ev)
    except Exception:
        # Un evento raro no puede tumbar la conexión de la que dependen
        # también los resultados de los originate.
        logger.exception("Evento de canal no procesado")
    try:
        await agentes.recibir(ev)
    except Exception:
        logger.exception("Evento de canal no procesado por el motor de agentes")
    try:
        await predictivo.motor.recibir(ev, en_segundo_plano=True)
    except Exception:
        logger.exception("Evento de canal no procesado por el predictivo")
    from app.services.supervision import monitoreo

    try:
        await monitoreo.recibir(ev)
    except Exception:
        logger.exception("Evento de canal no procesado por el monitoreo")
    if ev.get("Event-Name") == "CUSTOM":
        from app.services import push_colas

        # En una tarea aparte: el push espera a Apple/Google y la fila de
        # eventos no puede frenarse por eso.
        asyncio.create_task(_push_colas_seguro(push_colas, ev))


async def _push_colas_seguro(push_colas, ev: dict[str, str]) -> None:
    try:
        await push_colas.recibir(ev)
    except Exception:
        logger.exception("Aviso a la app móvil por una llamada de grupo no enviado")


async def cerrar_eventos() -> None:
    """Cierra las conexiones de eventos (al ganar o perder el liderazgo: las
    próximas se abren con la suscripción que corresponda)."""
    async with _event_listener_lock:
        for writer in list(_eventos.values()):
            writer.close()
        _eventos.clear()


async def asegurar_eventos() -> None:
    """Abre la conexión de eventos de cada servidor que no la tenga (ver
    tiempo_real.mantener_conexion). Un servidor caído no frena a los demás."""
    from app.services.nodos import directorio

    errores = []
    for nodo in await directorio.todos():
        try:
            await _ensure_event_listener(nodo)
        except Exception as exc:
            errores.append(f"{directorio.nombre(nodo)}: {exc}")
    if errores:
        raise RuntimeError("; ".join(errores))


async def bgapi_wait(command: str, timeout: int = 40, tenant_id: int | None = None) -> str:
    """Como bgapi, pero espera el evento BACKGROUND_JOB y devuelve/lanza el
    resultado real del comando (p.ej. la llamada fue contestada, colgada,
    ocupada, sin respuesta, etc.), en vez de solo confirmar que se encoló."""
    nodo = await nodo_para(tenant_id)
    await _ensure_event_listener(nodo)
    client = await get_client(nodo)
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


async def get_client(nodo: int | None = None) -> ESLClient:
    from app.services.nodos import directorio

    # Sin lock, dos corrutinas concurrentes podían ver el cliente caído a
    # la vez y abrir dos conexiones — la primera quedaba huérfana (nunca
    # cerrada) y cualquier callback pendiente en ella se perdía.
    async with _client_lock:
        cliente = _clientes.get(nodo)
        destino = directorio.destino(nodo)
        cambio = cliente is not None and (cliente.host, cliente.port, cliente.password) != (destino.host, destino.port, destino.password)
        if cliente is None or not cliente.connected or cambio:
            if cliente:
                await cliente.close()
            cliente = ESLClient(destino.host, destino.port, destino.password)
            await cliente.connect()
            _clientes[nodo] = cliente
        return cliente


async def invalidate_client():
    """Fuerza una reconexión (con los parámetros vigentes) en la próxima llamada."""
    for cliente in list(_clientes.values()):
        await cliente.close()
    _clientes.clear()
    await cerrar_eventos()


async def api(command: str, tenant_id: int | None = None, nodo=_SIN) -> str:
    client = await get_client(await nodo_para(tenant_id, nodo))
    return await client.api(command)


async def api_todos(command: str) -> dict:
    """El mismo comando en TODOS los servidores (recargar la configuración,
    colgar huérfanas). Devuelve {nodo: respuesta o la excepción}: un servidor
    caído no impide que los demás lo reciban."""
    from app.services.nodos import directorio

    resultados: dict = {}
    for nodo in await directorio.todos():
        try:
            resultados[nodo] = await api(command, nodo=nodo)
        except Exception as exc:
            logger.warning("«%s» falló en el servidor %s: %s", command.split()[0], directorio.nombre(nodo), exc)
            resultados[nodo] = exc
    return resultados


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


async def sesiones_en_curso() -> int:
    """Canales en curso sumando todos los servidores. Lanza si el principal
    no responde (quien marca prefiere no marcar a pasar el tope a ciegas);
    un adicional caído no cuenta (sus empresas no pueden marcar igual)."""
    from app.services.nodos import directorio

    total = (await status()).get("current_sessions", 0)
    for nodo in (await directorio.todos())[1:]:
        try:
            body = await api("status", nodo=nodo)
        except Exception:
            continue
        m = re.search(r"(\d+) session\(s\) - peak", body)
        total += int(m.group(1)) if m else 0
    return total


async def api_buscar(command: str) -> str:
    """El comando en cada servidor hasta que uno responda sin -ERR (para
    algo que se sabe de un canal pero no de qué servidor es)."""
    from app.services.nodos import directorio

    ultimo = ""
    for nodo in await directorio.todos():
        try:
            ultimo = await api(command, nodo=nodo)
        except Exception as exc:
            ultimo = f"-ERR {exc}"
            continue
        if not ultimo.strip().startswith("-ERR"):
            return ultimo
    return ultimo


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


async def gateway_status(name: str, tenant_id: int | None = None) -> dict:
    """Consulta el estado real de una troncal (gateway) vía ESL, en el
    servidor de su empresa (sin `tenant_id`, el del contexto en curso)."""
    validacion.exigir(validacion.NOMBRE_RE, name, "Nombre de troncal")
    body = await api(f"sofia status gateway {name}", tenant_id=tenant_id)
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


def clave_dnd(extension: str, tenant_id: int) -> str:
    """Clave del "no molestar" en la base interna de FreeSWITCH. Lleva la
    empresa: esa base es UNA para toda la plataforma, y con solo el número
    la extensión 1000 de una empresa y la 1000 de otra compartían el estado
    (prender DND en una lo prendía en la otra)."""
    validacion.exigir(validacion.EXTENSION_RE, extension, "Extensión")
    return f"{extension}_t{int(tenant_id)}"


ESTADO_AGENTE_DND = {True: "'On Break'", False: "Available"}


async def dnd_status(extension: str, tenant_id: int) -> bool:
    """Lee el "no molestar" de una extensión desde la base interna de
    FreeSWITCH — el mismo lugar que consulta el dialplan en cada llamada
    (ver app/services/config_generator.py:_append_dnd_hook), así que esto
    siempre refleja el estado real, nunca uno guardado aparte que se
    pueda desincronizar."""
    body = await api(f"db select/dnd/{clave_dnd(extension, tenant_id)}", tenant_id=tenant_id)
    return body.strip() == "on"


async def dnd_set(extension: str, tenant_id: int, dominio: str, enabled: bool) -> None:
    """Prende o apaga el DND de una extensión. Es lo mismo que hace
    marcar *78/*79 desde un teléfono — un botón en la app es solo otra
    forma de llegar al mismo estado.

    También pone al agente de cola de esa extensión en pausa ('On Break') o
    disponible: mod_callcenter le marca directo al agente, sin pasar por el
    dialplan, así que sin esto las colas le seguían timbrando con DND."""
    clave = clave_dnd(extension, tenant_id)
    validacion.exigir(validacion.HOST_RE, dominio, "Dominio")
    if enabled:
        await api(f"db insert/dnd/{clave}/on", tenant_id=tenant_id)
    else:
        await api(f"db delete/dnd/{clave}/on", tenant_id=tenant_id)
    # Si la extensión no es agente de ninguna cola responde -ERR: no importa.
    await api(f"callcenter_config agent set status {extension}@{dominio} {ESTADO_AGENTE_DND[enabled]}", tenant_id=tenant_id)


async def reloadxml() -> str:
    """En todos los servidores (la configuración es la misma para todos).
    Devuelve la respuesta del principal, o lanza si el principal falló."""
    resultados = await api_todos("reloadxml")
    principal = resultados.get(None)
    if isinstance(principal, Exception):
        raise principal
    return principal or ""


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
    tenant_id: int | None = None,
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
    return await bgapi_wait(cmd, timeout=wait_timeout if wait_timeout is not None else timeout + 10, tenant_id=tenant_id)


async def originate_bridge(
    from_endpoint: str,
    bridge_target: str,
    caller_id: str = "NSPBX",
    timeout: int = 30,
    variables: dict[str, str] | None = None,
    tenant_id: int | None = None,
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
    # `variables`: marcas propias (p. ej. nspbx_saliente); nombre y valor
    # restringidos, van dentro del bloque {…} sin comillas.
    extra = ""
    for k, v in (variables or {}).items():
        if not (re.fullmatch(r"[a-z_]{1,40}", k) and re.fullmatch(r"[A-Za-z0-9_.@-]{1,120}", v)):
            raise ValueError("Variable de canal con formato no permitido")
        extra += f",{k}={v}"
    cmd = (
        f"originate {{origination_caller_id_name='{safe_caller_id}',"
        f"origination_caller_id_number='{safe_caller_id}',"
        f"call_timeout={timeout}{extra}}}{from_endpoint} &bridge({bridge_target})"
    )
    return await bgapi(cmd, tenant_id=tenant_id)


async def bgapi(command: str, tenant_id: int | None = None, nodo=_SIN) -> str:
    client = await get_client(await nodo_para(tenant_id, nodo))
    return await client.bgapi(command)


_NIVELES_LOG = ("debug", "info", "notice", "warning", "err", "crit", "alert")


async def stream_logs(level: str = "info", nodo: int | None = None):
    """Streaming en vivo del log de FreeSWITCH — el equivalente web de
    pararse en `fs_cli` con `/log <nivel>` (o `asterisk -rvvvvv` para
    quien viene de ahí). Conexión ESL PROPIA, separada de la del
    cliente de comandos y de la del oyente de BACKGROUND_JOB: esta se
    queda leyendo indefinidamente mientras dure la pestaña abierta, y no
    debe competir por el mismo socket que usan `api`/`bgapi_wait`."""
    from app.services.nodos import directorio

    if level not in _NIVELES_LOG:
        level = "info"
    destino = directorio.destino(nodo)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(destino.host, destino.port), timeout=5)
    try:
        await _read_headers_raw(reader)  # saludo
        writer.write(f"auth {destino.password}\n\n".encode())
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
