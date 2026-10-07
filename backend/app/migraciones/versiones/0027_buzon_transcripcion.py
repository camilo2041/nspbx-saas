"""Transcripción de los mensajes de buzón.

Revisión: 0027_buzon_transcripcion
Anterior: 0026_devoluciones
"""

from alembic import op

revision = "0027_buzon_transcripcion"
down_revision = "0026_devoluciones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE buzon_mensajes ADD COLUMN IF NOT EXISTS transcripcion TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE buzon_mensajes DROP COLUMN IF EXISTS transcripcion")
