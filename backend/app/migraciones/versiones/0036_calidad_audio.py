"""Calidad del audio de cada llamada (MOS, % de calidad, paquetes perdidos) y el proveedor.

Revisión: 0036_calidad_audio
Anterior: 0035_errores_cliente
"""

from alembic import op

revision = "0036_calidad_audio"
down_revision = "0035_errores_cliente"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for columna, tipo in (("audio_mos", "DOUBLE PRECISION"), ("audio_calidad", "DOUBLE PRECISION"),
                          ("audio_perdida", "DOUBLE PRECISION"), ("troncal", "VARCHAR(100)")):
        op.execute(f"ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS {columna} {tipo}")


def downgrade() -> None:
    for columna in ("troncal", "audio_perdida", "audio_calidad", "audio_mos"):
        op.execute(f"ALTER TABLE call_logs DROP COLUMN IF EXISTS {columna}")
