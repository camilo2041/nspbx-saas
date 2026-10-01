"""Comprobaciones de configuración antes de arrancar.

Hay ajustes cuya ausencia no rompe nada visible: el sistema arranca, el
panel funciona y las llamadas salen. Lo que se pierde es una garantía, y
eso no da error — se descubre cuando ya pasó algo:

- Sin DATABASE_URL_APP la aplicación usa el rol dueño de las tablas, que se
  saltea Row-Level Security. Cada consulta que olvide filtrar por empresa
  devuelve datos de todas.
- Sin AUTH_SECRET se firma con una clave efímera: todos quedan
  desconectados en cada reinicio, y la tentación de "arreglarlo" con una
  clave fija copiada de algún lado es justo lo que no hay que hacer.
- Sin FS_XML_SECRET los endpoints que consume FreeSWITCH responden 403 y
  ninguna extensión registra.

En producción eso tiene que ser un arranque fallido con un mensaje claro,
no un aviso en un log que nadie lee. En desarrollo se tolera y se avisa.
"""

import logging
import os

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

# Un HS256 con menos de 32 bytes de clave es atacable por fuerza bruta
# offline a partir de cualquier token capturado.
LARGO_MINIMO_AUTH_SECRET = 32


def problemas_de_configuracion(cfg: Settings | None = None, auth_secret: str | None = None) -> list[str]:
    """Lista lo que falta para operar con las garantías completas.

    Recibe la configuración como parámetro para poder probarla sin tocar
    el entorno del proceso."""
    cfg = cfg or settings
    if auth_secret is None:
        auth_secret = os.getenv("AUTH_SECRET", "")
    auth_secret = auth_secret.strip()

    problemas: list[str] = []
    if not cfg.database_url_app:
        problemas.append(
            "DATABASE_URL_APP no está definida: la aplicación usaría el rol dueño de "
            "las tablas y el aislamiento por empresa (RLS) no se aplicaría."
        )
    elif cfg.database_url_app == cfg.database_url:
        problemas.append(
            "DATABASE_URL_APP es igual a DATABASE_URL: tiene que ser el rol restringido "
            "(nspbx_app), no el dueño, o RLS no se aplica."
        )
    if not auth_secret:
        problemas.append(
            "AUTH_SECRET no está definida: las sesiones se firmarían con una clave "
            "temporal. Generala con: openssl rand -base64 48"
        )
    elif len(auth_secret) < LARGO_MINIMO_AUTH_SECRET:
        problemas.append(
            f"AUTH_SECRET tiene {len(auth_secret)} caracteres; el mínimo es "
            f"{LARGO_MINIMO_AUTH_SECRET}. Generala con: openssl rand -base64 48"
        )
    if not cfg.fs_xml_secret:
        problemas.append(
            "FS_XML_SECRET no está definida: FreeSWITCH no podría pedir el directorio "
            "ni el dialplan."
        )
    return problemas


def exigir_configuracion_segura(cfg: Settings | None = None, auth_secret: str | None = None) -> None:
    """En producción, falla si falta algo; en desarrollo, solo avisa."""
    cfg = cfg or settings
    problemas = problemas_de_configuracion(cfg, auth_secret)
    if not problemas:
        return
    detalle = "\n  - ".join(problemas)
    if cfg.entorno.strip().lower() == "desarrollo":
        logger.warning("Configuración incompleta (tolerada en desarrollo):\n  - %s", detalle)
        return
    raise RuntimeError(
        "El backend no arranca en producción con esta configuración:\n  - "
        f"{detalle}\n"
        "Corregí el .env (scripts/setup.sh genera todos los secretos) o, solo en "
        "un equipo de desarrollo, definí ENTORNO=desarrollo."
    )
