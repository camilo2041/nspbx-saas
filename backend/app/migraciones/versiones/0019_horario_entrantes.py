"""Horario de atención en los números entrantes: fuera de él, la llamada
va a otro destino (otra persona, un grupo, el voizbot o colgar).

Revisión: 0019_horario_entrantes
Anterior: 0018_nodos
"""

from alembic import op

revision = "0019_horario_entrantes"
down_revision = "0018_nodos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbound_routes ADD COLUMN IF NOT EXISTS horario TEXT")
    op.execute("ALTER TABLE inbound_routes ADD COLUMN IF NOT EXISTS fuera_horario_tipo VARCHAR(20)")
    op.execute("ALTER TABLE inbound_routes ADD COLUMN IF NOT EXISTS fuera_horario_valor VARCHAR(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE inbound_routes DROP COLUMN IF EXISTS fuera_horario_valor")
    op.execute("ALTER TABLE inbound_routes DROP COLUMN IF EXISTS fuera_horario_tipo")
    op.execute("ALTER TABLE inbound_routes DROP COLUMN IF EXISTS horario")
