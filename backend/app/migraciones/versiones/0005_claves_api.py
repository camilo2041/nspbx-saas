"""Claves de la API pública (api_keys).

Revisión: 0005_claves_api
Anterior: 0004_auditoria_sin_fk

IF NOT EXISTS: en una base nueva la 0001 ya creó la tabla desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

from alembic import op

revision = "0005_claves_api"
down_revision = "0004_auditoria_sin_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(80) NOT NULL,
            prefix VARCHAR(16) NOT NULL,
            key_hash VARCHAR(64) NOT NULL,
            scopes VARCHAR(300) NOT NULL,
            created_by VARCHAR(100),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            expires_at TIMESTAMP WITHOUT TIME ZONE,
            revoked_at TIMESTAMP WITHOUT TIME ZONE,
            last_used_at TIMESTAMP WITHOUT TIME ZONE
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_tenant_id ON api_keys (tenant_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_prefix ON api_keys (prefix)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_keys")
