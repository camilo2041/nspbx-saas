"""CRM: contactos, campos propios, listas, notas, no llamar y el lead.

Revisión: 0012_crm
Anterior: 0011_tiempos_llamada

El lead es la fila de `campaign_numbers` (un número dentro de una
campaña), ahora con contacto, lista, prioridad y próximo intento. Cada
número existente queda ligado a un contacto: se crea uno por teléfono y
empresa, con el nombre que traía en sus variables ("cliente" o "nombre").

IF NOT EXISTS: en una base nueva la 0001 ya creó las tablas desde los
modelos. RLS y permisos los pone el arranque (main._TABLAS_CON_RLS).
"""

import json
import re

from alembic import op
from sqlalchemy import text

revision = "0012_crm"
down_revision = "0011_tiempos_llamada"
branch_labels = None
depends_on = None

_TS = "TIMESTAMP WITHOUT TIME ZONE"


def _clave(numero: str) -> str:
    # Misma regla que services/crm.py:clave_telefono (copiada: una revisión
    # no puede depender de código que cambie después).
    digitos = re.sub(r"\D", "", numero or "")
    return digitos[-10:]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS contactos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(150) NOT NULL,
            documento VARCHAR(30),
            telefono VARCHAR(40) NOT NULL,
            telefono_clave VARCHAR(20) NOT NULL,
            telefonos JSON,
            email VARCHAR(150),
            direccion VARCHAR(255),
            ciudad VARCHAR(100),
            campos JSON,
            fuente VARCHAR(60),
            created_at {_TS} NOT NULL,
            updated_at {_TS} NOT NULL
        )
        """
    )
    for col in ("tenant_id", "documento", "telefono_clave"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_contactos_{col} ON contactos ({col})")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS campos_contacto (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            clave VARCHAR(40) NOT NULL,
            nombre VARCHAR(80) NOT NULL,
            tipo VARCHAR(15) NOT NULL,
            opciones JSON,
            obligatorio BOOLEAN NOT NULL DEFAULT false,
            visible_agente BOOLEAN NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ux_campos_contacto_tenant_clave UNIQUE (tenant_id, clave)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_campos_contacto_tenant_id ON campos_contacto (tenant_id)")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS listas (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            nombre VARCHAR(120) NOT NULL,
            activa BOOLEAN NOT NULL,
            prioridad INTEGER NOT NULL DEFAULT 0,
            origen VARCHAR(20) NOT NULL,
            created_at {_TS} NOT NULL
        )
        """
    )
    for col in ("tenant_id", "campaign_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_listas_{col} ON listas ({col})")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS notas (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            contacto_id INTEGER NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            autor VARCHAR(150),
            texto TEXT NOT NULL,
            created_at {_TS} NOT NULL
        )
        """
    )
    for col in ("tenant_id", "contacto_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_notas_{col} ON notas ({col})")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS no_llamar (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            telefono VARCHAR(40) NOT NULL,
            telefono_clave VARCHAR(20) NOT NULL,
            motivo VARCHAR(255),
            hasta {_TS},
            creado_por VARCHAR(150),
            created_at {_TS} NOT NULL,
            CONSTRAINT ux_no_llamar_tenant_clave UNIQUE (tenant_id, telefono_clave)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_no_llamar_tenant_id ON no_llamar (tenant_id)")

    op.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS reglas_reciclaje JSON")
    for col, tipo in (
        ("contacto_id", "INTEGER REFERENCES contactos(id) ON DELETE SET NULL"),
        ("lista_id", "INTEGER REFERENCES listas(id) ON DELETE SET NULL"),
        ("prioridad", "INTEGER NOT NULL DEFAULT 0"),
        ("proximo_intento_at", _TS),
        ("ultimo_intento_at", _TS),
    ):
        op.execute(f"ALTER TABLE campaign_numbers ADD COLUMN IF NOT EXISTS {col} {tipo}")
    for col in ("contacto_id", "lista_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_campaign_numbers_{col} ON campaign_numbers ({col})")

    _contactos_de_los_numeros()


def _contactos_de_los_numeros() -> None:
    """Un contacto por teléfono y empresa para los números ya cargados."""
    conn = op.get_bind()
    filas = conn.execute(
        text(
            "SELECT id, tenant_id, phone, extra_data FROM campaign_numbers "
            "WHERE contacto_id IS NULL ORDER BY id"
        )
    ).all()
    contactos: dict[tuple[int, str], int] = {}
    for fila in filas:
        clave = _clave(fila.phone)
        if not clave:
            continue
        llave = (fila.tenant_id, clave)
        if llave not in contactos:
            nombre = ""
            try:
                datos = json.loads(fila.extra_data) if fila.extra_data else {}
                if isinstance(datos, dict):
                    bajas = {str(k).lower(): v for k, v in datos.items()}
                    nombre = str(bajas.get("cliente") or bajas.get("nombre") or "")[:150]
            except (ValueError, TypeError):
                pass
            contactos[llave] = conn.execute(
                text(
                    "INSERT INTO contactos (tenant_id, nombre, telefono, telefono_clave, fuente, created_at, updated_at) "
                    "VALUES (:t, :n, :tel, :c, 'campaña', now() at time zone 'utc', now() at time zone 'utc') "
                    "RETURNING id"
                ),
                {"t": fila.tenant_id, "n": nombre, "tel": fila.phone[:40], "c": clave},
            ).scalar_one()
        conn.execute(
            text("UPDATE campaign_numbers SET contacto_id = :c WHERE id = :id"),
            {"c": contactos[llave], "id": fila.id},
        )


def downgrade() -> None:
    for col in ("ultimo_intento_at", "proximo_intento_at", "prioridad", "lista_id", "contacto_id"):
        op.execute(f"ALTER TABLE campaign_numbers DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS reglas_reciclaje")
    for tabla in ("no_llamar", "notas", "listas", "campos_contacto", "contactos"):
        op.execute(f"DROP TABLE IF EXISTS {tabla}")
