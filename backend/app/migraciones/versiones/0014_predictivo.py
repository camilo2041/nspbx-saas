"""Predictivo: nivel de marcación, abandono y métricas del día por campaña.

Revisión: 0014_predictivo
Anterior: 0013_agentes
"""

from alembic import op

revision = "0014_predictivo"
down_revision = "0013_agentes"
branch_labels = None
depends_on = None

_CAMPANA = (
    ("nivel_marcacion", "DOUBLE PRECISION NOT NULL DEFAULT 1.0"),
    ("nivel_max", "DOUBLE PRECISION NOT NULL DEFAULT 3.0"),
    ("nivel_actual", "DOUBLE PRECISION"),
    ("abandono_objetivo", "DOUBLE PRECISION NOT NULL DEFAULT 3.0"),
    ("temporizador_abandono", "INTEGER NOT NULL DEFAULT 2"),
    ("mensaje_abandono", "TEXT"),
    ("audio_abandono", "VARCHAR(255)"),
)


def upgrade() -> None:
    for col, tipo in _CAMPANA:
        op.execute(f"ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS {col} {tipo}")
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS abandonada BOOLEAN")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metricas_campana (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            fecha DATE NOT NULL,
            intentos INTEGER NOT NULL DEFAULT 0,
            contestadas INTEGER NOT NULL DEFAULT 0,
            asignadas INTEGER NOT NULL DEFAULT 0,
            abandonadas INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ux_metricas_campana_dia UNIQUE (campaign_id, fecha)
        )
        """
    )
    for col in ("tenant_id", "campaign_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_metricas_campana_{col} ON metricas_campana ({col})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metricas_campana")
    op.execute("ALTER TABLE call_logs DROP COLUMN IF EXISTS abandonada")
    for col, _ in _CAMPANA:
        op.execute(f"ALTER TABLE campaigns DROP COLUMN IF EXISTS {col}")
