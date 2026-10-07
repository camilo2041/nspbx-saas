"""Sesiones del widget de llamada web en la base (antes, en memoria de un
solo proceso: con varias réplicas el directorio no las encontraba).

Revisión: 0023_webcall_sesiones
Anterior: 0022_entrantes
"""

from alembic import op

revision = "0023_webcall_sesiones"
down_revision = "0022_entrantes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS webcall_sesiones ("
        "id SERIAL PRIMARY KEY, username VARCHAR(20) NOT NULL UNIQUE, "
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "password TEXT NOT NULL, ip VARCHAR(64) NOT NULL, creada DOUBLE PRECISION NOT NULL, "
        "registrada BOOLEAN NOT NULL DEFAULT false, terminada BOOLEAN NOT NULL DEFAULT false)"
    )
    for col in ("tenant_id", "ip", "creada"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_webcall_sesiones_{col} ON webcall_sesiones ({col})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webcall_sesiones")
