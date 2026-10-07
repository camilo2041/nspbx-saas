"""Errores del panel y de la app, agrupados por firma.

Revisión: 0035_errores_cliente
Anterior: 0034_verificacion_vivo

Los lee Plataforma con la sesión del dueño: sin RLS.
"""

from alembic import op

revision = "0035_errores_cliente"
down_revision = "0034_verificacion_vivo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS errores_cliente (id SERIAL PRIMARY KEY, firma VARCHAR(64) NOT NULL UNIQUE, "
        "origen VARCHAR(10) NOT NULL, mensaje VARCHAR(300) NOT NULL, pila TEXT, ruta VARCHAR(200), version VARCHAR(60), "
        "tenant_id INTEGER, usuario VARCHAR(100), veces INTEGER NOT NULL DEFAULT 1, usuarios INTEGER NOT NULL DEFAULT 1, "
        "primera_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL, ultima_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL, "
        "resuelto BOOLEAN NOT NULL DEFAULT false)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_errores_cliente_ultima_vez ON errores_cliente (ultima_vez)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_errores_cliente_tenant_id ON errores_cliente (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS errores_cliente")
