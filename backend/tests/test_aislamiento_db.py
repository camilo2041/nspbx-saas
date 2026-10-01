"""I1 en la base: Row-Level Security corta aunque la aplicación no filtre.

Estas pruebas hablan directo con Postgres usando el rol de la aplicación
y consultas SIN `WHERE tenant_id`. Es la red de seguridad: el día que un
endpoint se olvide del filtro, lo que lo salva es esto.
"""

import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.database import Base, app_engine, app_session, engine, fijar_tenant
from app.main import _TABLAS_CON_RLS
from app.models import Extension, Trunk

from .conftest import requiere_rls

# Estas pruebas verifican RLS en sí: en el modo sin RLS no aplican.
pytestmark = requiere_rls


def _modelos_con_tenant():
    return [
        m.class_
        for m in Base.registry.mappers
        if "tenant_id" in m.class_.__table__.columns
    ]


def test_toda_tabla_con_tenant_tiene_rls():
    """Una tabla nueva con `tenant_id` que no se agregue a la lista de RLS
    queda fuera del aislamiento sin que nada lo avise. Esto lo avisa."""
    faltan = sorted(
        m.__tablename__ for m in _modelos_con_tenant() if m.__tablename__ not in _TABLAS_CON_RLS
    )
    assert not faltan, f"Tablas con tenant_id sin Row-Level Security: {faltan}"


async def test_politicas_activas_en_postgres(mundo):
    """La lista dice que hay RLS; esto comprueba que Postgres lo tenga."""
    async with engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, "
                    "  (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'p_tenant'), "
                    "  (SELECT p.polwithcheck IS NOT NULL FROM pg_policy p "
                    "     WHERE p.polrelid = c.oid AND p.polname = 'p_tenant') "
                    "FROM pg_class c WHERE c.relname = ANY(:tablas) AND c.relkind = 'r'"
                ),
                {"tablas": _TABLAS_CON_RLS},
            )
        ).all()
    estado = {nombre: (rls, politicas, con_check) for nombre, rls, politicas, con_check in filas}
    assert set(estado) == set(_TABLAS_CON_RLS)
    for tabla, (rls, politicas, con_check) in estado.items():
        assert rls, f"{tabla}: ROW LEVEL SECURITY desactivado"
        assert politicas == 1, f"{tabla}: falta la política p_tenant"
        assert con_check, f"{tabla}: la política no tiene WITH CHECK (se podría escribir en otra empresa)"


async def test_rol_de_la_aplicacion_no_saltea_rls(mundo):
    async with app_engine.connect() as conn:
        usuario, es_super, saltea, es_dueno = (
            await conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls, "
                    "  EXISTS (SELECT 1 FROM pg_tables WHERE tableowner = current_user AND schemaname = 'public') "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    assert not es_super, f"{usuario} es superusuario"
    assert not saltea, f"{usuario} tiene BYPASSRLS"
    assert not es_dueno, f"{usuario} es dueño de tablas: el dueño se saltea RLS"


@pytest.mark.parametrize("tabla", _TABLAS_CON_RLS)
async def test_sin_filtro_solo_se_ve_la_propia_empresa(mundo, tabla):
    """`SELECT *` sin WHERE, atado a alfa: ninguna fila de beta."""
    async with app_session() as session:
        fijar_tenant(session, mundo.alfa.id)
        empresas = {
            fila[0] for fila in (await session.execute(text(f"SELECT DISTINCT tenant_id FROM {tabla}"))).all()
        }
    assert mundo.beta.id not in empresas


async def test_hay_datos_propios_visibles(mundo):
    """Control positivo: sin esto, las pruebas de arriba pasarían también
    con una política que no deja ver NADA."""
    async with app_session() as session:
        fijar_tenant(session, mundo.alfa.id)
        exts = (await session.execute(select(Extension))).scalars().all()
    assert [e.tenant_id for e in exts] == [mundo.alfa.id]


@pytest.mark.parametrize("tabla", _TABLAS_CON_RLS)
async def test_sin_empresa_fijada_no_se_ve_nada(mundo, tabla):
    """Modo de falla seguro: si alguien consulta antes de fijar la empresa,
    la respuesta es vacía, nunca todo."""
    async with app_session() as session:
        n = (await session.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar()
    assert n == 0


async def test_no_se_puede_insertar_en_otra_empresa(mundo):
    async with app_session() as session:
        fijar_tenant(session, mundo.alfa.id)
        session.add(Extension(tenant_id=mundo.beta.id, number="6666", password="x"))
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.commit()


async def test_no_se_puede_mover_una_fila_a_otra_empresa(mundo):
    async with app_session() as session:
        fijar_tenant(session, mundo.alfa.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                update(Trunk).where(Trunk.id == mundo.alfa.ids["trunk"]).values(tenant_id=mundo.beta.id)
            )
            await session.commit()


async def test_update_y_delete_masivos_no_tocan_otra_empresa(mundo):
    """El olvido más caro: un UPDATE o DELETE sin WHERE. Se hace dentro de
    una transacción que se descarta, para no romper el resto de pruebas."""
    async with app_engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mundo.alfa.id)})
        await conn.execute(text("UPDATE extensions SET caller_id_name = 'pisado'"))
        await conn.execute(text("DELETE FROM payment_promises"))
        # Se mira con los ojos de beta DENTRO de la misma transacción, que
        # es la única que ve los cambios todavía sin confirmar.
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mundo.beta.id)})
        nombre = (
            await conn.execute(text("SELECT caller_id_name FROM extensions WHERE id = :i"), {"i": mundo.beta.ids["extension"]})
        ).scalar()
        promesas = (await conn.execute(text("SELECT count(*) FROM payment_promises"))).scalar()
        await tx.rollback()
    assert nombre == "Recepcion zzbeta"
    assert promesas == 1


async def test_update_masivo_sin_filtro_solo_alcanza_la_propia_empresa(mundo):
    """Como el anterior, pero mirando cuántas filas tocó el UPDATE: tiene
    que ser exactamente la de alfa."""
    async with app_engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mundo.alfa.id)})
        res = await conn.execute(text("UPDATE extensions SET caller_id_name = caller_id_name"))
        await tx.rollback()
    assert res.rowcount == 1


async def test_la_empresa_sobrevive_a_varios_commits(mundo):
    """`SET LOCAL` muere con la transacción; el enganche `after_begin` lo
    reaplica. Sin eso, después del primer commit todo se ve vacío."""
    async with app_session() as session:
        fijar_tenant(session, mundo.alfa.id)
        assert (await session.execute(select(Extension))).scalars().all()
        await session.commit()
        assert (await session.execute(select(Extension))).scalars().all()
        await session.commit()
        exts = (await session.execute(select(Extension))).scalars().all()
    assert [e.tenant_id for e in exts] == [mundo.alfa.id]


def test_los_modelos_de_negocio_exigen_tenant():
    """`tenant_id` NOT NULL en toda tabla de negocio (menos `users`, donde
    NULL es el usuario de la plataforma)."""
    for modelo in _modelos_con_tenant():
        # NULL es la plataforma (usuarios) o algo que no es de ninguna empresa
        # (auditoría de la plataforma, logins de usuarios inexistentes).
        if modelo.__tablename__ in ("users", "audit_log"):
            continue
        col = inspect(modelo).columns["tenant_id"]
        assert not col.nullable, f"{modelo.__tablename__}.tenant_id admite NULL"
