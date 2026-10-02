"""Tiempos separados de cada llamada: setup, ring, espera y quién colgó.

Revisión: 0011_tiempos_llamada
Anterior: 0010_prefijos_bloqueados
"""

from alembic import op

revision = "0011_tiempos_llamada"
down_revision = "0010_prefijos_bloqueados"
branch_labels = None
depends_on = None

_COLUMNAS = (
    ("progress_at", "TIMESTAMP WITHOUT TIME ZONE"),
    ("setup_ms", "INTEGER"),
    ("ring_ms", "INTEGER"),
    ("espera_ms", "INTEGER"),
    ("colgo", "VARCHAR(10)"),
)


def upgrade() -> None:
    for nombre, tipo in _COLUMNAS:
        op.execute(f"ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS {nombre} {tipo}")


def downgrade() -> None:
    for nombre, _ in _COLUMNAS:
        op.execute(f"ALTER TABLE call_logs DROP COLUMN IF EXISTS {nombre}")
