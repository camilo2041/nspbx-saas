"""Columnas de secretos a TEXT, para guardarlas cifradas.

Revisión: 0002_secretos_cifrados
Anterior: 0001_base

Un valor cifrado ("enc:v1:" + base64 de nonce y texto) no entra en
VARCHAR(64..255). Los valores en sí los cifra el arranque
(core/cifrado.cifrar_pendientes), no esta revisión: tiene que poder
repetirse cuando se configura o se rota DATA_ENCRYPTION_KEY, y una
revisión corre una sola vez.
"""

from alembic import op

revision = "0002_secretos_cifrados"
down_revision = "0001_base"
branch_labels = None
depends_on = None

_LARGOS = {
    ("trunks", "password"): 255,
    ("extensions", "password"): 255,
    ("system_settings", "fs_esl_password"): 255,
    ("system_settings", "elevenlabs_api_key"): 255,
    ("system_settings", "agent_webhook_secret"): 255,
    ("system_settings", "ai_llm_api_key"): 255,
    ("system_settings", "deepgram_api_key"): 200,
    ("system_settings", "ari_password"): 255,
    ("system_settings", "webcall_turnstile_secret"): 255,
    ("users", "mfa_secret"): 64,
}


def upgrade() -> None:
    # Cambiar a TEXT es idempotente (si ya lo es, no hace nada).
    for (tabla, columna) in _LARGOS:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE TEXT")


def downgrade() -> None:
    # Volver a VARCHAR solo es posible con los valores en claro: si hay
    # alguno cifrado no entra y Postgres corta la operación, que es lo
    # correcto (antes hay que descifrarlos).
    for (tabla, columna), largo in _LARGOS.items():
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE VARCHAR({largo})")
