"""Agentes: pausas, disposiciones, sesiones, bitácora de estados, callbacks.

Revisión: 0013_agentes
Anterior: 0012_crm

IF NOT EXISTS: en una base nueva la 0001 ya creó las tablas desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS). Los
catálogos de ejemplo (pausas y disposiciones) se crean por empresa la
primera vez que se usan (services/agentes.py:asegurar_catalogos).
"""

from alembic import op

revision = "0013_agentes"
down_revision = "0012_crm"
branch_labels = None
depends_on = None

_TS = "TIMESTAMP WITHOUT TIME ZONE"
_TENANT = "tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE"


def _tabla(nombre: str, columnas: str, indices: tuple[str, ...] = ()) -> None:
    op.execute(f"CREATE TABLE IF NOT EXISTS {nombre} (id SERIAL PRIMARY KEY, {_TENANT}, {columnas})")
    for col in ("tenant_id", *indices):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{nombre}_{col} ON {nombre} ({col})")


def upgrade() -> None:
    _tabla(
        "codigos_pausa",
        "codigo VARCHAR(20) NOT NULL, nombre VARCHAR(60) NOT NULL, pagada BOOLEAN NOT NULL, "
        "max_minutos INTEGER, activo BOOLEAN NOT NULL, orden INTEGER NOT NULL DEFAULT 0, "
        "CONSTRAINT ux_codigos_pausa_tenant_codigo UNIQUE (tenant_id, codigo)",
    )
    _tabla(
        "disposiciones",
        "codigo VARCHAR(20) NOT NULL, nombre VARCHAR(60) NOT NULL, categoria VARCHAR(15) NOT NULL, "
        "contacto_humano BOOLEAN NOT NULL, color VARCHAR(10), activa BOOLEAN NOT NULL, "
        "orden INTEGER NOT NULL DEFAULT 0, "
        "CONSTRAINT ux_disposiciones_tenant_codigo UNIQUE (tenant_id, codigo)",
    )
    _tabla(
        "campana_agentes",
        "campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE, "
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "CONSTRAINT ux_campana_agentes UNIQUE (campaign_id, user_id)",
        ("campaign_id", "user_id"),
    )
    _tabla(
        "sesiones_agente",
        f"user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, campanas JSON, "
        f"extension VARCHAR(20), inicio {_TS} NOT NULL, fin {_TS}, motivo_fin VARCHAR(20)",
        ("user_id",),
    )
    _tabla(
        "estados_agente",
        f"user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        f"sesion_id INTEGER NOT NULL REFERENCES sesiones_agente(id) ON DELETE CASCADE, "
        f"estado VARCHAR(15) NOT NULL, "
        f"codigo_pausa_id INTEGER REFERENCES codigos_pausa(id) ON DELETE SET NULL, "
        f"campaign_id INTEGER, lead_id INTEGER, call_uuid VARCHAR(64), disposicion_id INTEGER, "
        f"inicio {_TS} NOT NULL, fin {_TS}",
        ("user_id", "sesion_id", "call_uuid"),
    )
    _tabla(
        "agentes_vivo",
        f"user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        f"sesion_id INTEGER NOT NULL REFERENCES sesiones_agente(id) ON DELETE CASCADE, "
        f"estado VARCHAR(15) NOT NULL, desde {_TS} NOT NULL, codigo_pausa_id INTEGER, campanas JSON, "
        f"extension VARCHAR(20), audio_uuid VARCHAR(64), audio BOOLEAN NOT NULL, token_audio VARCHAR(64), "
        f"campaign_id INTEGER, lead_id INTEGER, call_uuid VARCHAR(64), telefono VARCHAR(40), "
        f"contestada_at {_TS}, pausa_pendiente_id INTEGER, volver_a_pausa_id INTEGER, "
        f"CONSTRAINT ux_agentes_vivo_user UNIQUE (user_id)",
    )
    _tabla(
        "callbacks",
        f"lead_id INTEGER NOT NULL REFERENCES campaign_numbers(id) ON DELETE CASCADE, "
        f"campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE, "
        f"contacto_id INTEGER REFERENCES contactos(id) ON DELETE SET NULL, "
        f"agente_id INTEGER REFERENCES users(id) ON DELETE SET NULL, "
        f"cuando {_TS} NOT NULL, estado VARCHAR(12) NOT NULL, nota TEXT, creado_por INTEGER, "
        f"created_at {_TS} NOT NULL",
        ("lead_id", "cuando"),
    )

    for col, tipo in (
        ("metodo", "VARCHAR(20) NOT NULL DEFAULT 'voizbot'"),
        ("guion", "TEXT"),
        ("grabacion", "VARCHAR(10) NOT NULL DEFAULT 'todas'"),
    ):
        op.execute(f"ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS {col} {tipo}")
    for col, tipo in (
        ("agente_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ("disposicion_id", "INTEGER REFERENCES disposiciones(id) ON DELETE SET NULL"),
    ):
        op.execute(f"ALTER TABLE campaign_numbers ADD COLUMN IF NOT EXISTS {col} {tipo}")
    for col in ("agente_id", "lead_id", "disposicion_id"):
        op.execute(f"ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS {col} INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_call_logs_agente_id ON call_logs (agente_id)")


def downgrade() -> None:
    for col in ("disposicion_id", "lead_id", "agente_id"):
        op.execute(f"ALTER TABLE call_logs DROP COLUMN IF EXISTS {col}")
    for col in ("disposicion_id", "agente_id"):
        op.execute(f"ALTER TABLE campaign_numbers DROP COLUMN IF EXISTS {col}")
    for col in ("grabacion", "guion", "metodo"):
        op.execute(f"ALTER TABLE campaigns DROP COLUMN IF EXISTS {col}")
    for tabla in ("callbacks", "agentes_vivo", "estados_agente", "sesiones_agente", "campana_agentes",
                  "disposiciones", "codigos_pausa"):
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
