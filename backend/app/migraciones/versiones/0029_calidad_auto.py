"""Calidad automática: muestreo nocturno con IA que alguien revisa.

Revisión: 0029_calidad_auto
Anterior: 0028_festivos
"""

from alembic import op

revision = "0029_calidad_auto"
down_revision = "0028_festivos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE evaluaciones_llamada ADD COLUMN IF NOT EXISTS revisada BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS calidad_auto_por_agente INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS calidad_auto_tope INTEGER NOT NULL DEFAULT 20")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS calidad_auto_ultima DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS calidad_auto_ultima")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS calidad_auto_tope")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS calidad_auto_por_agente")
    op.execute("ALTER TABLE evaluaciones_llamada DROP COLUMN IF EXISTS revisada")
