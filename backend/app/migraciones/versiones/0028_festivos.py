"""Festivos y fechas especiales de cada empresa.

Revisión: 0028_festivos
Anterior: 0027_buzon_transcripcion
"""

from alembic import op

revision = "0028_festivos"
down_revision = "0027_buzon_transcripcion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS festivos_cerrado BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "CREATE TABLE IF NOT EXISTS fechas_especiales (id SERIAL PRIMARY KEY, "
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, fecha DATE NOT NULL, "
        "nombre VARCHAR(80) NOT NULL, franja VARCHAR(11), "
        "CONSTRAINT ux_fechas_especiales_tenant_fecha UNIQUE (tenant_id, fecha))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fechas_especiales_tenant_id ON fechas_especiales (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fechas_especiales_fecha ON fechas_especiales (fecha)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fechas_especiales")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS festivos_cerrado")
