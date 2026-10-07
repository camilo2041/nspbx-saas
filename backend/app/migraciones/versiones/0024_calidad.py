"""Calidad de llamadas: criterios por empresa, evaluaciones y la
transcripción guardada de cada grabación.

Revisión: 0024_calidad
Anterior: 0023_webcall_sesiones

IF NOT EXISTS: en una base nueva la 0001 ya creó las tablas desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

from alembic import op

revision = "0024_calidad"
down_revision = "0023_webcall_sesiones"
branch_labels = None
depends_on = None

_TENANT = "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE"


def upgrade() -> None:
    op.execute("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS transcripcion JSON")
    op.execute(
        f"CREATE TABLE IF NOT EXISTS criterios_calidad (id SERIAL PRIMARY KEY, {_TENANT}, "
        "nombre VARCHAR(120) NOT NULL, descripcion TEXT, peso INTEGER NOT NULL DEFAULT 1, "
        "orden INTEGER NOT NULL DEFAULT 0, activo BOOLEAN NOT NULL DEFAULT true)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS evaluaciones_llamada (id SERIAL PRIMARY KEY, {_TENANT}, "
        "call_id INTEGER NOT NULL REFERENCES call_logs(id) ON DELETE CASCADE, "
        "agente_id INTEGER REFERENCES users(id) ON DELETE SET NULL, "
        "evaluador_id INTEGER REFERENCES users(id) ON DELETE SET NULL, "
        "puntajes JSON NOT NULL, total_pct DOUBLE PRECISION NOT NULL, comentario TEXT, "
        "origen VARCHAR(10) NOT NULL DEFAULT 'manual', created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL)"
    )
    for tabla, col in (("criterios_calidad", "tenant_id"), ("evaluaciones_llamada", "tenant_id"),
                       ("evaluaciones_llamada", "call_id"), ("evaluaciones_llamada", "agente_id"),
                       ("evaluaciones_llamada", "created_at")):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabla}_{col} ON {tabla} ({col})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluaciones_llamada")
    op.execute("DROP TABLE IF EXISTS criterios_calidad")
    op.execute("ALTER TABLE call_logs DROP COLUMN IF EXISTS transcripcion")
