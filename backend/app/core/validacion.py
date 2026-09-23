"""Formatos permitidos para todo dato que termina dentro de un comando de
FreeSWITCH (ESL), de un archivo XML de configuración o de una ruta de
archivo.

Existe porque esos tres destinos interpretan caracteres que en un
formulario parecen inocentes: un salto de línea doble en un comando ESL
es OTRO comando (`api system ...` ejecuta código en el servidor), una
comilla en un atributo XML puede agregar parámetros al gateway, y `../`
en un nombre de archivo escribe fuera de la carpeta. La regla es
permitir solo lo que el dato legítimo necesita, en vez de intentar
prohibir lo peligroso — la lista de lo peligroso siempre se queda corta.
"""

import re

# Número marcable: dígitos y los símbolos de teclado telefónico.
TELEFONO_RE = re.compile(r"^[0-9+*#]{1,30}$")
# Número de extensión interna.
EXTENSION_RE = re.compile(r"^[0-9]{1,20}$")
# Nombre técnico (troncal, cola): forma parte de nombres de archivo, de
# comandos de consola y de atributos XML.
NOMBRE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
# Host o dominio SIP.
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
# Lista de códecs: "PCMU,PCMA,G729".
CODECS_RE = re.compile(r"^[A-Za-z0-9_,.-]{1,255}$")
# Nombre a mostrar (caller ID): texto legible sin caracteres de control ni
# los que rompen comillas/XML/ESL.
NOMBRE_VISIBLE_RE = re.compile(r"^[^\x00-\x1f\x7f\ud800-\udfff\ufffe\uffff'\"<>&{}|\\]{1,100}$")

PATRON_TELEFONO = TELEFONO_RE.pattern
PATRON_EXTENSION = EXTENSION_RE.pattern
PATRON_NOMBRE = NOMBRE_RE.pattern
PATRON_HOST = HOST_RE.pattern
PATRON_CODECS = CODECS_RE.pattern
PATRON_NOMBRE_VISIBLE = NOMBRE_VISIBLE_RE.pattern


def exigir(regex: re.Pattern, valor: str, que: str) -> str:
    """Devuelve `valor` si coincide con `regex`; si no, ValueError.

    Para los servicios (esl.py, gateways.py), que no pasan por pydantic:
    es la última barrera si algún camino nuevo llegara sin validar."""
    if not isinstance(valor, str) or not regex.fullmatch(valor):
        raise ValueError(f"{que} con formato no permitido")
    return valor


def limpiar_nombre_visible(valor: str | None, respaldo: str = "NSPBX") -> str:
    """Nombre a mostrar apto para un comando ESL: se descartan los
    caracteres que no puede haber en él, en vez de rechazar la llamada
    (el nombre es decorativo; la llamada no debe fallar por él)."""
    limpio = re.sub(r"[\x00-\x1f\x7f'\"<>&{}|\\]", "", valor or "").strip()
    return limpio[:100] or respaldo


# Destino de un `transfer`/ruta: una extensión, una cola (número) o `bot_N`.
# Sin espacios: "1000 XML ctx_otra" en un destino transfiere al contexto de
# OTRA empresa, porque el dialplan lee el texto como "<destino> XML <contexto>".
DESTINO_RE = re.compile(r"^[A-Za-z0-9_.*#+-]{1,50}$")
# Un DID exacto. El comodín "any" se trata aparte.
DID_RE = TELEFONO_RE
BOT_RE = re.compile(r"^bot_[0-9]{1,10}$")


def destino_valido(tipo: str, valor: str | None) -> bool:
    """¿El destino de una ruta entrante es coherente con su tipo?"""
    if tipo == "hangup":
        return True
    if not valor:
        return False
    if tipo == "extension":
        return bool(EXTENSION_RE.fullmatch(valor))
    if tipo == "queue":
        return bool(TELEFONO_RE.fullmatch(valor))
    if tipo == "voicebot":
        return bool(BOT_RE.fullmatch(valor))
    return False


# --- Patrones de marcado (rutas salientes) ------------------------------
# Notación de FreePBX/Issabel, no regex. Ver el modelo OutboundRoute para
# el porqué: un regex mal escrito acá no falla de forma visible, abre un
# destino caro y se descubre en la factura.
#
#   X  0-9      Z  1-9      N  2-9      .  uno o más caracteres
#   [1-5] rango       dígitos, + * # literales
#
# El filtro es deliberadamente cerrado: lo que salga de acá se inserta en
# el dialplan, donde una expresión inesperada cambia a qué troncal sale
# una llamada.
PATRON_MARCADO_RE = re.compile(r"^(?:[0-9+*#XZN.]|\[[0-9]-[0-9]\]){1,40}$")

_CLASE_POR_LETRA = {"X": "[0-9]", "Z": "[1-9]", "N": "[2-9]"}


def patron_marcado_a_regex(patron: str, quitar: int = 0) -> str:
    """Traduce un patrón de marcado a la expresión que usa FreeSWITCH.

    Devuelve la expresión anclada con UN grupo de captura. `quitar` deja
    ese grupo empezando después de los primeros N símbolos del patrón,
    que es como se descartan dígitos de marcado (el 0 de "03001234567"):
    así el dialplan marca `$1` y ya sale normalizado, sin tener que
    recortar la cadena en tiempo de llamada.

    Lanza ValueError si el patrón no pasa el filtro: preferimos romper al
    guardar, donde alguien lo ve, que generar una ruta que se come
    llamadas en silencio.
    """
    if not PATRON_MARCADO_RE.fullmatch(patron or ""):
        raise ValueError(
            "Patrón inválido. Se permiten dígitos, + * #, las letras X (0-9), "
            "Z (1-9), N (2-9), el punto (uno o más) y rangos como [1-5]."
        )
    partes: list[str] = []
    i = 0
    while i < len(patron):
        c = patron[i]
        if c == "[":
            fin = patron.index("]", i)
            partes.append(patron[i : fin + 1])
            i = fin + 1
            continue
        if c in _CLASE_POR_LETRA:
            partes.append(_CLASE_POR_LETRA[c])
        elif c == ".":
            partes.append(".+")
        else:
            partes.append(re.escape(c))
        i += 1
    if quitar < 0 or quitar >= len(partes):
        raise ValueError(
            f"No se pueden quitar {quitar} dígitos de un patrón de {len(partes)}: "
            "no quedaría nada que marcar."
        )
    return "^" + "".join(partes[:quitar]) + "(" + "".join(partes[quitar:]) + ")$"


# --- Flujos del voizbot -------------------------------------------------
# Todo lo que un flujo (flow_json) o un saludo mete en el dialplan pasa por
# estos filtros. El motivo es concreto: FreeSWITCH expande `${...}` DENTRO de
# los datos de cada acción al momento de la llamada, y `${system(cmd)}` o
# `${api_comando(...)}` ejecuta código. Escapar el XML no lo evita (eso solo
# impide romper el documento): el texto llega intacto al motor. Por eso los
# textos hablados solo pueden llevar letras, números y puntuación simple; no
# `$`, `{`, `}`, comillas ni barras invertidas.

# Ids de nodo: entran en nombres de contexto y variables de canal.
NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# Audios de bots: solo archivos sueltos dentro de la carpeta de sonidos de bots.
RUTA_AUDIO_RE = re.compile(r"^/usr/share/freeswitch/sounds/bots/[A-Za-z0-9_.-]{1,120}$")

# Lo único que puede llevar un texto hablado (unicode: acentos y ñ incluidos).
_NO_PERMITIDO_EN_TEXTO = re.compile(r"[^\w\s.,;:!?¿¡()\-%/+]")


def ruta_audio_segura(ruta: str | None) -> str | None:
    """La ruta si es un archivo de la carpeta de audios de bots; si no, None."""
    if isinstance(ruta, str) and RUTA_AUDIO_RE.fullmatch(ruta) and ".." not in ruta:
        return ruta
    return None


def texto_hablado(valor: str | None, maximo: int = 500) -> str:
    """Texto listo para `speak`/flite: sin caracteres que FreeSWITCH interprete.

    Se descartan (no se rechazan) porque el texto solo alimenta el respaldo de
    voz sintética; la llamada no debe fallar por un símbolo. El audio de buena
    calidad se genera aparte, con el texto original, y no pasa por acá."""
    limpio = _NO_PERMITIDO_EN_TEXTO.sub("", str(valor or ""))
    return re.sub(r"\s+", " ", limpio).strip()[:maximo]


# XML 1.0 solo admite algunos caracteres. Uno fuera de rango (por ejemplo
# U+FFFE o un byte de control) hace que libxml2 rechace el DOCUMENTO ENTERO:
# /fs/dialplan y /fs/directory sirven a TODAS las empresas, así que un solo
# nombre con ese carácter dejaba sin llamadas a todas. Se quitan al serializar.
_XML_ILEGAL = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def limpiar_xml(texto: str) -> str:
    return _XML_ILEGAL.sub("", texto)


def id_nodo_valido(valor) -> bool:
    return bool(NODE_ID_RE.fullmatch(str(valor)))


# Música en espera de una cola: la de fábrica, un stream local por nombre o un
# archivo dentro de la carpeta de sonidos. Nada de URL ni de `${...}`.
MOH_POR_DEFECTO = "$${hold_music}"
_MOH_RE = re.compile(r"^(local_stream://[A-Za-z0-9_.-]{1,60}|/usr/share/freeswitch/sounds/[A-Za-z0-9_./-]{1,150})$")


def moh_valido(valor: str | None) -> bool:
    if valor == MOH_POR_DEFECTO:
        return True
    return bool(isinstance(valor, str) and _MOH_RE.fullmatch(valor) and ".." not in valor)
