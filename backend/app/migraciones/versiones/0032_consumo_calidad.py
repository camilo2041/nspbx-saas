"""Consumo IA: el gasto de la calidad con IA, aparte de las llamadas del voizbot.

Revisión: 0032_consumo_calidad
Anterior: 0031_intentos_acceso
"""

from alembic import op

revision = "0032_consumo_calidad"
down_revision = "0031_intentos_acceso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS origen VARCHAR(20) NOT NULL DEFAULT 'voizbot'")


def downgrade() -> None:
    op.execute("ALTER TABLE ai_call_usage DROP COLUMN IF EXISTS origen")
