"""Instalaciones locales con licencia firmada por la central (Fase K).

Revisión: 0039_instalaciones_locales
Anterior: 0038_preguntas_sin_guia

`instalaciones` vive en la central; `licencia_local`, en el servidor del
cliente. Las dos son de la plataforma: sin RLS.
"""

from alembic import op

revision = "0039_instalaciones_locales"
down_revision = "0038_preguntas_sin_guia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS instalaciones ("
        "id SERIAL PRIMARY KEY, "
        "empresa_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "nombre VARCHAR(80) NOT NULL, "
        "estado VARCHAR(12) NOT NULL DEFAULT 'pendiente', "
        "codigo_hash VARCHAR(64) UNIQUE, "
        "codigo_vence TIMESTAMP WITHOUT TIME ZONE, "
        "token_hash VARCHAR(64) UNIQUE, "
        "activada_at TIMESTAMP WITHOUT TIME ZONE, "
        "ultimo_latido TIMESTAMP WITHOUT TIME ZONE, "
        "version VARCHAR(40), "
        "ip VARCHAR(64), "
        "uso JSON, "
        "created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now())"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_instalaciones_empresa_id ON instalaciones (empresa_id)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS licencia_local ("
        "id INTEGER PRIMARY KEY, "
        "instalacion_id INTEGER NOT NULL, "
        "token TEXT NOT NULL, "
        "documento TEXT NOT NULL, "
        "firma VARCHAR(200) NOT NULL, "
        "recibida_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(), "
        "ultimo_intento_at TIMESTAMP WITHOUT TIME ZONE, "
        "ultimo_error VARCHAR(300), "
        "version_disponible VARCHAR(40))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS licencia_local")
    op.execute("DROP TABLE IF EXISTS instalaciones")
