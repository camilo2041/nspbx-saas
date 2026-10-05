"""Salientes de los teléfonos solo en horario laboral (opcional por empresa).

Revisión: 0008_salientes_en_horario
Anterior: 0007_horario_campanas
"""

from alembic import op

revision = "0008_salientes_en_horario"
down_revision = "0007_horario_campanas"
branch_labels = None
depends_on = None

_COLUMNAS = [
    ("system_settings", "outbound_hours_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("system_settings", "outbound_hours_weekdays", "VARCHAR(11) NOT NULL DEFAULT '07:00-19:00'"),
    ("system_settings", "outbound_hours_saturday", "VARCHAR(11) NOT NULL DEFAULT '08:00-13:00'"),
    ("system_settings", "outbound_hours_sundays_holidays", "BOOLEAN NOT NULL DEFAULT false"),
    ("extensions", "outbound_after_hours", "BOOLEAN NOT NULL DEFAULT false"),
]


def upgrade() -> None:
    for tabla, columna, tipo in _COLUMNAS:
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {tipo}")


def downgrade() -> None:
    for tabla, columna, _ in _COLUMNAS:
        op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {columna}")
