"""Qué puede tocar una empresa y qué es de TODA la plataforma.

FreeSWITCH, la base de datos, el disco de grabaciones y respaldos, y el
Event Socket son UNO solo para todas las empresas. Un administrador de
empresa que cambiaba esos ajustes (o los veía) afectaba a las demás: repuntar
el Event Socket dejaba a todas sin llamadas, un tope de disco en 0,5 GB
borraba las grabaciones y respaldos de todos, y los logs de FreeSWITCH
mostraban el tráfico de cada cliente.

Regla: esas operaciones solo están disponibles cuando la instalación tiene UNA
empresa (ahí el administrador es, de hecho, el dueño de la plataforma). Con
varias empresas se configuran por variables de entorno y las opera quien
administra el servidor.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import usuario_actual
from app.core.database import get_session
from app.models import Tenant, User


async def instalacion_unica(session: AsyncSession) -> bool:
    """¿Hay una sola empresa activa? `tenants` no está bajo Row-Level Security,
    así que cuenta todas aunque la sesión esté atada a una."""
    n = (await session.execute(select(func.count(Tenant.id)).where(Tenant.enabled.is_(True)))).scalar() or 0
    return n <= 1


async def es_operador_global(usuario: User, session: AsyncSession) -> bool:
    """Plataforma, o administrador de la única empresa de la instalación."""
    if permissions.puede(usuario.role, permissions.EMPRESAS_GESTIONAR):
        return True
    return await instalacion_unica(session)


async def requiere_operador_global(
    usuario: User = Depends(usuario_actual), session: AsyncSession = Depends(get_session)
) -> User:
    if not await es_operador_global(usuario, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta operación afecta a toda la plataforma y no está disponible para una empresa.",
        )
    return usuario
