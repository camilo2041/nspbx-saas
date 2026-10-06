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


async def siguiente_libre(session: AsyncSession, desde: int = 101) -> str:
    """El número de extensión que sigue al mayor de la empresa (101 si no
    hay ninguno), saltando los que ya use una cola."""
    numeros = [int(n) for n in (await session.execute(select(Extension.number))).scalars() if n.isdigit() and len(n) <= 6]
    candidato = max([desde - 1, *numeros]) + 1
    while await numero_en_uso(session, str(candidato)):
        candidato += 1
    return str(candidato)
