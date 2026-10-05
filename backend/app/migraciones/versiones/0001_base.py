"""Esquema base: el que llevaba main.py como lista de parches.

Revisión: 0001_base
Anterior: ninguna

Idempotente a propósito: en una base que ya existía antes de Alembic no
cambia nada y la deja registrada en esta versión; en una base nueva crea
todo. Por eso usa los modelos actuales (create_all) más los parches
congelados, que traen lo que create_all no hace (datos de relleno, índices
parciales, restricciones renombradas).
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.core.database import Base
    from app.main import _PARCHES_BASE

    conexion = op.get_bind()
    Base.metadata.create_all(conexion)
    for sentencia in _PARCHES_BASE:
        conexion.execute(sa.text(sentencia))


def downgrade() -> None:
    raise NotImplementedError(
        "El esquema base no se deshace: para volver atrás, restaurar un respaldo "
        "(scripts/restore.sh)."
    )
