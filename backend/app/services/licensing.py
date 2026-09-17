"""Licenciamiento por empresa: planes, estado y límites.

Cada empresa tiene UNA licencia (tabla `licenses`). Los límites se
enforcean al crear recursos (extensiones, troncales, campañas) y al
originar llamadas; si la licencia está vencida o suspendida, la empresa no
puede operar.

Los planes definen límites por defecto; una licencia puede sobreescribirlos
(campo `custom`). `None` = sin límite.
"""

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_local
from app.models import Campaign, Extension, License, Trunk

logger = logging.getLogger(__name__)

TRIAL_DAYS = 15

# Presets de cada plan: límites por defecto (None = sin límite).
PLANES: dict[str, dict[str, int | None]] = {
    "free": {
        "max_extensions": 5,
        "max_trunks": 1,
        "max_concurrent_calls": 1,
        "max_campaigns": 1,
    },
    "pro": {
        "max_extensions": 25,
        "max_trunks": 5,
        "max_concurrent_calls": 10,
        "max_campaigns": 5,
    },
    "enterprise": {
        "max_extensions": None,
        "max_trunks": None,
        "max_concurrent_calls": None,
        "max_campaigns": None,
    },
}

ETIQUETAS_PLAN = {
    "trial": "Prueba",
    "free": "Gratis",
    "pro": "Pro",
    "enterprise": "Enterprise",
    "custom": "Personalizado",
}

RECURSOS = ("max_extensions", "max_trunks", "max_concurrent_calls", "max_campaigns")


async def obtener(session: AsyncSession, tenant_id: int) -> License:
    """La licencia de la empresa; si no existe, crea una trial de 15 días."""
    lic = (await session.execute(select(License).where(License.tenant_id == tenant_id))).scalars().first()
    if not lic:
        lic = License(
            tenant_id=tenant_id,
            plan="trial",
            status="trial",
            started_at=now_local(),
            expires_at=now_local() + timedelta(days=TRIAL_DAYS),
        )
        session.add(lic)
        await session.commit()
        await session.refresh(lic)
    return lic


def estado(lic: License) -> str:
    """'ok' | 'vencida' | 'suspendida'. El vencimiento se evalúa en caliente."""
    if lic.status == "suspended":
        return "suspendida"
    if lic.expires_at and lic.expires_at < now_local():
        return "vencida"
    return "ok"


def limite(lic: License, recurso: str) -> int | None:
    """Límite efectivo de un recurso: el sobreescrito de la licencia o el
    del plan. `None` = sin límite."""
    valor = getattr(lic, recurso, None)
    if valor is not None:
        return valor
    return PLANES.get(lic.plan, {}).get(recurso)


async def hay_cupo(session: AsyncSession, lic: License, recurso: str, actual: int) -> bool:
    tope = limite(lic, recurso)
    if tope is None:
        return True
    return actual < tope


async def contar_extensiones(session: AsyncSession, tenant_id: int) -> int:
    return (await session.execute(select(func.count(Extension.id)).where(Extension.tenant_id == tenant_id))).scalar() or 0


async def contar_troncales(session: AsyncSession, tenant_id: int) -> int:
    return (await session.execute(select(func.count(Trunk.id)).where(Trunk.tenant_id == tenant_id))).scalar() or 0


async def contar_campanas(session: AsyncSession, tenant_id: int) -> int:
    return (await session.execute(select(func.count(Campaign.id)).where(Campaign.tenant_id == tenant_id))).scalar() or 0


async def tope_concurrentes(session: AsyncSession, tenant_id: int, tope_configurado: int) -> int:
    """El tope de llamadas concurrentes EFECTIVO: el menor entre el que el
    admin configuró en Ajustes y el que permite la licencia."""
    lic = await obtener(session, tenant_id)
    tope_licencia = limite(lic, "max_concurrent_calls")
    if tope_licencia is None:
        return tope_configurado
    return min(tope_configurado, tope_licencia)
