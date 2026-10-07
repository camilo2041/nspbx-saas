"""PIN del buzón para escucharlo desde otro teléfono (*96).

Revisión: 0030_pin_buzon
Anterior: 0029_calidad_auto
"""

from alembic import op

revision = "0030_pin_buzon"
down_revision = "0029_calidad_auto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cifrado en la aplicación (TextoCifrado), como la clave SIP.
    op.execute("ALTER TABLE extensions ADD COLUMN IF NOT EXISTS voicemail_pin TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE extensions DROP COLUMN IF EXISTS voicemail_pin")
