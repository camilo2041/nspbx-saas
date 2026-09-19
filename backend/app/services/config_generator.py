import json
import logging
import re
import xml.etree.ElementTree as ET

from app.core import validacion
from app.core.config import settings
from app.core.firmas import firma_push
from app.services import voice_prompts
from app.services.flow_engine import build_voicebot_flow_routes

logger = logging.getLogger(__name__)


def _e(tag: str, text: str | None = None, attrib: dict | None = None) -> ET.Element:
    el = ET.Element(tag, attrib or {})
    if text:
        el.text = text
    return el


def _dashed_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def build_directory_xml(tenantes: list[dict]) -> str:
    """Genera la seccion <section name='directory'>.

    `tenantes` es una lista de dicts con `dominio` (Tenant.sip_domain o el
    de Ajustes), `contexto` (ctx_<slug>) y `extensions` (solo las de esa
    empresa). Cada empresa recibe su propio bloque `<domain name=...>`: es
    la etiqueta con la que FreeSWITCH decide de quién es cada teléfono que
    se registra, y `user_context` dentro de cada usuario es lo que hace que
    sus llamadas entren al contexto de su empresa y no al de otra.
    """
    root = _e("document", attrib={"type": "freeswitch/xml"})
    section = ET.SubElement(root, "section", attrib={"name": "directory"})
    for t in tenantes:
        dominio = t["dominio"]
        contexto = t["contexto"]
        domain = ET.SubElement(section, "domain", attrib={"name": dominio})
        params = ET.SubElement(domain, "params")
        ET.SubElement(params, "param", attrib={"name": "dial-string", "value": "{^^:sip_invite_domain=${dialed_domain}:presence_id=${dialed_user}@${dialed_domain}}${sofia_contact(*/${dialed_user}@${dialed_domain})}"})
        groups = ET.SubElement(domain, "groups")
        group = ET.SubElement(groups, "group", attrib={"name": "default"})
        users = ET.SubElement(group, "users")
        for ext in t["extensions"]:
            user = ET.SubElement(users, "user", attrib={"id": ext.number})
            params = ET.SubElement(user, "params")
            ET.SubElement(params, "param", attrib={"name": "password", "value": ext.password})
            ET.SubElement(params, "param", attrib={"name": "vm-password", "value": ext.password})
            v = ET.SubElement(user, "variables")
            if ext.caller_id_name:
                ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_name", "value": ext.caller_id_name})
            ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_number", "value": ext.number})
            ET.SubElement(v, "variable", attrib={"name": "user_context", "value": contexto})
    return validacion.limpiar_xml(ET.tostring(root, encoding="unicode"))


def build_guest_directory_xml(username: str, password: str, domain: str, context_name: str) -> str:
    """Directorio de UN usuario invitado del widget de llamada web (ver
    app/services/webcall.py). Se genera al vuelo en cada lookup de
    mod_xml_curl porque estas credenciales son efímeras y no viven en la
    base.

    Clave del aislamiento anti-fraude: `user_context = context_name`
    (`webcall_<slug>` de la empresa dueña del widget), NO el contexto
    normal de la empresa. Ese contexto (ver _append_webcall_context) solo
    sabe llegar a la cola configurada — cualquier otro destino se cuelga.

    `domain` es el `Tenant.sip_domain` de la empresa dueña del widget, no
    un dominio global: con varias empresas, cada una tiene el suyo."""
    root = _e("document", attrib={"type": "freeswitch/xml"})
    section = ET.SubElement(root, "section", attrib={"name": "directory"})
    domain_el = ET.SubElement(section, "domain", attrib={"name": domain})
    params = ET.SubElement(domain_el, "params")
    ET.SubElement(params, "param", attrib={"name": "dial-string", "value": "{^^:sip_invite_domain=${dialed_domain}:presence_id=${dialed_user}@${dialed_domain}}${sofia_contact(*/${dialed_user}@${dialed_domain})}"})
    groups = ET.SubElement(domain_el, "groups")
    group = ET.SubElement(groups, "group", attrib={"name": "default"})
    users = ET.SubElement(group, "users")
    user = ET.SubElement(users, "user", attrib={"id": username})
    p = ET.SubElement(user, "params")
    ET.SubElement(p, "param", attrib={"name": "password", "value": password})
    v = ET.SubElement(user, "variables")
    ET.SubElement(v, "variable", attrib={"name": "user_context", "value": context_name})
    ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_name", "value": "Llamada web"})
    ET.SubElement(v, "variable", attrib={"name": "effective_caller_id_number", "value": username})
    return validacion.limpiar_xml(ET.tostring(root, encoding="unicode"))


def _decir(condition: ET.Element, prompt_key: str, texto_respaldo: str) -> None:
    """Reproduce un aviso corto pre-generado (voz real, en español) si ya
    existe; si todavía no se sintetizó (recién instalado, sin API key de
    Deepgram cargada), cae a `speak` con flite como único respaldo posible
    — suena peor, pero ninguna llamada se queda sin ningún aviso."""
    ruta = voice_prompts.prompt_path(prompt_key)
    if ruta:
        ET.SubElement(condition, "action", attrib={"application": "playback", "data": ruta})
    else:
        ET.SubElement(condition, "action", attrib={"application": "speak", "data": f"flite|kal|{texto_respaldo}"})


def _append_dnd_feature_codes(context: ET.Element) -> None:
    """*78 activa "no molestar" para quien marca, *79 lo apaga.

    Es el código de función estándar que cualquier softphone o teléfono
    SIP de escritorio sabe marcar (muchos hasta lo mandan solos cuando se
    aprieta su propio botón de DND) — no depende de que el cliente tenga
    nada especial, solo de que el servidor sepa qué hacer con esos dígitos.

    El estado se guarda en la base interna de FreeSWITCH (`db insert`),
    no en Postgres: se consulta en caliente en CADA llamada entrante a una
    extensión (ver _append_dnd_hook) y no vale la pena el viaje a la base
    de la app por algo que se prende y apaga desde el propio teléfono.
    """
    activar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_on", "continue": "false"})
    c1 = ET.SubElement(activar, "condition", attrib={"field": "destination_number", "expression": r"^\*78$"})
    ET.SubElement(c1, "action", attrib={"application": "answer"})
    ET.SubElement(c1, "action", attrib={"application": "db", "data": "insert/dnd/${caller_id_number}/on"})
    _decir(c1, "dnd_on", "No molestar activado.")
    ET.SubElement(c1, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    desactivar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_off", "continue": "false"})
    c2 = ET.SubElement(desactivar, "condition", attrib={"field": "destination_number", "expression": r"^\*79$"})
    ET.SubElement(c2, "action", attrib={"application": "answer"})
    ET.SubElement(c2, "action", attrib={"application": "db", "data": "delete/dnd/${caller_id_number}/on"})
    _decir(c2, "dnd_off", "No molestar desactivado.")
    ET.SubElement(c2, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _append_dnd_hook(context: ET.Element, extensions: list) -> None:
    """Si la extensión destino tiene DND activo, corta acá con ocupado en
    vez de timbrar. Va ANTES de Local_Extension, con continue="false" —
    solo se llega a cortar si de verdad hay DND activo; si no, esta
    extensión ni siquiera matchea y la llamada sigue de largo.

    La consulta a la base de FreeSWITCH va DIRECTO en el `field` de la
    condición (no en un `set` de una extensión previa): probado en vivo
    que separar "guardar la variable" y "leerla" en dos extensiones
    distintas no funciona de forma confiable — la variable quedaba
    seteada (confirmado con uuid_dump) pero la condición que la leía
    después no la evaluaba. Con la consulta inline en la misma condición
    no hay ese problema.
    """
    if not extensions:
        return
    numbers = "|".join(e.number for e in extensions)

    cortar = ET.SubElement(context, "extension", attrib={"name": "nspbx_dnd_cortar", "continue": "false"})
    c1 = ET.SubElement(cortar, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    c2 = ET.SubElement(cortar, "condition", attrib={"field": "${db(select/dnd/${destination_number})}", "expression": "^on$"})
    ET.SubElement(c2, "action", attrib={"application": "answer"})
    _decir(c2, "dnd_no_disponible", "La extensión no está disponible en este momento.")
    ET.SubElement(c2, "action", attrib={"application": "hangup", "data": "USER_BUSY"})


def _append_mobile_push_hook(context: ET.Element, extensions: list, push_numbers: set[str], slug: str) -> None:
    """Antes de timbrarle a una extensión que tiene la app móvil registrada
    (ver DeviceToken/api/fs_push.py), avisa al backend para que dispare un
    push de voz (PushKit/FCM) — es lo único que puede despertar la app si
    el teléfono está bloqueado o la app en segundo plano.

    `continue="true"`: el aviso no reemplaza el timbrado SIP normal, sale
    en paralelo antes de que la llamada siga su ruteo de siempre
    (Local_Extension o la ruta entrante que la trajo hasta este contexto —
    ver _append_inbound_routes, que transfiere acá con el dialplan-hunt
    completo, por eso alcanza con este único hook por contexto).

    La URL NO lleva `FS_XML_SECRET` sino una firma HMAC atada a esta
    extensión concreta (ver core/firmas.py): el XML del dialplan y los logs
    de FreeSWITCH —que un admin de empresa puede ver desde la consola web—
    dejan de contener la llave maestra. Por eso hay una regla por extensión
    en vez de una sola con todos los números: cada una firma la suya.

    Los datos de quien llama van con url_encode: un nombre con `&`, `#` o
    espacios podía inyectar parámetros propios (`call_uuid`, `caller_id_number`)
    o argumentos de mod_curl.
    """
    numbers = sorted(e.number for e in extensions if e.number in push_numbers)
    if not numbers or not settings.fs_xml_secret:
        return
    for numero in numbers:
        extension = ET.SubElement(
            context, "extension", attrib={"name": f"nspbx_mobile_push_{numero}", "continue": "true"}
        )
        condition = ET.SubElement(
            extension, "condition", attrib={"field": "destination_number", "expression": f"^{re.escape(numero)}$"}
        )
        url = (
            f"http://backend:8000/fs/push/{firma_push(slug, numero)}/{slug}/{numero}"
            "?caller_id_number=${url_encode(${caller_id_number})}"
            "&caller_id_name=${url_encode(${caller_id_name})}"
            "&call_uuid=${uuid} get"
        )
        ET.SubElement(condition, "action", attrib={"application": "curl", "data": url})


def _append_local_extension_route(context: ET.Element, extensions: list, dominio: str) -> None:
    """Extension a extension (Local_Extension)."""
    if not extensions:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "Local_Extension", "continue": "false"})
    numbers = "|".join(e.number for e in extensions)
    condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    ET.SubElement(condition, "action", attrib={"application": "log", "data": "Llamada local a extension"})
    # SIN "answer" acá — contestaba la pata de quien LLAMA antes de
    # siquiera intentar timbrarle a quien recibe. Entre dos softphones
    # (SIP.js/WebRTC), eso le manda un 200 OK al que llama al instante:
    # su pantalla salta a "en llamada" sin que el otro lado haya hecho
    # nada, y a quien recibe nunca le suena porque bridge todavía ni
    # arrancó. Sin este "answer", la pata de quien llama se queda
    # timbrando de verdad hasta que el destino conteste — es `bridge`
    # el que se encarga de contestarla en ese momento, no antes.
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "continue_on_fail=true"})
    # Tono de "llamando" para quien marca (425 Hz, 1 s sí / 4 s no) como audio previo a
    # la respuesta: sin él, la pata de quien llama timbra en silencio.
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "ringback=%(1000,4000,425)"})
    # El dominio literal de la EMPRESA y no $${domain} (variable global):
    # con varias empresas, $${domain} no puede ser el de todas a la vez y
    # `user/<ext>@$${domain}` terminaría buscando el contacto en el dominio
    # equivocado. Acá cada contexto ya sabe de qué empresa es.
    ET.SubElement(condition, "action", attrib={"application": "bridge", "data": f"user/${{destination_number}}@{dominio}"})
    anti = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^({numbers})$"})
    anti.set("break", "on-false")
    ET.SubElement(anti, "action", attrib={"application": "hangup", "data": "NO_ANSWER"})


def _parse_bot_menu(config_json: str | None) -> dict[str, str]:
    """Lee `{"menu": {"1": "1000", "2": "1001"}}` del campo config del bot.

    Solo se aceptan teclas de un dígito (0-9, *, #) mapeadas a un número de
    extensión, para mantener el IVR simple (sin IA) y su enrutamiento seguro.
    """
    if not config_json:
        return {}
    try:
        data = json.loads(config_json)
    except (ValueError, TypeError):
        return {}
    menu = data.get("menu") if isinstance(data, dict) else None
    if not isinstance(menu, dict):
        return {}
    out: dict[str, str] = {}
    for digit, target in menu.items():
        digit = str(digit).strip()
        target = str(target).strip()
        # El destino va en `transfer "<destino> XML <contexto>"`: con un
        # espacio, "1000 XML ctx_otra" mandaba la llamada al contexto de otra
        # empresa. Solo un token sin espacios.
        if len(digit) == 1 and digit in "0123456789*#" and validacion.DESTINO_RE.fullmatch(target):
            out[digit] = target
    return out


def _append_voicebot_routes(
    section: ET.Element, context: ET.Element, bots: list, dominio: str, tenant_id: int
) -> None:
    """IVR simple (sin IA): saluda con audio o texto (TTS) y enruta según la
    tecla presionada hacia una extensión, reutilizando Local_Extension.

    IMPORTANTE: las condiciones de un <extension> se evalúan TODAS al
    momento de enrutar la llamada (antes de ejecutar ninguna acción), no en
    vivo mientras corre `read`. Por eso el dígito capturado no se puede
    comparar con `<condition field="${var}">` en la MISMA extensión — para
    cuando se evalúa, la variable aún no existe. La forma correcta es
    transferir a un CONTEXTO nuevo usando el valor de la variable como
    destination_number: `transfer` resuelve eso en tiempo de ejecución, y el
    contexto destino hace un dialplan-hunt nuevo con el dígito ya capturado.
    """
    for bot in bots:
        if bot.bot_type != "ivr":
            continue  # los bots de IA se entregan directo al motor (campaña o flujo)
        if build_voicebot_flow_routes(section, context, bot, dominio, tenant_id):
            continue  # el bot tiene un flujo visual (nodos/edges); ya se generó su dialplan
        menu = _parse_bot_menu(bot.config)
        var_name = f"ivr_digit_{bot.id}"
        menu_context_name = f"ivr_menu_{bot.id}"

        extension = ET.SubElement(context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}", "continue": "false"})
        entry = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
        ET.SubElement(entry, "action", attrib={"application": "answer"})
        ET.SubElement(entry, "action", attrib={"application": "sleep", "data": "300"})

        if not menu:
            saludo_audio = validacion.ruta_audio_segura(bot.greeting_audio_path)
            saludo_texto = validacion.texto_hablado(bot.welcome_message)
            if saludo_audio:
                ET.SubElement(entry, "action", attrib={"application": "playback", "data": saludo_audio})
            elif saludo_texto:
                ET.SubElement(entry, "action", attrib={"application": "speak", "data": f"flite|kal|{saludo_texto}"})
            ET.SubElement(entry, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            continue

        # Nota: se probó pasar el audio directo como prompt de `read` para
        # evitar perder el dígito en la transición playback→read, pero
        # `read` no reproduce bien un mp3 largo como prompt (aborta en ~1s
        # y cae al resguardo en inglés) — peor que el problema original.
        # Se reproduce por separado; sin terminadores en `read` (abajo),
        # que sí era una causa real y confirmada de pérdida del dígito.
        saludo_audio = validacion.ruta_audio_segura(bot.greeting_audio_path)
        saludo_texto = validacion.texto_hablado(bot.welcome_message)
        if saludo_audio:
            ET.SubElement(entry, "action", attrib={"application": "playback", "data": saludo_audio})
        elif saludo_texto:
            # mod_flite no trae voz en español (se oye con acento inglés);
            # es solo resguardo si no hay audio propio.
            ET.SubElement(entry, "action", attrib={"application": "speak", "data": f"flite|kal|{saludo_texto}"})

        # Valor por defecto ANTES de leer el dígito: si el que llama no
        # marca nada (timeout), la variable queda vacía — eso rompe el
        # parseo de argumentos de `transfer` más abajo (un exten vacío
        # desplaza los argumentos siguientes). "x" nunca matchea ningún
        # dígito real, así que cae limpio en la opción inválida.
        ET.SubElement(entry, "action", attrib={"application": "set", "data": f"{var_name}=x"})
        # `read` demostró (con llamadas reales) no guardar el dígito en la
        # variable aunque el DTMF sí llega — confirmado con un log de
        # diagnóstico. Se usa `play_and_get_digits`, la aplicación
        # recomendada de FreeSWITCH para menús IVR de un dígito.
        ET.SubElement(
            entry,
            "action",
            attrib={
                "application": "play_and_get_digits",
                "data": f"1 1 1 7000 # silence_stream://200 silence_stream://200 {var_name} \\d|\\* 5000",
            },
        )
        # Transferir usando el valor EN VIVO de la variable (se resuelve al
        # ejecutar, no al enrutar) hacia un contexto dedicado a este menú.
        ET.SubElement(entry, "action", attrib={"application": "transfer", "data": f"${{{var_name}}} XML {menu_context_name}"})

        # Contexto aparte: aquí destination_number SÍ es el dígito recién
        # capturado, porque el dialplan-hunt vuelve a ocurrir al transferir.
        menu_context = ET.SubElement(section, "context", attrib={"name": menu_context_name})
        for digit, target in menu.items():
            option = ET.SubElement(menu_context, "extension", attrib={"name": f"opcion_{digit}", "continue": "false"})
            cond = ET.SubElement(option, "condition", attrib={"field": "destination_number", "expression": f"^{_escape_regex_digit(digit)}$"})
            ET.SubElement(cond, "action", attrib={"application": "transfer", "data": f"{target} XML default"})

        fallback_ext = ET.SubElement(menu_context, "extension", attrib={"name": "opcion_invalida", "continue": "false"})
        fallback = ET.SubElement(fallback_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
        ET.SubElement(fallback, "action", attrib={"application": "answer"})
        # Si el bot tiene audio propio, no se mezcla con voz sintética de
        # respaldo al final — se cuelga en silencio. El TTS de "opción
        # inválida" solo se usa cuando TODO el bot es por voz sintética
        # (sin audio propio subido).
        if not bot.greeting_audio_path:
            ET.SubElement(fallback, "action", attrib={"application": "speak", "data": "flite|kal|Opcion invalida. Hasta luego."})
        ET.SubElement(fallback, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _escape_regex_digit(digit: str) -> str:
    """Escapa el * (cuantificador en regex) al construir la expresión; # no
    necesita escape, es un carácter literal."""
    return "\\" + digit if digit == "*" else digit


def orden_troncales(trunks: list, principal_id: int | None = None) -> list:
    """Troncales habilitadas, en el orden en que hay que intentarlas.

    Si se indica `principal_id` (la troncal que alguien eligió a propósito
    para una campaña o un click-to-call), va primero; el resto entra como
    respaldo en el orden en que se dieron de alta. Sin `principal_id`,
    simplemente el orden de alta decide quién es la principal.

    Esta lista es la base de la redundancia de salida: con una sola
    troncal habilitada, el comportamiento es idéntico a antes (una sola
    pata). En cuanto hay una segunda troncal habilitada, cualquier salida
    empieza a poder recurrir a ella sola, sin que nadie tenga que
    reaccionar a mitad de una llamada real.
    """
    habilitadas = sorted((t for t in trunks if t.enabled), key=lambda t: t.id)
    if principal_id is None:
        return habilitadas
    principal = next((t for t in habilitadas if t.id == principal_id), None)
    if principal is None:
        return habilitadas
    return [principal] + [t for t in habilitadas if t.id != principal_id]


def _append_outbound_route(
    context: ET.Element,
    trunks: list,
    slug_por_tenant: dict[int, str],
    permitir_internacional: bool = False,
    tope_simultaneas: int = 0,
    slug: str = "",
) -> None:
    """Ruta de salida: números externos (7-15 dígitos) vía la cadena de
    troncales habilitadas, en serie (separadas por "|" en `bridge`, que es
    la sintaxis de FreeSWITCH para "probá la primera; si no contesta o la
    rechaza, probá la siguiente"). Con una sola troncal habilitada, esto
    genera exactamente la misma llamada de antes.

    Nota: es una ruta única simple (no hay aún "outbound routes" con
    patrones por troncal como en Issabel/FreePBX). Si se necesitan varias
    troncales con distintos patrones de marcado, esto debe evolucionar a
    algo configurable.
    """
    cadena = orden_troncales(trunks)
    if not cadena:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "Outbound_External", "continue": "false"})
    # Sin permiso internacional: nada de prefijos 00/011 ni de más de 10
    # dígitos (el fraude cae en destinos de ese tipo).
    expresion = r"^(\d{7,15})$" if permitir_internacional else r"^(?!00|011)(\d{7,10})$"
    condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": expresion})
    # Tope de salientes simultáneas de la empresa: al superarlo se rechaza
    # la llamada en vez de saturar la troncal (y el saldo).
    if tope_simultaneas and tope_simultaneas > 0 and validacion.NOMBRE_RE.fullmatch(slug or ""):
        ET.SubElement(condition, "action", attrib={"application": "limit", "data": f"hash outbound {slug} {int(tope_simultaneas)} !CALL_REJECTED"})
    nombres = " -> ".join(t.name for t in cadena)
    ET.SubElement(condition, "action", attrib={"application": "log", "data": f"Llamada saliente vía {nombres}"})
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
    # Tono de "está llamando" (425 Hz, 1 s sí / 4 s no, el de Colombia) para quien
    # marca: FreeSWITCH lo envía como audio previo a la respuesta (183) mientras el
    # proveedor no mande el suyo. Sin esto, si el proveedor solo manda "180 Ringing"
    # sin audio, quien llama oye silencio hasta que le contestan.
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "ringback=%(1000,4000,425)"})
    # El gateway en sofia lleva el slug de la empresa como prefijo (ver
    # app/services/gateways.py) — sin él, la ruta apuntaría a un gateway
    # que no existe o al de otra empresa.
    destinos = "|".join(
        f"sofia/gateway/{slug_por_tenant.get(t.tenant_id, 'x')}_{t.name}/${{destination_number}}"
        for t in cadena
    )
    ET.SubElement(condition, "action", attrib={"application": "bridge", "data": destinos})


def _append_queue_routes(context: ET.Element, queues: list, dominio: str) -> None:
    """Extensión de entrada de cada cola: contesta y entra a mod_callcenter.
    Si la cola se agota (timeout/sin agentes) o `callcenter` falla, sigue a
    la extensión de desbordamiento (o cuelga si no hay una configurada) —
    igual que el "Fail over destination" de las colas en Issabel/FreePBX.

    El nombre de la cola lleva el dominio de la empresa porque en
    mod_callcenter los nombres son GLOBALES: con el dominio, la cola
    "soporte" de una empresa y la de otra no son la misma (ver
    app/services/queues_sync.py)."""
    for queue in queues:
        if not queue.enabled:
            continue
        if not validacion.NOMBRE_RE.fullmatch(queue.name or ""):
            # Guardada antes de existir la validación: el nombre entra en el
            # dato de la acción `callcenter`, no se arriesga.
            logger.error("Cola %s omitida en el dialplan: nombre %r no válido", queue.id, queue.name)
            continue
        qkey = f"{queue.name}@{dominio}"
        extension = ET.SubElement(context, "extension", attrib={"name": f"queue_{queue.name}", "continue": "false"})
        condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": f"^{re.escape(str(queue.extension))}$"})
        ET.SubElement(condition, "action", attrib={"application": "answer"})
        ET.SubElement(condition, "action", attrib={"application": "set", "data": "hangup_after_bridge=false"})
        ET.SubElement(condition, "action", attrib={"application": "callcenter", "data": qkey})
        if queue.failover_extension and validacion.DESTINO_RE.fullmatch(queue.failover_extension):
            ET.SubElement(condition, "action", attrib={"application": "transfer", "data": f"{queue.failover_extension} XML {context.get('name')}"})
        else:
            ET.SubElement(condition, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})


def _append_inbound_routes(
    public_context: ET.Element, routes: list, contextos: dict[int, str], dominios: dict[int, str]
) -> None:
    """Contexto "public": adonde caen las llamadas entrantes de la troncal
    (ver sip_profiles/external.xml y el context="public" de cada gateway).
    Cada ruta hace matching por DID (número marcado por quien llama) y
    transfiere al contexto de SU empresa (ctx_<slug>), reutilizando TODO el
    ruteo que ya existe ahí (extensión → Local_Extension, cola →
    queue_<nombre>, voizbot → bot_<id>) — igual que "Inbound Routes" en
    Issabel/FreePBX.

    Es el único lugar donde el ruteo cruza empresas: la llamada entrante
    solo trae el número marcado, y ese número es la clave que decide de
    quién es. El DID es único en toda la plataforma (ver
    InboundRoute.did_pattern en los modelos).

    Si ninguna ruta matchea, se cuelga (UNALLOCATED_NUMBER) en vez de
    dejar pasar la llamada sin control — eso sería un hueco de fraude
    telefónico (un desconocido podría terminar pudiendo marcar salientes
    vía la troncal).
    """
    tag_ext = ET.SubElement(public_context, "extension", attrib={"name": "outside_call_tag", "continue": "true"})
    tag_cond = ET.SubElement(tag_ext, "condition")
    ET.SubElement(tag_cond, "action", attrib={"application": "set", "data": "outside_call=true"})

    def _es_comodin(r) -> bool:
        return r.did_pattern.strip().lower() in ("any", "*", "")

    # Los comodines van SIEMPRE al final, sin importar su prioridad. Este
    # contexto es compartido por todas las empresas: un comodín con
    # prioridad 0 quedaba antes de los DID exactos de las demás y les
    # robaba TODAS las llamadas entrantes, sin ningún error visible.
    ordered = sorted((r for r in routes if r.enabled), key=lambda r: (_es_comodin(r), r.priority, r.id))
    for route in ordered:
        pattern = route.did_pattern.strip()
        # re.escape: el DID es un número exacto, no una expresión. Con datos
        # guardados antes de validarlos, un "5.*" seguía funcionando como
        # regex y capturaba números ajenos.
        expression = ".*" if _es_comodin(route) else f"^{re.escape(pattern)}$"
        if route.destination_type != "hangup" and not validacion.destino_valido(
            route.destination_type, route.destination_value
        ):
            logger.error(
                "Ruta entrante %s omitida: destino %r no válido para el tipo %r",
                route.id, route.destination_value, route.destination_type,
            )
            continue
        destino_ctx = contextos.get(route.tenant_id) or "default"
        extension = ET.SubElement(public_context, "extension", attrib={"name": f"did_{route.id}_{route.name}", "continue": "false"})
        condition = ET.SubElement(extension, "condition", attrib={"field": "destination_number", "expression": expression})
        ET.SubElement(condition, "action", attrib={"application": "set", "data": f"domain_name={dominios.get(route.tenant_id, '$${domain}')}"})
        if route.destination_type == "hangup" or not route.destination_value:
            ET.SubElement(condition, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
        else:
            ET.SubElement(condition, "action", attrib={"application": "transfer", "data": f"{route.destination_value} XML {destino_ctx}"})

    fallback = ET.SubElement(public_context, "extension", attrib={"name": "no_route", "continue": "false"})
    fb_cond = ET.SubElement(fallback, "condition", attrib={"field": "destination_number", "expression": ".*"})
    ET.SubElement(fb_cond, "action", attrib={"application": "hangup", "data": "UNALLOCATED_NUMBER"})


def _append_recording_hook(context: ET.Element) -> None:
    """Graba TODA llamada del contexto. Va primero y con continue="true"
    para que la llamada siga su ruteo normal después.

    `nspbx_recording` guarda la ruta en el propio canal, así viaja dentro
    del CDR que FreeSWITCH manda al backend al colgar y la app sabe qué
    archivo corresponde a cada llamada (ver backend/app/api/calls.py).
    """
    extension = ET.SubElement(context, "extension", attrib={"name": "nspbx_grabar_todo", "continue": "true"})
    condition = ET.SubElement(extension, "condition")
    ET.SubElement(condition, "action", attrib={"application": "set", "data": "RECORD_STEREO=false"})
    # Organizadas por fecha (AAAA/MM/DD) en vez de todas sueltas en un solo
    # directorio — con meses de campañas activas, un directorio plano se
    # vuelve imposible de navegar a mano y de acotar por retención.
    dia = "${strftime(%Y)}/${strftime(%m)}/${strftime(%d)}"
    ET.SubElement(
        condition,
        "action",
        attrib={"application": "set", "data": f"nspbx_recording=$${{recordings_dir}}/{dia}/llamada_${{uuid}}.wav"},
    )
    # `record_session` no crea subdirectorios nuevos por su cuenta — hay
    # que asegurarse de que la carpeta del día exista ANTES de grabar.
    # `system` (no `bg_system`) porque record_session, la acción
    # siguiente, necesita que el mkdir ya haya terminado.
    ET.SubElement(
        condition,
        "action",
        attrib={"application": "system", "data": f"mkdir -p $${{recordings_dir}}/{dia}"},
    )
    # `record_session` directo, NO vía execute_on_answer: en las llamadas
    # SALIENTES el canal ya viene contestado cuando entra al dialplan, así
    # que ese disparador no llegaba a ejecutarse nunca y no se generaba
    # ningún archivo (confirmado: el CDR traía la ruta pero el directorio
    # de grabaciones estaba vacío). Graba en segundo plano y no bloquea.
    ET.SubElement(condition, "action", attrib={"application": "record_session", "data": "${nspbx_recording}"})


def _append_call_limits_hook(context: ET.Element, max_minutes: int) -> None:
    """Tope de duración para TODA llamada del contexto — entrante,
    saliente o interna. Va primero, sin condición de "grabar todo" (esa es
    una preferencia de privacidad; esto es protección contra fraude
    telefónico y no depende de ella).

    Sin esto, una extensión comprometida —o simplemente un bug— puede
    dejar una llamada corriendo horas hacia un número caro sin que nadie
    se entere hasta la factura. `execute_on_answer` dispara recién cuando
    el canal contesta de verdad: no cuenta el timbrado.
    """
    if max_minutes <= 0:
        return
    extension = ET.SubElement(context, "extension", attrib={"name": "nspbx_tope_duracion", "continue": "true"})
    condition = ET.SubElement(extension, "condition")
    ET.SubElement(
        condition,
        "action",
        attrib={
            "application": "set",
            "data": f"execute_on_answer=sched_hangup +{max_minutes * 60} alloted_timeout",
        },
    )


def _append_webcall_context(
    section: ET.Element, context_name: str, queue, dominio: str, record_all: bool, max_call_minutes: int
) -> None:
    """Contexto `webcall_<slug>`: el ÚNICO al que llegan las credenciales
    temporales del widget de llamada web de esa empresa (ver
    app/api/webcall.py). Tiene exactamente una ruta válida —`webqueue` → la
    cola configurada— y un catch-all que cuelga todo lo demás. Sin rutas
    salientes, sin códigos de función, sin acceso a extensiones internas:
    aunque se filtre una credencial, no sirve para marcar a ningún lado.

    El nombre lleva el slug de la empresa (no un `webcall` fijo) para que
    activar el widget en una segunda empresa no choque con el de la
    primera — cada una tiene su propio contexto aislado.

    Si no hay cola configurada no se emite el contexto: un registro
    invitado sin dialplan simplemente no puede hacer nada."""
    if queue is None:
        return
    ctx = ET.SubElement(section, "context", attrib={"name": context_name})
    _append_call_limits_hook(ctx, max_call_minutes)

    ext = ET.SubElement(ctx, "extension", attrib={"name": "webcall_queue", "continue": "false"})
    cond = ET.SubElement(ext, "condition", attrib={"field": "destination_number", "expression": "^webqueue$"})
    ET.SubElement(cond, "action", attrib={"application": "answer"})
    if queue.record and not record_all:
        _append_recording_hook_call(cond)
    ET.SubElement(cond, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
    # Dominio literal de la empresa (no $${domain}, variable global que no
    # sirve con varias empresas) — mismo patrón que _append_queue_routes.
    ET.SubElement(cond, "action", attrib={"application": "callcenter", "data": f"{queue.name}@{dominio}"})
    ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    deny = ET.SubElement(ctx, "extension", attrib={"name": "webcall_deny", "continue": "false"})
    dcond = ET.SubElement(deny, "condition", attrib={"field": "destination_number", "expression": "^.*$"})
    ET.SubElement(dcond, "action", attrib={"application": "hangup", "data": "CALL_REJECTED"})


def _append_recording_hook_call(cond: ET.Element) -> None:
    """Graba esta llamada puntual (cola con `record` propio, sin que la
    grabación global ya esté activa) — mismas acciones que
    `_append_recording_hook` pero dentro de una condición existente en vez
    de una extensión nueva."""
    ET.SubElement(cond, "action", attrib={"application": "set", "data": "RECORD_STEREO=false"})
    dia = "${strftime(%Y)}/${strftime(%m)}/${strftime(%d)}"
    ET.SubElement(
        cond,
        "action",
        attrib={"application": "set", "data": f"nspbx_recording=$${{recordings_dir}}/{dia}/llamada_${{uuid}}.wav"},
    )
    ET.SubElement(cond, "action", attrib={"application": "system", "data": f"mkdir -p $${{recordings_dir}}/{dia}"})
    ET.SubElement(cond, "action", attrib={"application": "record_session", "data": "${nspbx_recording}"})


def build_dialplan_xml(
    tenantes: list[dict],
    routes: list | None = None,
    contextos: dict[int, str] | None = None,
    dominios: dict[int, str] | None = None,
    slugs: dict[int, str] | None = None,
) -> str:
    """Genera la seccion <section name='dialplan'> completa.

    Un contexto por empresa (`ctx_<slug>`) con SOLO sus extensiones, bots,
    colas y troncales — es lo que hace que la extensión 1000 de una empresa
    no sea la de otra —, más un contexto `public` único que enruta las
    llamadas entrantes por DID al contexto de la empresa que corresponde.
    """
    contextos = contextos or {}
    dominios = dominios or {}
    slugs = slugs or {}
    root = _e("document", attrib={"type": "freeswitch/xml"})
    section = ET.SubElement(root, "section", attrib={"name": "dialplan"})

    record_public = any(t["record_all"] for t in tenantes)
    max_minutes_public = max((t["max_call_minutes"] for t in tenantes), default=60)

    for t in tenantes:
        contexto = t["contexto"]
        dominio = t["dominio"]
        extensions = t["extensions"]
        bots = t["bots"]
        trunks = t["trunks"]
        queues = t["queues"]
        context = ET.SubElement(section, "context", attrib={"name": contexto})

        _append_call_limits_hook(context, t["max_call_minutes"])
        if t["record_all"]:
            _append_recording_hook(context)
        _append_dnd_feature_codes(context)
        _append_dnd_hook(context, extensions)
        _append_mobile_push_hook(context, extensions, t.get("push_extensions") or set(), slugs.get(t["tenant_id"], ""))
        _append_local_extension_route(context, extensions, dominio)
        _append_voicebot_routes(section, context, bots, dominio, t["tenant_id"])
        _append_queue_routes(context, queues, dominio)

        # Echo test
        echo = ET.SubElement(context, "extension", attrib={"name": "Echo_Test", "continue": "false"})
        c = ET.SubElement(echo, "condition", attrib={"field": "destination_number", "expression": "^9196$"})
        ET.SubElement(c, "action", attrib={"application": "answer"})
        ET.SubElement(c, "action", attrib={"application": "echo"})

        _append_outbound_route(
            context,
            trunks,
            slugs,
            t.get("allow_international", False),
            t.get("max_concurrent", 0),
            slugs.get(t["tenant_id"], t.get("slug", "")),
        )

        webcall_queue = t.get("webcall_queue")
        if webcall_queue is not None:
            slug = slugs.get(t["tenant_id"], t.get("slug", ""))
            _append_webcall_context(
                section, f"webcall_{slug}", webcall_queue, dominio, t["record_all"], t["max_call_minutes"]
            )

    public_context = ET.SubElement(section, "context", attrib={"name": "public"})
    _append_call_limits_hook(public_context, max_minutes_public)
    if record_public:
        _append_recording_hook(public_context)
    _append_inbound_routes(public_context, routes or [], contextos, dominios)

    return validacion.limpiar_xml(ET.tostring(root, encoding="unicode"))
