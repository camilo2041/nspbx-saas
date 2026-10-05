"""Varios FreeSWITCH: las empresas se reparten entre servidores (opción A,
docs/escala.md §4).

Revisión: 0018_nodos
Anterior: 0017_escala
"""

from alembic import op

revision = "0018_nodos"
down_revision = "0017_escala"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nodos_freeswitch (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(40) NOT NULL UNIQUE,
            esl_host VARCHAR(255) NOT NULL,
            esl_port INTEGER NOT NULL DEFAULT 8021,
            esl_password TEXT NOT NULL,
            sip_host VARCHAR(255) NOT NULL,
            capacidad_agentes INTEGER NOT NULL DEFAULT 200,
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS nodo_id INTEGER REFERENCES nodos_freeswitch(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_nodo_id ON tenants (nodo_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenants_nodo_id")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS nodo_id")
    op.execute("DROP TABLE IF EXISTS nodos_freeswitch")
