"""Reporte de entrantes: de qué grupo de atención fue cada llamada, cuánto
esperó y cómo terminó (atendida, abandonada o desbordada).

Revisión: 0022_entrantes
Anterior: 0021_transferencias
"""

from alembic import op

revision = "0022_entrantes"
down_revision = "0021_transferencias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS cola VARCHAR(100)")
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS cola_espera_s INTEGER")
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS cola_resultado VARCHAR(12)")
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS cola_agente VARCHAR(20)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_call_logs_cola_inicio ON call_logs (cola, started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_call_logs_cola_inicio")
    for col in ("cola_agente", "cola_resultado", "cola_espera_s", "cola"):
        op.execute(f"ALTER TABLE call_logs DROP COLUMN IF EXISTS {col}")
