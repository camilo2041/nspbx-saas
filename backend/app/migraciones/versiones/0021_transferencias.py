"""Transferir y poner en espera desde la consola de agente.

Revisión: 0021_transferencias
Anterior: 0020_buzon_de_voz
"""

from alembic import op

revision = "0021_transferencias"
down_revision = "0020_buzon_de_voz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agentes_vivo ADD COLUMN IF NOT EXISTS en_espera BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE agentes_vivo ADD COLUMN IF NOT EXISTS consulta_uuid VARCHAR(64)")
    op.execute("ALTER TABLE agentes_vivo ADD COLUMN IF NOT EXISTS consulta_destino VARCHAR(40)")


def downgrade() -> None:
    op.execute("ALTER TABLE agentes_vivo DROP COLUMN IF EXISTS consulta_destino")
    op.execute("ALTER TABLE agentes_vivo DROP COLUMN IF EXISTS consulta_uuid")
    op.execute("ALTER TABLE agentes_vivo DROP COLUMN IF EXISTS en_espera")
