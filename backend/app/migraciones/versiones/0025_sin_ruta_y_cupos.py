"""Números que llaman sin ruta de entrada y cupos de uso compartidos entre
réplicas (antes, en memoria de cada una).

Revisión: 0025_sin_ruta_y_cupos
Anterior: 0024_calidad

IF NOT EXISTS: en una base nueva la 0001 ya creó las tablas desde los modelos.
Ninguna es de una empresa (sin tenant_id ni RLS).
"""

from alembic import op

revision = "0025_sin_ruta_y_cupos"
down_revision = "0024_calidad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS numeros_sin_ruta (id SERIAL PRIMARY KEY, numero VARCHAR(64) NOT NULL UNIQUE, "
        "para VARCHAR(64), origen VARCHAR(64), troncal VARCHAR(120), veces INTEGER NOT NULL DEFAULT 1, "
        "primera_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL, ultima_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_numeros_sin_ruta_ultima_vez ON numeros_sin_ruta (ultima_vez)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS cupos_uso (clave VARCHAR(120) PRIMARY KEY, ventana BIGINT NOT NULL, "
        "conteo INTEGER NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cupos_uso")
    op.execute("DROP TABLE IF EXISTS numeros_sin_ruta")
