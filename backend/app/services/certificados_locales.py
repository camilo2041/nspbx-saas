"""Certificado real para instalaciones locales en red local (en la CENTRAL).

Una instalación que se usa solo dentro de la red del cliente no tiene un
dominio propio que Let's Encrypt pueda validar por HTTP. Así se resuelve:

1. Al activarse recibe un subdominio nuestro:
   `<empresa>-<id>.<DOMINIO_LOCAL_SUFIJO>` (ej. clinica-norte-7.local.nspbx…).
2. Su servidor genera SU clave privada y manda solo el CSR y su IP privada.
3. La central crea el A del subdominio → esa IP (en Cloudflare, sin proxy) y
   pide el certificado por DNS-01: el TXT del desafío lo publica la central,
   así que la instalación no necesita abrir ningún puerto.
4. La cadena vuelve a la instalación; la clave nunca salió de allá.
5. La central lo renueva 30 días antes de vencer y la instalación lo recibe
   en su latido. Si su IP cambia, el latido la trae y se corrige el A.

Solo se publican IP privadas (10/8, 172.16/12, 192.168/16): un subdominio
nuestro apuntando a un servidor público sería una puerta para suplantarnos.
"""

import asyncio
import ipaddress
import logging
import re
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models import AcmeCuenta, Instalacion, Tenant
from app.services import acme, dns_cloudflare

logger = logging.getLogger(__name__)

RENOVAR_ANTES = timedelta(days=30)
REVISAR_CADA_S = 12 * 3600
_REDES_PERMITIDAS = [ipaddress.ip_network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
_candados: dict[int, asyncio.Lock] = {}

# Puntos de inyección para las pruebas (tests/test_certificados_locales.py).
fabrica_dns = lambda: dns_cloudflare.Cloudflare(settings.dns_cloudflare_token, settings.dns_cloudflare_zona_id)  # noqa: E731
esperar_propagacion = dns_cloudflare.esperar_txt
verificar_tls_acme: bool | str = True


class ErrorCertificado(Exception):
    """Lo que se le explica a la instalación (o al operador) tal cual."""


def disponible() -> bool:
    return bool(settings.dns_cloudflare_token and settings.dns_cloudflare_zona_id and settings.dominio_local_sufijo)


def subdominio_para(empresa: Tenant, instalacion: Instalacion) -> str:
    etiqueta = re.sub(r"[^a-z0-9-]+", "-", f"{empresa.slug}-{instalacion.id}".lower()).strip("-")[:63].strip("-")
    return f"{etiqueta}.{settings.dominio_local_sufijo.strip('.').lower()}"


def validar_ip(ip: str) -> str:
    try:
        direccion = ipaddress.IPv4Address((ip or "").strip())
    except ValueError:
        raise ErrorCertificado("La IP local no es una dirección IPv4 válida")
    if not any(direccion in red for red in _REDES_PERMITIDAS):
        raise ErrorCertificado("Solo se publican IP de red local (10.x, 172.16-31.x o 192.168.x)")
    return str(direccion)


def validar_csr(csr_pem: str, subdominio: str) -> str:
    try:
        csr = x509.load_pem_x509_csr((csr_pem or "").encode())
    except ValueError:
        raise ErrorCertificado("La solicitud de certificado (CSR) no es válida")
    if not csr.is_signature_valid:
        raise ErrorCertificado("La firma del CSR no corresponde")
    nombres = acme.nombres_del_csr(csr_pem)
    if nombres != [subdominio]:
        raise ErrorCertificado(f"El CSR tiene que pedir solo {subdominio}")
    clave = csr.public_key()
    if isinstance(clave, rsa.RSAPublicKey) and clave.key_size < 2048:
        raise ErrorCertificado("La clave del CSR es demasiado corta (mínimo RSA 2048)")
    if not isinstance(clave, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
        raise ErrorCertificado("Tipo de clave no admitido: usa RSA 2048+ o EC P-256")
    return csr_pem.strip() + "\n"


async def _cuenta(session) -> AcmeCuenta:
    fila = await session.get(AcmeCuenta, 1)
    if fila is None or fila.directorio != settings.acme_directorio:
        if fila is None:
            fila = AcmeCuenta(id=1, clave=acme.nueva_clave_cuenta())
            session.add(fila)
        fila.kid, fila.directorio = None, settings.acme_directorio
        await session.commit()
    return fila


async def emitir(session, inst: Instalacion, csr_pem: str | None = None, ip: str | None = None) -> str:
    """Saca (o renueva) el certificado de `inst`. Devuelve la cadena PEM."""
    if not disponible():
        raise ErrorCertificado("Esta central no tiene configurado el DNS para instalaciones en red local")
    if not inst.subdominio:
        raise ErrorCertificado("La instalación no tiene subdominio asignado")
    csr_pem = validar_csr(csr_pem or inst.csr or "", inst.subdominio)
    ip = validar_ip(ip or inst.ip_local or "")
    candado = _candados.setdefault(inst.id, asyncio.Lock())
    async with candado:
        dns = fabrica_dns()
        try:
            await dns.fijar_a(inst.subdominio, ip)
            cuenta = await _cuenta(session)
            async with acme.ClienteAcme(settings.acme_directorio, cuenta.clave, settings.acme_correo,
                                        verify=verificar_tls_acme) as cliente:
                cliente.kid = cuenta.kid
                if not cliente.kid:
                    cuenta.kid = await cliente.cuenta()
                    await session.commit()
                cadena = await cliente.certificado(csr_pem, dns.publicar_txt, dns.quitar_txt, esperar_propagacion)
        except (acme.ErrorAcme, dns_cloudflare.ErrorDns) as exc:
            inst.cert_error = str(exc)[:300]
            await session.commit()
            logger.error("Certificado de %s: %s", inst.subdominio, exc)
            raise ErrorCertificado(f"No se pudo emitir el certificado: {exc}")
        finally:
            await dns.cerrar()
    inst.csr, inst.ip_local = csr_pem, ip
    inst.certificado, inst.cert_vence, inst.cert_error = cadena, acme.vence(cadena), None
    await session.commit()
    logger.warning("Certificado de %s emitido (vence %s)", inst.subdominio, inst.cert_vence)
    return cadena


async def actualizar_ip(session, inst: Instalacion, ip: str | None) -> None:
    """El latido trajo otra IP: se corrige el A. Sin efecto si no cambió."""
    if not ip or not disponible() or not inst.subdominio or not inst.certificado:
        return
    try:
        ip = validar_ip(ip)
    except ErrorCertificado:
        return
    if ip == inst.ip_local:
        return
    dns = fabrica_dns()
    try:
        await dns.fijar_a(inst.subdominio, ip)
        inst.ip_local = ip
        await session.commit()
        logger.warning("%s ahora apunta a %s", inst.subdominio, ip)
    except dns_cloudflare.ErrorDns as exc:
        logger.error("No se pudo actualizar el A de %s: %s", inst.subdominio, exc)
    finally:
        await dns.cerrar()


async def retirar(inst: Instalacion) -> None:
    """Instalación revocada o borrada: su nombre deja de resolver."""
    if not disponible() or not inst.subdominio:
        return
    dns = fabrica_dns()
    try:
        await dns.borrar_a(inst.subdominio)
    except dns_cloudflare.ErrorDns as exc:
        logger.error("No se pudo borrar el A de %s: %s", inst.subdominio, exc)
    finally:
        await dns.cerrar()


async def renovar_pendientes() -> int:
    """Renueva los que vencen en menos de 30 días. Devuelve cuántos."""
    if not disponible():
        return 0
    limite = datetime.utcnow() + RENOVAR_ANTES
    async with async_session() as session:
        pendientes = (
            await session.execute(
                select(Instalacion).where(Instalacion.estado == "activa", Instalacion.certificado.is_not(None),
                                          Instalacion.cert_vence < limite)
            )
        ).scalars().all()
        hechos = 0
        for inst in pendientes:
            try:
                await emitir(session, inst)
                hechos += 1
            except ErrorCertificado as exc:
                logger.error("Renovación de %s: %s", inst.subdominio, exc)
        return hechos


class Renovador:
    """Revisa cada 12 h (solo el líder, solo en la central con DNS configurado)."""

    def __init__(self):
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if disponible() and settings.modo_instalacion != "local" and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            try:
                await renovar_pendientes()
            except Exception:
                logger.exception("Error renovando certificados de instalaciones locales")
            await asyncio.sleep(REVISAR_CADA_S)


renovador = Renovador()
