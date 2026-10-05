"""Integraciones y reportes: webhooks firmados, su bitácora, URL del CRM por
campaña y reportes programados por correo.

Revisión: 0016_integraciones
Anterior: 0015_supervision
"""

from alembic import op

revision = "0016_integraciones"
down_revision = "0015_supervision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS crm_url TEXT")
    op.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS crm_secreto TEXT")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webhooks (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(80) NOT NULL,
            url VARCHAR(500) NOT NULL,
            secreto TEXT NOT NULL,
            eventos JSON,
            activo BOOLEAN NOT NULL DEFAULT true,
            fallos_seguidos INTEGER NOT NULL DEFAULT 0,
            ultimo_ok_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhooks_tenant_id ON webhooks (tenant_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS entregas_webhook (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            evento VARCHAR(40) NOT NULL,
            payload TEXT NOT NULL,
            estado VARCHAR(12) NOT NULL,
            intentos INTEGER NOT NULL DEFAULT 0,
            proximo_intento_at TIMESTAMP WITHOUT TIME ZONE,
            ultimo_codigo INTEGER,
            ultimo_error TEXT,
            entregado_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    for col in ("tenant_id", "webhook_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_entregas_webhook_{col} ON entregas_webhook ({col})")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entregas_webhook_cola ON entregas_webhook (estado, proximo_intento_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reportes_programados (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(80) NOT NULL,
            tipo VARCHAR(20) NOT NULL,
            frecuencia VARCHAR(10) NOT NULL,
            hora INTEGER NOT NULL DEFAULT 7,
            destinatarios TEXT NOT NULL,
            filtros JSON,
            activo BOOLEAN NOT NULL DEFAULT true,
            ultimo_envio_at TIMESTAMP WITHOUT TIME ZONE,
            ultimo_intento_at TIMESTAMP WITHOUT TIME ZONE,
            ultimo_periodo VARCHAR(30),
            ultimo_error TEXT,
            creado_por INTEGER,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_reportes_programados_tenant_id ON reportes_programados (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reportes_programados")
    op.execute("DROP TABLE IF EXISTS entregas_webhook")
    op.execute("DROP TABLE IF EXISTS webhooks")
    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS crm_secreto")
    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS crm_url")
