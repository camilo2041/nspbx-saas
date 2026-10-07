"""Preguntas al asistente que ninguna guía respondió.

Revisión: 0038_preguntas_sin_guia
Anterior: 0037_conservar_grabacion

Las lee Plataforma con la sesión del dueño: sin RLS.
"""

from alembic import op

revision = "0038_preguntas_sin_guia"
down_revision = "0037_conservar_grabacion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS preguntas_sin_guia (id SERIAL PRIMARY KEY, clave VARCHAR(200) NOT NULL UNIQUE, "
        "ejemplo VARCHAR(300) NOT NULL, veces INTEGER NOT NULL DEFAULT 1, origen VARCHAR(10) NOT NULL DEFAULT 'panel', "
        "primera_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL, ultima_vez TIMESTAMP WITHOUT TIME ZONE NOT NULL)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_preguntas_sin_guia_ultima_vez ON preguntas_sin_guia (ultima_vez)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS preguntas_sin_guia")
