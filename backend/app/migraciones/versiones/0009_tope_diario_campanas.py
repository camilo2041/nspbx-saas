"""Topes diarios por campaña (llamadas y minutos) y contador del marcador.

Revisión: 0009_tope_diario_campanas
Anterior: 0008_salientes_en_horario
"""

from alembic import op

revision = "0009_tope_diario_campanas"
down_revision = "0008_salientes_en_horario"
branch_labels = None
depends_on = None

_COLUMNAS = [
    ("max_calls_per_day", "INTEGER"),
    ("max_minutes_per_day", "INTEGER"),
    ("calls_today", "INTEGER NOT NULL DEFAULT 0"),
    ("calls_today_date", "DATE"),
]


def upgrade() -> None:
    for columna, tipo in _COLUMNAS:
        op.execute(f"ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS {columna} {tipo}")


def downgrade() -> None:
    for columna, _ in _COLUMNAS:
        op.execute(f"ALTER TABLE campaigns DROP COLUMN IF EXISTS {columna}")
