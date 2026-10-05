"""Franja de marcación de las campañas (Ley 2300 de 2023).

Revisión: 0007_horario_campanas
Anterior: 0006_cps_salientes
"""

from alembic import op

revision = "0007_horario_campanas"
down_revision = "0006_cps_salientes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS campaign_hours_weekdays VARCHAR(11) NOT NULL DEFAULT '07:00-19:00'")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS campaign_hours_saturday VARCHAR(11) NOT NULL DEFAULT '08:00-15:00'")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS campaign_sundays_holidays BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    for columna in ("campaign_hours_weekdays", "campaign_hours_saturday", "campaign_sundays_holidays"):
        op.execute(f"ALTER TABLE system_settings DROP COLUMN IF EXISTS {columna}")
