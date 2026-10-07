"""Devolución de llamada desde la fila de un grupo de atención.

Revisión: 0026_devoluciones
Anterior: 0025_sin_ruta_y_cupos

IF NOT EXISTS: en una base nueva la 0001 ya creó las tablas desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

from alembic import op

revision = "0026_devoluciones"
down_revision = "0025_sin_ruta_y_cupos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE queues ADD COLUMN IF NOT EXISTS devolucion BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "CREATE TABLE IF NOT EXISTS devoluciones (id SERIAL PRIMARY KEY, "
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "queue_id INTEGER REFERENCES queues(id) ON DELETE SET NULL, numero VARCHAR(30) NOT NULL, did VARCHAR(30), "
        "estado VARCHAR(12) NOT NULL DEFAULT 'pendiente', intentos INTEGER NOT NULL DEFAULT 0, "
        "pedida_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, proximo_at TIMESTAMP WITHOUT TIME ZONE, "
        "hecha_at TIMESTAMP WITHOUT TIME ZONE, detalle VARCHAR(200))"
    )
    for col in ("tenant_id", "queue_id", "estado", "pedida_at"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_devoluciones_{col} ON devoluciones ({col})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS devoluciones")
    op.execute("ALTER TABLE queues DROP COLUMN IF EXISTS devolucion")
