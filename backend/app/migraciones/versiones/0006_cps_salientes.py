"""Tope de llamadas salientes por segundo por empresa (licenses.max_outbound_cps).

Revisión: 0006_cps_salientes
Anterior: 0005_claves_api
"""

from alembic import op

revision = "0006_cps_salientes"
down_revision = "0005_claves_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS max_outbound_cps INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE licenses DROP COLUMN IF EXISTS max_outbound_cps")
