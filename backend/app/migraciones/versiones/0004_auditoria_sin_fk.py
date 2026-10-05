"""audit_log.tenant_id sin clave foránea a tenants.

Revisión: 0004_auditoria_sin_fk
Anterior: 0003_versiones_voicebot

Con ON DELETE SET NULL, borrar una empresa hacía un UPDATE sobre
audit_log, que el disparador de solo agregar rechaza: ninguna empresa con
actividad se podía borrar. El registro conserva el número de la empresa.
"""

from alembic import op

revision = "0004_auditoria_sin_fk"
down_revision = "0003_versiones_voicebot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_tenant_id_fkey")


def downgrade() -> None:
    # NOT VALID: puede haber registros de empresas ya borradas.
    op.execute(
        "ALTER TABLE audit_log ADD CONSTRAINT audit_log_tenant_id_fkey FOREIGN KEY (tenant_id) "
        "REFERENCES tenants(id) ON DELETE SET NULL NOT VALID"
    )
