"""Historial de versiones de los voizbots (voicebot_versions).

Revisión: 0003_versiones_voicebot
Anterior: 0002_secretos_cifrados

IF NOT EXISTS: en una base nueva la 0001 ya creó la tabla desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

from alembic import op

revision = "0003_versiones_voicebot"
down_revision = "0002_secretos_cifrados"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS voicebot_versions (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            voicebot_id INTEGER NOT NULL REFERENCES voicebots(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            bot_type VARCHAR(20) NOT NULL,
            welcome_message TEXT,
            config TEXT,
            flow_json TEXT,
            created_by VARCHAR(100),
            reason VARCHAR(60),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_voicebot_versions_tenant_id ON voicebot_versions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_voicebot_versions_voicebot_id ON voicebot_versions (voicebot_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS voicebot_versions")
