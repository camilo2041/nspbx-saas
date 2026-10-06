"""Buzón de voz: mensajes que dejan quienes llaman a una extensión que no
contesta.

Revisión: 0020_buzon_de_voz
Anterior: 0019_horario_entrantes

IF NOT EXISTS: en una base nueva la 0001 ya creó la tabla desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

from alembic import op

revision = "0020_buzon_de_voz"
down_revision = "0019_horario_entrantes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS buzon_mensajes ("
        "id SERIAL PRIMARY KEY, "
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "extension VARCHAR(20) NOT NULL, call_uuid VARCHAR(64) UNIQUE, "
        "caller_number VARCHAR(30), caller_name VARCHAR(100), ruta VARCHAR(500) NOT NULL, "
        "duracion INTEGER NOT NULL DEFAULT 0, escuchado BOOLEAN NOT NULL DEFAULT false, "
        "created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_buzon_mensajes_tenant_id ON buzon_mensajes (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_buzon_mensajes_extension ON buzon_mensajes (extension)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS buzon_mensajes")
