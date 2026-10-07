"""Intentos fallidos de inicio de sesión compartidos entre réplicas
(antes, en memoria de cada una).

Revisión: 0031_intentos_acceso
Anterior: 0030_pin_buzon

Sin tenant_id ni RLS: se consulta antes de saber de qué empresa es nadie.
"""

from alembic import op

revision = "0031_intentos_acceso"
down_revision = "0030_pin_buzon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS intentos_acceso (clave VARCHAR(200) PRIMARY KEY, fallos INTEGER NOT NULL DEFAULT 0, "
        "inicio DOUBLE PRECISION NOT NULL DEFAULT 0, hasta DOUBLE PRECISION NOT NULL DEFAULT 0)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intentos_acceso")
