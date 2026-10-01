"""Entorno de Alembic.

En el arranque, main.migrar pasa la conexión abierta (dentro de su
transacción) en `config.attributes["connection"]`. Desde la línea de
comandos (`alembic upgrade head`, `alembic revision`) se conecta con
DATABASE_URL, el rol DUEÑO: el de la aplicación no puede alterar tablas.
"""

import asyncio

from alembic import context

import app.models  # noqa: F401  (registra los modelos en Base.metadata)
from app.core.database import Base

target_metadata = Base.metadata


def _correr(conexion) -> None:
    context.configure(connection=conexion, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


conexion = context.config.attributes.get("connection")
if conexion is not None:
    _correr(conexion)
else:
    from app.core.database import engine

    async def _desde_la_linea_de_comandos() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(_correr)
        await engine.dispose()

    asyncio.run(_desde_la_linea_de_comandos())
