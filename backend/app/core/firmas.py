"""Firmas de un solo propósito para los webhooks que FreeSWITCH llama.

Por qué no usar directamente FS_XML_SECRET en cada URL: ese secreto es la
llave maestra (con él, /fs/directory entrega la contraseña SIP de TODAS las
empresas y /fs/cdr acepta llamadas inventadas). Una URL del dialplan viaja
en el XML que FreeSWITCH carga y aparece en sus logs de depuración — y esos
logs los puede ver un administrador de empresa desde la consola web. Si la
URL llevara la llave maestra, filtrarla equivaldría a entregar las claves de
todas las empresas.

En su lugar, cada URL lleva una firma HMAC derivada del secreto pero atada
a UNA acción concreta (avisar la llamada a UNA extensión de UNA empresa).
Quien la vea en un log solo puede repetir exactamente ese aviso; no puede
leer el directorio, ni falsear CDR, ni calcular la firma de otra extensión
sin conocer el secreto.
"""

import hashlib
import hmac

from app.core.config import settings


def _firmar(mensaje: str) -> str:
    return hmac.new(settings.fs_xml_secret.encode(), mensaje.encode(), hashlib.sha256).hexdigest()


def firma_push(slug: str, extension: str) -> str:
    """Firma del aviso de llamada para `extension` de la empresa `slug`.
    Vacía si no hay secreto configurado (el hook no se genera entonces)."""
    if not settings.fs_xml_secret:
        return ""
    return _firmar(f"push:{slug}:{extension}")


def firma_push_valida(firma: str, slug: str, extension: str) -> bool:
    esperada = firma_push(slug, extension)
    return bool(esperada) and hmac.compare_digest(firma or "", esperada)
