"""Conservar una grabación puntual aunque pase la retención (reclamos, auditorías).

Revisión: 0037_conservar_grabacion
Anterior: 0036_calidad_audio
"""

from alembic import op

revision = "0037_conservar_grabacion"
down_revision = "0036_calidad_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS conservar BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX IF NOT EXISTS ix_call_logs_conservar ON call_logs (tenant_id) WHERE conservar")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_call_logs_conservar")
    op.execute("ALTER TABLE call_logs DROP COLUMN IF EXISTS conservar")
