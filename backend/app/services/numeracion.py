"""Números internos de una empresa: extensiones y colas comparten el mismo
plan de marcado (el contexto ctx_<slug>), así que no pueden repetirse.

En el dialplan la extensión se evalúa antes que la cola: una cola con el
número de una extensión existente quedaba inalcanzable sin ningún error
visible (las llamadas a ese número le timbraban a la extensión).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Extension, Queue


async def numero_en_uso(
    session: AsyncSession, numero: str, *, salvo_extension: int | None = None, salvo_cola: int | None = None
) -> str | None:
    """Qué usa ya ese número en la empresa de la sesión (texto para el
    usuario), o None si está libre."""
    consulta = select(Extension.number).where(Extension.number == numero)
    if salvo_extension is not None:
        consulta = consulta.where(Extension.id != salvo_extension)
    if (await session.execute(consulta.limit(1))).first():
        return f"la extensión {numero}"
    consulta = select(Queue.name).where(Queue.extension == numero)
    if salvo_cola is not None:
        consulta = consulta.where(Queue.id != salvo_cola)
    fila = (await session.execute(consulta.limit(1))).first()
    if fila:
        return f"la cola «{fila[0]}»"
    return None
