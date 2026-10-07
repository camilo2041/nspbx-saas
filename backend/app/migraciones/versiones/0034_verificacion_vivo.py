"""Verificación en vivo: pruebas manuales con teléfonos reales y su resultado.

Revisión: 0034_verificacion_vivo
Anterior: 0033_desbloqueos_ip

La maneja Plataforma con la sesión del dueño: sin RLS.
"""

from alembic import op

revision = "0034_verificacion_vivo"
down_revision = "0033_desbloqueos_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS verificaciones_vivo (id SERIAL PRIMARY KEY, "
        "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, clave VARCHAR(40) NOT NULL, "
        "estado VARCHAR(12) NOT NULL DEFAULT 'en_curso', iniciada_en TIMESTAMP WITHOUT TIME ZONE NOT NULL, "
        "terminada_en TIMESTAMP WITHOUT TIME ZONE, quien VARCHAR(100) NOT NULL, evidencia VARCHAR(300), nota VARCHAR(500))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_verificaciones_vivo_tenant_id ON verificaciones_vivo (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS verificaciones_vivo")
