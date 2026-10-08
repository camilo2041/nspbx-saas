"""Certificado real para instalaciones locales en red local (Fase K, punto 15).

Revisión: 0040_certificados_locales
Anterior: 0039_instalaciones_locales

Cada instalación recibe un subdominio de la central con su registro A a la
IP de la red local y un certificado de Let's Encrypt por DNS-01. La cuenta
ACME de la central se guarda cifrada en `acme_cuenta` (una fila).
"""

from alembic import op

revision = "0040_certificados_locales"
down_revision = "0039_instalaciones_locales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for columna in (
        "subdominio VARCHAR(120)",
        "ip_local VARCHAR(45)",
        "csr TEXT",
        "certificado TEXT",
        "cert_vence TIMESTAMP WITHOUT TIME ZONE",
        "cert_error VARCHAR(300)",
    ):
        op.execute(f"ALTER TABLE instalaciones ADD COLUMN IF NOT EXISTS {columna}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_instalaciones_subdominio ON instalaciones (subdominio)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS acme_cuenta (id INTEGER PRIMARY KEY, clave TEXT NOT NULL, "
        "kid VARCHAR(300), directorio VARCHAR(200))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS acme_cuenta")
    op.execute("DROP INDEX IF EXISTS ux_instalaciones_subdominio")
    for columna in ("subdominio", "ip_local", "csr", "certificado", "cert_vence", "cert_error"):
        op.execute(f"ALTER TABLE instalaciones DROP COLUMN IF EXISTS {columna}")
