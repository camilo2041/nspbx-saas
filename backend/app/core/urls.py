"""Defensa contra SSRF en URLs que fija una empresa (p. ej. el modelo de IA).

La URL base del modelo la escribe el admin de cada empresa y el SERVIDOR hace
la petición: sin control, apuntarla a http://postgres:5432, a la API interna,
al Event Socket o a los metadatos de la nube (169.254.169.254) convertiría al
backend en un proxy hacia la red interna. Se exige HTTPS y que el destino
resuelva solo a direcciones públicas.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import settings


class UrlNoPermitida(ValueError):
    pass


def _ip_publica(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def validar_url_https(url: str) -> str:
    """Comprobación sintáctica (barata, sin red). Devuelve la URL sin barra final."""
    try:
        p = urlsplit((url or "").strip())
        host = p.hostname
        p.port  # noqa: B018  (lanza si el puerto es inválido)
    except ValueError:
        raise UrlNoPermitida("URL no válida")
    if p.scheme != "https" or not host:
        raise UrlNoPermitida("La URL debe empezar con https://")
    if p.username or p.password:
        raise UrlNoPermitida("La URL no debe llevar usuario ni contraseña")
    if settings.permitir_urls_privadas:
        return url.strip().rstrip("/")
    if host.lower() == "localhost" or host.lower().endswith((".local", ".internal", ".localhost")):
        raise UrlNoPermitida("Ese destino no es público")
    try:
        es_publica = _ip_publica(host)
    except ValueError:
        es_publica = True  # es un nombre, no una IP: se comprueba al resolverlo
    if not es_publica:
        raise UrlNoPermitida("Ese destino no es público")
    return url.strip().rstrip("/")


async def exigir_destino_publico(url: str) -> str:
    """Igual que `validar_url_https` y además resuelve el nombre: todas sus
    direcciones deben ser públicas (cierra el truco de un dominio propio que
    resuelve a 10.x o 127.0.0.1)."""
    limpia = validar_url_https(url)
    if settings.permitir_urls_privadas:
        return limpia
    host = urlsplit(limpia).hostname or ""
    try:
        info = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise UrlNoPermitida("No se pudo resolver el servidor del modelo")
    if not info or not all(_ip_publica(i[4][0]) for i in info):
        raise UrlNoPermitida("Ese destino no es público")
    return limpia
