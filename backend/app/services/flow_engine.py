import json
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.config import settings

# Ruta que ve FreeSWITCH para los audios de bots.
FS_SOUNDS_BOTS = "/usr/share/freeswitch/sounds/bots"
# "¿Aló?" que se reproduce al contestar, antes del saludo con el menú.
SALUDO_INICIAL = Path(settings.fs_sounds_dir) / "bots" / "saludo_inicial.wav"

VALID_DIGITS = set("0123456789*#")


def parse_flow(flow_json: str | None) -> dict | None:
    if not flow_json:
        return None
    try:
        data = json.loads(flow_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        return None
    return {"nodes": nodes, "edges": edges}


def legacy_flow_from_bot(bot) -> dict:
    """Convierte el menú simple viejo (bot.config = {"menu": {...}} +
    welcome_message/greeting_audio_path) a nodos/edges del editor visual,
    para que un bot creado antes del editor de flujo se pueda ver y seguir
    editando ahí en vez de aparecer vacío."""
    nodes = [
        {
            "id": "start",
            "type": "menu",
            "position": {"x": 80, "y": 200},
            "data": {
                "label": "Saludo",
                "start": True,
                "audio_path": bot.greeting_audio_path,
                "tts_text": None if bot.greeting_audio_path else bot.welcome_message,
            },
        }
    ]
    edges = []
    menu: dict[str, str] = {}
    if bot.config:
        try:
            data = json.loads(bot.config)
            raw_menu = data.get("menu") if isinstance(data, dict) else None
            if isinstance(raw_menu, dict):
                menu = {str(k).strip(): str(v).strip() for k, v in raw_menu.items()}
        except (ValueError, TypeError):
            pass
    for i, (digit, target) in enumerate(menu.items()):
        node_id = f"legacy_{digit}"
        nodes.append(
            {
                "id": node_id,
                "type": "transfer",
                "position": {"x": 420, "y": 60 + i * 160},
                "data": {"label": f"Opción {digit}", "extension": target},
            }
        )
        edges.append({"id": f"e_start_{digit}", "source": "start", "target": node_id, "sourceHandle": digit})
    return {"nodes": nodes, "edges": edges}


def _escape_regex_digit(digit: str) -> str:
    return "\\" + digit if digit == "*" else digit


def _start_node(flow: dict) -> dict | None:
    for n in flow["nodes"]:
        if n.get("data", {}).get("start"):
            return n
    return flow["nodes"][0] if flow["nodes"] else None


def _node_audio_action(node: dict) -> ET.Element | None:
    data = node.get("data", {})
    audio_path = data.get("audio_path")
    tts_text = data.get("tts_text")
    if audio_path:
        return ET.Element("action", attrib={"application": "playback", "data": audio_path})
    if tts_text:
        return ET.Element("action", attrib={"application": "speak", "data": f"flite|kal|{tts_text}"})
    return None


def build_voicebot_flow_routes(
    section: ET.Element, context: ET.Element, bot, dominio: str, tenant_id: int
) -> bool:
    """Genera el dialplan a partir de un flujo visual (nodos + conexiones,
    estilo n8n) guardado en bot.flow_json. Devuelve False si el bot no tiene
    un flujo válido (para que el llamador use el generador simple legado).

    Cada nodo tipo "menu" se traduce en DOS contextos FreeSWITCH propios:
    uno que reproduce su audio y lee el dígito, y otro (separado) que
    enruta ese dígito ya capturado hacia el siguiente nodo — la misma
    técnica de `transfer` a un contexto nuevo que usa el resto del sistema,
    necesaria porque FreeSWITCH evalúa las <condition> de una extension al
    momento de enrutar, no en vivo después de `read`.

    `dominio` es el de la EMPRESA a la que pertenece el bot (con él se
    arma el bridge hacia sus extensiones) y `tenant_id` viaja como variable
    de canal para que el motor de IA sepa de qué empresa es la llamada
    cuando FreeSWITCH le entrega el control.
    """
    flow = parse_flow(bot.flow_json)
    if not flow:
        return False
    nodes_by_id = {str(n["id"]): n for n in flow["nodes"]}
    start = _start_node(flow)
    if not start:
        return False

    # Una llamada de CAMPAÑA (ver workers/dialer.py) llega con la gestión
    # ya decidida ANTES de marcar — `nspbx_ai_intent` viene seteado desde
    # el originate. A quien contesta no tiene sentido pedirle que marque
    # una opción de menú que nunca vio: se salta el menú entero y se
    # entrega la llamada directo al motor de IA, igual que haría un nodo
    # de "transferencia" a ai_agent dentro del flujo (ver
    # _append_target_actions más abajo) pero sin el paso intermedio del
    # menú. Esta extensión va ANTES que la del menú normal a propósito:
    # FreeSWITCH evalúa las <extension> en orden y se queda con la
    # primera que matchea todas sus <condition>.
    directo_ext = ET.SubElement(
        context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}_campana", "continue": "false"}
    )
    ET.SubElement(directo_ext, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
    directo_cond = ET.SubElement(
        directo_ext, "condition", attrib={"field": "${nspbx_ai_intent}", "expression": "."}
    )
    ET.SubElement(directo_cond, "action", attrib={"application": "set", "data": f"nspbx_tenant_id={tenant_id}"})
    ET.SubElement(directo_cond, "action", attrib={"application": "answer"})
    ET.SubElement(
        directo_cond, "action", attrib={"application": "socket", "data": f"{settings.voicebot_esl_socket} async full"}
    )
    ET.SubElement(directo_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    entry_ext = ET.SubElement(context, "extension", attrib={"name": f"bot_{bot.id}_{bot.name}", "continue": "false"})
    entry_cond = ET.SubElement(entry_ext, "condition", attrib={"field": "destination_number", "expression": f"^bot_{bot.id}$"})
    ET.SubElement(entry_cond, "action", attrib={"application": "answer"})
    ET.SubElement(entry_cond, "action", attrib={"application": "sleep", "data": "300"})
    # Un "¿Aló?" corto antes del saludo largo, y una pausa para que la
    # persona conteste — como en una llamada humana. Sin esto el menú
    # completo arranca en el instante exacto en que descuelgan: pisa el
    # "aló" del que contesta y las primeras palabras se pierden.
    if SALUDO_INICIAL.exists():
        ET.SubElement(
            entry_cond,
            "action",
            attrib={"application": "playback", "data": f"{FS_SOUNDS_BOTS}/{SALUDO_INICIAL.name}"},
        )
        ET.SubElement(entry_cond, "action", attrib={"application": "sleep", "data": "1800"})
    ET.SubElement(entry_cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot.id}_n{start['id']}"})

    for node in flow["nodes"]:
        node_id = str(node["id"])
        node_type = node.get("type", "menu")
        if node_type != "menu":
            continue  # los nodos de transferencia/colgar solo se resuelven como destino de un edge

        outgoing = [e for e in flow["edges"] if str(e.get("source")) == node_id]
        var_name = f"flow_{bot.id}_{node_id}"
        route_context_name = f"bot_{bot.id}_n{node_id}_route"

        enter_context = ET.SubElement(section, "context", attrib={"name": f"bot_{bot.id}_n{node_id}"})
        enter_ext = ET.SubElement(enter_context, "extension", attrib={"name": "enter", "continue": "false"})
        enter_cond = ET.SubElement(enter_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})

        if not outgoing:
            audio_action = _node_audio_action(node)
            if audio_action is not None:
                enter_cond.append(audio_action)
            ET.SubElement(enter_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            continue

        # Nota: se probó pasar el audio directo como prompt de `read` (para
        # evitar perder el dígito en la transición playback→read), pero
        # `read` no reproduce bien un mp3 largo como prompt (aborta en ~1s)
        # y cae al resguardo en inglés — peor que el problema original. Se
        # vuelve a reproducir por separado; sin terminadores en `read`
        # (ver abajo), que sí era una causa real y confirmada de pérdida
        # del dígito.
        audio_action = _node_audio_action(node)
        if audio_action is not None:
            enter_cond.append(audio_action)

        ET.SubElement(enter_cond, "action", attrib={"application": "set", "data": f"{var_name}=x"})
        # `read` demostró (con llamadas reales, 4 pruebas seguidas) no
        # guardar el dígito en la variable aunque el DTMF sí llega —
        # confirmado con un log de diagnóstico justo después. Se reemplaza
        # por `play_and_get_digits`, la aplicación recomendada de
        # FreeSWITCH para menús IVR de un dígito, más robusta que `read`.
        # tries=1 para que la propia app no reintente (nuestro contexto de
        # ruteo ya maneja la opción inválida).
        # Terminador "none" y no "#": con "#" como terminador, y con la
        # expresión anterior (\d|\*) que además no lo aceptaba, una opción
        # configurada en la tecla # era INALCANZABLE — el editor la ofrece
        # (ver VALID_DIGITS) pero el llamante caía siempre en "opción
        # inválida". Como se recoge un solo dígito, no hace falta ningún
        # terminador.
        ET.SubElement(
            enter_cond,
            "action",
            attrib={
                "application": "play_and_get_digits",
                "data": f"1 1 1 7000 none silence_stream://200 silence_stream://200 {var_name} [0-9*#] 5000",
            },
        )
        # El prefijo "opt" NO es decorativo: si nadie marca,
        # play_and_get_digits deja la variable VACÍA (borra incluso el
        # valor puesto con `set` más arriba), y `transfer  XML contexto`
        # con el primer argumento vacío hace que FreeSWITCH corra los
        # argumentos, tome "XML" como destino y muera con
        # NO_ROUTE_DESTINATION. Pasó en una llamada real: la persona no
        # alcanzó a marcar y se le cortó. Con el prefijo el destino nunca
        # es vacío y el caso cae en la extensión de opción inválida.
        ET.SubElement(enter_cond, "action", attrib={"application": "transfer", "data": f"opt${{{var_name}}} XML {route_context_name}"})

        route_context = ET.SubElement(section, "context", attrib={"name": route_context_name})
        for edge in outgoing:
            digit = str(edge.get("sourceHandle", "")).strip()
            if digit not in VALID_DIGITS:
                continue
            target = nodes_by_id.get(str(edge.get("target")))
            if not target:
                continue
            option_ext = ET.SubElement(route_context, "extension", attrib={"name": f"opcion_{digit}", "continue": "false"})
            option_cond = ET.SubElement(option_ext, "condition", attrib={"field": "destination_number", "expression": f"^opt{_escape_regex_digit(digit)}$"})
            _append_target_actions(option_cond, target, bot.id, dominio, tenant_id)

        # Sin marcar nada el destino llega como "opt" pelado; se le da una
        # vuelta más al menú antes de rendirse, que es lo que haría una
        # persona. Solo una: si tampoco marca ahí, cae en la extensión de
        # abajo y se despide.
        reintento_ext = ET.SubElement(route_context, "extension", attrib={"name": "sin_respuesta", "continue": "false"})
        ET.SubElement(reintento_ext, "condition", attrib={"field": "destination_number", "expression": "^opt$"})
        # Segunda condición: que no se haya reintentado ya. Las condiciones
        # de una extension se evalúan en AND, y al fallar una se pasa a la
        # extension siguiente — que es la de "opción inválida". Sin este
        # tope, volver al menú sería un bucle infinito para quien no marca.
        reintento_cond = ET.SubElement(
            reintento_ext, "condition", attrib={"field": f"${{{var_name}_reintento}}", "expression": "^$"}
        )
        ET.SubElement(reintento_cond, "action", attrib={"application": "set", "data": f"{var_name}_reintento=1"})
        ET.SubElement(reintento_cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot.id}_n{node_id}"})

        fallback_ext = ET.SubElement(route_context, "extension", attrib={"name": "opcion_invalida", "continue": "false"})
        fallback_cond = ET.SubElement(fallback_ext, "condition", attrib={"field": "destination_number", "expression": ".*"})
        ET.SubElement(fallback_cond, "action", attrib={"application": "speak", "data": "flite|kal|Opcion invalida. Hasta luego."})
        ET.SubElement(fallback_cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})

    return True


def _append_target_actions(cond: ET.Element, target: dict, bot_id: int, dominio: str, tenant_id: int) -> None:
    data = target.get("data", {})
    ttype = target.get("type", "menu")

    if ttype == "menu":
        ET.SubElement(cond, "action", attrib={"application": "transfer", "data": f"go XML bot_{bot_id}_n{target['id']}"})
        return

    if ttype == "hangup":
        audio_action = _node_audio_action(target)
        if audio_action is not None:
            cond.append(audio_action)
        ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
        return

    if ttype == "transfer":
        extension = str(data.get("extension", "")).strip()
        if not extension:
            ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            return
        if extension == "ai_agent":
            # Qué gestión viene a resolver el bot en esta rama del menú
            # (confirmar / reagendar / cancelar / agendar / cobranza). Se
            # fija como variable del canal ANTES de entregar el control:
            # sin esto el bot no sabía qué tecla marcó la persona y tenía
            # que preguntarle otra vez. Ver app/services/ai_intents.py.
            intent = str(data.get("ai_intent", "") or "").strip().lower()
            if intent:
                ET.SubElement(cond, "action", attrib={"application": "set", "data": f"nspbx_ai_intent={intent}"})
            # La empresa viaja igual: el motor de IA necesita saber de
            # qué tenant es la llamada para leer sus ajustes (API keys)
            # y guardar con tenant_id (ver app/services/ai_agent.py).
            ET.SubElement(cond, "action", attrib={"application": "set", "data": f"nspbx_tenant_id={tenant_id}"})
            # Entrega el control de la llamada al voizbot conversacional
            # (ESL "outbound socket" — ver backend/app/services/ai_agent.py,
            # que corre en el contenedor "voicebot", separado del backend
            # de la API REST). async/full: FreeSWITCH conecta hacia allá y
            # le cede la sesión completa (grabar, reproducir, colgar) hasta
            # que la app "socket" retorna (cuando el voizbot cuelga).
            ET.SubElement(
                cond, "action", attrib={"application": "socket", "data": f"{settings.voicebot_esl_socket} async full"}
            )
            ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
            return
        whisper_audio = data.get("whisper_audio_path")
        whisper_text = data.get("whisper_text")
        if whisper_audio:
            ET.SubElement(cond, "action", attrib={"application": "set", "data": "bridge_pre_execute_bleg_app=playback"})
            ET.SubElement(cond, "action", attrib={"application": "set", "data": f"bridge_pre_execute_bleg_data={whisper_audio}"})
        elif whisper_text:
            ET.SubElement(cond, "action", attrib={"application": "set", "data": "bridge_pre_execute_bleg_app=speak"})
            ET.SubElement(cond, "action", attrib={"application": "set", "data": f"bridge_pre_execute_bleg_data=flite|kal|{whisper_text}"})
        ET.SubElement(cond, "action", attrib={"application": "set", "data": "hangup_after_bridge=true"})
        # El dominio de la EMPRESA (no $${domain}, global): es la etiqueta
        # con la que se registra cada extensión en el directorio, y con
        # varias empresas $${domain} no puede ser el de todas a la vez.
        ET.SubElement(cond, "action", attrib={"application": "bridge", "data": f"user/{extension}@{dominio}"})
        return

    ET.SubElement(cond, "action", attrib={"application": "hangup", "data": "NORMAL_CLEARING"})
