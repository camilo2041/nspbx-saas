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
NOMBRE_VISIBLE_RE = re.compile(r"^[^\x00-\x1f\x7f'\"<>&{}|\\]{1,100}$")

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
