"""Destinos internacionales que la plataforma bloquea para todas las empresas.

Revisión: 0010_prefijos_bloqueados
Anterior: 0009_tope_diario_campanas
"""

from alembic import op

revision = "0010_prefijos_bloqueados"
down_revision = "0009_tope_diario_campanas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform_state ADD COLUMN IF NOT EXISTS blocked_prefixes TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE platform_state DROP COLUMN IF EXISTS blocked_prefixes")
