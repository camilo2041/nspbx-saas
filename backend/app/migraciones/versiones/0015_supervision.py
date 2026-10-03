"""Supervisión: tokens de solo lectura para el wallboard.

Revisión: 0015_supervision
Anterior: 0014_predictivo
"""

from alembic import op

revision = "0015_supervision"
down_revision = "0014_predictivo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens_wallboard (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(80) NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            creado_por INTEGER,
            vence TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            revocado_at TIMESTAMP WITHOUT TIME ZONE,
            ultimo_uso_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tokens_wallboard_tenant_id ON tokens_wallboard (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tokens_wallboard")
