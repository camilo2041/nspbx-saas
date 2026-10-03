"""Escala: escuchas del supervisor en la base (varias réplicas) e índices
para los reportes con volumen.

Revisión: 0017_escala
Anterior: 0016_integraciones
"""

from alembic import op

revision = "0017_escala"
down_revision = "0016_integraciones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoreos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            uuid VARCHAR(64) NOT NULL UNIQUE,
            supervisor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agente_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            modo VARCHAR(12) NOT NULL,
            token VARCHAR(64) NOT NULL,
            contestado BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ux_monitoreos_agente UNIQUE (agente_id),
            CONSTRAINT ux_monitoreos_supervisor UNIQUE (supervisor_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_monitoreos_tenant_id ON monitoreos (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_call_logs_campana_inicio ON call_logs (campaign_id, started_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sesiones_agente_tenant_inicio ON sesiones_agente (tenant_id, inicio)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_estados_agente_tenant_inicio ON estados_agente (tenant_id, inicio)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_estados_agente_tenant_inicio")
    op.execute("DROP INDEX IF EXISTS ix_sesiones_agente_tenant_inicio")
    op.execute("DROP INDEX IF EXISTS ix_call_logs_campana_inicio")
    op.execute("DROP TABLE IF EXISTS monitoreos")
