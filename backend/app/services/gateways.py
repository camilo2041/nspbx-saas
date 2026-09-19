import html
import logging
import os
from pathlib import Path

from app.core import validacion
from app.core.config import settings

logger = logging.getLogger(__name__)

GATEWAYS_DIR = "sip_profiles/external"


def _gateways_path() -> Path:
    return Path(settings.fs_conf_dir) / GATEWAYS_DIR


def ensure_dirs():
    _gateways_path().mkdir(parents=True, exist_ok=True)


def nombre_gateway(nombre: str, slug: str) -> str:
    """El nombre REAL del gateway en FreeSWITCH.

    En sofia los nombres de gateway son GLOBALES al perfil external: dos
    empresas con una troncal llamada "principal" pisarían el archivo y el
    registro del otro. El slug de la empresa va como prefijo
    (`empresa2_principal`) para que cada una tenga el suyo sin chocar.
    """
    return f"{slug}_{nombre}"


def _attr(valor) -> str:
    """Valor listo para ir dentro de un atributo XML entre comillas.

    Sin esto, una comilla en la contraseña o el usuario cierra el atributo
    y el resto del texto pasa a ser XML propio: se pueden agregar
    parámetros al gateway (por ejemplo cambiar su `context` al de otra
    empresa). Escapar es lo correcto para contraseñas, que pueden llevar
    cualquier símbolo; el resto de los campos además se restringen abajo.
    """
    return html.escape(str(valor), quote=True)


def _ruta_segura(gw_name: str) -> Path:
    """Ruta del archivo del gateway, garantizando que queda DENTRO de la
    carpeta de gateways: un nombre con `../` escribiría o borraría
    archivos en cualquier parte del volumen de configuración."""
    validacion.exigir(validacion.NOMBRE_RE, gw_name, "Nombre de gateway")
    base = _gateways_path().resolve()
    path = (base / f"gw_{gw_name}.xml").resolve()
    if path.parent != base:
        raise ValueError("Ruta de gateway fuera de la carpeta permitida")
    return path


def write_gateway_file(trunk, slug: str) -> Path:
    """Escribe/actualiza el gateway de una troncal en la config de FreeSWITCH."""
    ensure_dirs()
    validacion.exigir(validacion.NOMBRE_RE, slug, "Identificador de empresa")
    validacion.exigir(validacion.NOMBRE_RE, trunk.name, "Nombre de troncal")
    validacion.exigir(validacion.HOST_RE, trunk.gateway_host, "Host de la troncal")
    if trunk.from_domain:
        validacion.exigir(validacion.HOST_RE, trunk.from_domain, "Dominio de origen")
    if getattr(trunk, "codec_prefs", None):
        validacion.exigir(validacion.CODECS_RE, trunk.codec_prefs, "Códecs")
    gw_name = nombre_gateway(trunk.name, slug)
    path = _ruta_segura(gw_name)

    has_credentials = bool(trunk.username and trunk.password)
    # Solo se registra si hay credenciales Y la troncal lo tiene habilitado.
    # Una troncal sin usuario/password es "IP-authenticated": FreeSWITCH no
    # debe intentar REGISTER (con credenciales vacías fallaría en bucle).
    should_register = has_credentials and getattr(trunk, "register_enabled", True)

    proxy = f"{trunk.gateway_host}:{trunk.gateway_port}"
    transport = getattr(trunk, "transport", "udp") or "udp"
    if transport != "udp":
        proxy += f";transport={transport}"

    lines = [
        '<include>',
        f'  <gateway name="{_attr(gw_name)}">',
        f'    <param name="proxy" value="{_attr(proxy)}"/>',
    ]
    if trunk.username:
        lines.append(f'    <param name="username" value="{_attr(trunk.username)}"/>')
    if trunk.password:
        lines.append(f'    <param name="password" value="{_attr(trunk.password)}"/>')
    if trunk.from_domain:
        lines.append(f'    <param name="from-domain" value="{_attr(trunk.from_domain)}"/>')
    lines.append(f'    <param name="register" value="{"true" if should_register else "false"}"/>')
    if transport != "udp":
        lines.append(f'    <param name="register-transport" value="{_attr(transport)}"/>')
    ping = getattr(trunk, "ping", None)
    if ping:
        lines.append(f'    <param name="ping" value="{_attr(ping)}"/>')
    codec_prefs = getattr(trunk, "codec_prefs", None)
    if codec_prefs:
        lines.append(f'    <param name="codec-prefs" value="{_attr(codec_prefs)}"/>')
    lines.append('    <param name="context" value="public"/>')
    lines.append('  </gateway>')
    lines.append('</include>')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Gateway %s escrito en %s (register=%s)", gw_name, path, should_register)
    return path


def remove_gateway_file(gw_name: str):
    ensure_dirs()
    try:
        path = _ruta_segura(gw_name)
    except ValueError:
        logger.warning("Gateway con nombre no permitido, no se elimina: %r", gw_name)
        return
    if path.exists():
        path.unlink()
        logger.info("Gateway %s eliminado", gw_name)


def clean_gateways(valid_names: set[str]):
    """Elimina archivos de gateway que no corresponden a troncales validas."""
    ensure_dirs()
    for f in os.listdir(_gateways_path()):
        if f.startswith("gw_") and f.endswith(".xml"):
            name = f[3:-4]
            if name not in valid_names:
                try:
                    (_gateways_path() / f).unlink()
                    logger.info("Gateway obsoleto eliminado: %s", name)
                except OSError:
                    pass


def sync_gateways(trunks: list, slug_por_tenant: dict[int, str]):
    validos = {nombre_gateway(t.name, slug_por_tenant.get(t.tenant_id, "x")) for t in trunks}
    clean_gateways(validos)
    for trunk in trunks:
        if trunk.enabled:
            # Una troncal guardada antes de existir la validación (ej. con
            # espacios en el nombre) no debe impedir que arranque el sistema
            # ni que se escriban las demás: se omite y queda registrada.
            try:
                write_gateway_file(trunk, slug_por_tenant.get(trunk.tenant_id, "x"))
            except ValueError as exc:
                logger.error("Troncal %s omitida: %s. Corrígela desde el panel.", trunk.id, exc)
