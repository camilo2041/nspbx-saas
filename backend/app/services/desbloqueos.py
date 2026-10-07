"""Desbloquear una IP de fail2ban sin darle a la aplicación el cortafuegos.

El socket de control de fail2ban también permite bloquear, recargar y
reconfigurar (ver services/fail2ban.py), así que no se monta aquí. En su
lugar, Plataforma deja un pedido en `desbloqueos_ip` y un script del host
(scripts/fail2ban-desbloquear.sh, por cron cada minuto) lee los pendientes
con `python -m app.desbloqueos pendientes`, corre únicamente
`fail2ban-client set <jail> unbanip <ip>` y anota el resultado.

Lo peor que puede hacer quien tome el panel es pedir que se desbloquee una
IP que hoy está bloqueada, y solo con el rol de plataforma.
"""

import ipaddress
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DesbloqueoIp
from app.services import fail2ban

JAIL_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
ESTADOS_FINALES = ("hecho", "no_estaba", "error")
# Un pendiente más viejo que esto: el script del host no está corriendo.
SIN_ATENDER = timedelta(minutes=5)


class PedidoInvalido(ValueError):
    pass


def ip_valida(ip: str) -> str:
    try:
        return str(ipaddress.ip_address((ip or "").strip()))
    except ValueError:
        raise PedidoInvalido("Esa no es una dirección IP") from None


async def pedir(session: AsyncSession, jail: str, ip: str, motivo: str | None, quien: str) -> DesbloqueoIp:
    """Solo IP que fail2ban tiene bloqueadas ahora en ese jail."""
    ip = ip_valida(ip)
    if not JAIL_RE.fullmatch(jail or ""):
        raise PedidoInvalido("Ese origen de bloqueo no es válido")
    if not any(b.jail == jail and b.ip == ip for b in fail2ban.bloqueos()):
        raise PedidoInvalido("Esa IP no está bloqueada ahora en ese origen")
    ya = (
        await session.execute(
            select(DesbloqueoIp).where(DesbloqueoIp.jail == jail, DesbloqueoIp.ip == ip, DesbloqueoIp.estado == "pendiente")
        )
    ).scalar_one_or_none()
    if ya is not None:
        return ya
    pedido = DesbloqueoIp(jail=jail, ip=ip, motivo=(motivo or "").strip()[:200] or None, pedido_por=quien[:100],
                          pedido_en=datetime.utcnow(), estado="pendiente")
    session.add(pedido)
    await session.commit()
    await session.refresh(pedido)
    return pedido


async def pendientes(session: AsyncSession) -> list[DesbloqueoIp]:
    return list(
        (await session.execute(
            select(DesbloqueoIp).where(DesbloqueoIp.estado == "pendiente").order_by(DesbloqueoIp.id).limit(50)
        )).scalars()
    )


async def resolver(session: AsyncSession, pedido_id: int, estado: str, detalle: str | None = None) -> bool:
    if estado not in ESTADOS_FINALES:
        raise PedidoInvalido(f"Estado desconocido: {estado}")
    pedido = await session.get(DesbloqueoIp, pedido_id)
    if pedido is None or pedido.estado != "pendiente":
        return False
    pedido.estado = estado
    pedido.detalle = (detalle or "").strip()[:300] or None
    pedido.resuelto_en = datetime.utcnow()
    await session.commit()
    return True


def sin_atender(pedido: DesbloqueoIp, ahora: datetime | None = None) -> bool:
    return pedido.estado == "pendiente" and (ahora or datetime.utcnow()) - pedido.pedido_en > SIN_ATENDER
