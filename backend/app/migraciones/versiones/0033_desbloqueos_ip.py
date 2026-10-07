"""Pedidos de desbloqueo de IP de fail2ban (los ejecuta un script del host).

Revisión: 0033_desbloqueos_ip
Anterior: 0032_consumo_calidad

De la plataforma, no de una empresa: sin tenant_id ni RLS.
"""

from alembic import op

revision = "0033_desbloqueos_ip"
down_revision = "0032_consumo_calidad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS desbloqueos_ip (id SERIAL PRIMARY KEY, jail VARCHAR(64) NOT NULL, "
        "ip VARCHAR(64) NOT NULL, motivo VARCHAR(200), pedido_por VARCHAR(100) NOT NULL, "
        "pedido_en TIMESTAMP WITHOUT TIME ZONE NOT NULL, estado VARCHAR(20) NOT NULL DEFAULT 'pendiente', "
        "resuelto_en TIMESTAMP WITHOUT TIME ZONE, detalle VARCHAR(300))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_desbloqueos_ip_estado ON desbloqueos_ip (estado)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS desbloqueos_ip")
