"""Migraciones versionadas (app/migraciones).

Lo que se comprueba:

- Una base nueva llega a la última revisión, y correrlas otra vez no falla
  (cada arranque las corre).
- Una base de antes de Alembic (sin `alembic_version`) se actualiza sin
  perder datos.
- Una base con el esquema de la revisión base CONGELADO
  (tests/esquema_0001.sql), llevada a la última revisión, coincide con los
  modelos. Es la que atrapa el error caro: cambiar un modelo sin escribir la
  revisión. En una base nueva no se nota (create_all usa los modelos
  actuales); en producción, la columna nunca aparece.
- Las revisiones forman una sola cadena y las posteriores a la base se
  pueden deshacer y rehacer.
"""

import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app import migraciones
from app.core.database import Base, engine

from .conftest import _DUENO

_ESQUEMA_BASE = Path(__file__).with_name("esquema_0001.sql")


@pytest.fixture
async def base_vacia():
    """Una base de datos nueva y descartable en el mismo servidor."""
    nombre = f"nspbx_mig_{uuid.uuid4().hex[:8]}"
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'CREATE DATABASE "{nombre}"'))
    partes = urlsplit(_DUENO)
    otra = create_async_engine(partes._replace(path=f"/{nombre}").geturl())
    try:
        yield otra
    finally:
        await otra.dispose()
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))


def _cabeza() -> str:
    heads = ScriptDirectory.from_config(migraciones.configuracion()).get_heads()
    assert len(heads) == 1, f"Más de una cabeza de revisiones (ramas sin unir): {heads}"
    return heads[0]


async def _version(eng) -> str | None:
    async with eng.connect() as conn:
        return await conn.run_sync(migraciones.version_actual)


async def test_una_sola_cadena_de_revisiones():
    script = ScriptDirectory.from_config(migraciones.configuracion())
    revisiones = list(script.walk_revisions())
    assert revisiones[-1].revision == "0001_base"
    assert _cabeza() == revisiones[0].revision


async def test_base_nueva_llega_a_la_ultima_y_se_puede_repetir(base_vacia):
    for _ in range(2):
        async with base_vacia.begin() as conn:
            await conn.run_sync(migraciones.actualizar)
    assert await _version(base_vacia) == _cabeza()


async def test_base_anterior_a_alembic_se_actualiza_sin_perder_datos(base_vacia):
    """Producción hoy: el esquema completo, sin alembic_version."""
    from app.main import _PARCHES_BASE

    async with base_vacia.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sentencia in _PARCHES_BASE:
            await conn.execute(text(sentencia))
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await conn.execute(text("INSERT INTO tenants (id, name, slug, sip_domain, business_type, modules, enabled, created_at) VALUES (7, 'Vieja', 'vieja', 'vieja.test', 'general', 'pbx', true, now()) ON CONFLICT DO NOTHING"))
    assert await _version(base_vacia) is None

    async with base_vacia.begin() as conn:
        await conn.run_sync(migraciones.actualizar)
    assert await _version(base_vacia) == _cabeza()
    async with base_vacia.connect() as conn:
        assert (await conn.execute(text("SELECT name FROM tenants WHERE id = 7"))).scalar() == "Vieja"


def _sin_ruido(diferencias) -> list:
    """Diferencias que importan entre la base y los modelos."""
    relevantes = []
    for d in diferencias:
        d = d[0] if isinstance(d, list) else d
        # Índices y restricciones únicas que los parches de la base crean con
        # nombre propio (p. ej. índices parciales) no se expresan en los
        # modelos: no son columnas ni tablas faltantes.
        if d[0] in ("add_index", "remove_index", "add_constraint", "remove_constraint", "remove_table") and (
            d[0] != "remove_table" or getattr(d[1], "name", "") == "alembic_version"
        ):
            continue
        relevantes.append(d)
    return relevantes


async def test_esquema_congelado_mas_revisiones_coincide_con_los_modelos(base_vacia):
    script = _ESQUEMA_BASE.read_text()
    async with base_vacia.connect() as conn:
        crudo = await conn.get_raw_connection()
        await crudo.driver_connection.execute(script)
        await crudo.driver_connection.execute(
            "SELECT pg_catalog.set_config('search_path', 'public', false);"
            "INSERT INTO public.alembic_version (version_num) VALUES ('0001_base')"
        )
        await conn.commit()

    async with base_vacia.begin() as conn:
        await conn.run_sync(migraciones.actualizar)

    def comparar(conexion):
        contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
        return compare_metadata(contexto, Base.metadata)

    async with base_vacia.connect() as conn:
        diferencias = _sin_ruido(await conn.run_sync(comparar))
    assert not diferencias, (
        "Los modelos no coinciden con la base migrada: falta una revisión en "
        f"app/migraciones/versiones para estos cambios: {diferencias}"
    )


async def test_las_revisiones_posteriores_se_deshacen_y_rehacen(base_vacia):
    from alembic import command

    async with base_vacia.begin() as conn:
        await conn.run_sync(migraciones.actualizar)

    if _cabeza() == "0001_base":
        pytest.skip("todavía no hay revisiones después de la base")

    def bajar_y_subir(conexion):
        cfg = migraciones.configuracion()
        cfg.attributes["connection"] = conexion
        command.downgrade(cfg, "0001_base")
        command.upgrade(cfg, "head")

    async with base_vacia.begin() as conn:
        await conn.run_sync(bajar_y_subir)
    assert await _version(base_vacia) == _cabeza()


async def test_la_revision_del_crm_liga_cada_numero_a_un_contacto(base_vacia):
    """0012: los números ya cargados quedan con su contacto (uno por
    teléfono y empresa, con el nombre de sus variables). Una variable que no
    es JSON no frena la migración."""
    from alembic import command

    def a(revision):
        def ir(conexion):
            cfg = migraciones.configuracion()
            cfg.attributes["connection"] = conexion
            if revision == "head":
                command.upgrade(cfg, "head")
            else:
                command.downgrade(cfg, revision)

        return ir

    async with base_vacia.begin() as conn:
        await conn.run_sync(migraciones.actualizar)
        await conn.run_sync(a("0011_tiempos_llamada"))
        await conn.execute(text(
            "INSERT INTO tenants (id, name, slug, sip_domain, business_type, modules, enabled, created_at) "
            "VALUES (5, 'Uno', 'uno', 'uno.test', 'general', 'pbx', true, now())"
        ))
        await conn.execute(text(
            "INSERT INTO campaigns (id, tenant_id, name, max_concurrency, retries, status, created_at) "
            "VALUES (9, 5, 'c', 1, 0, 'idle', now())"
        ))
        for i, (telefono, extra) in enumerate([
            ("+57 300 111 2233", '{"cliente": "Ana Gómez"}'),
            ("3001112233", None),
            ("3009998877", "esto no es json"),
        ]):
            await conn.execute(
                text(
                    "INSERT INTO campaign_numbers (id, tenant_id, campaign_id, phone, status, attempts, extra_data, created_at) "
                    "VALUES (:id, 5, 9, :t, 'pending', 0, :e, now())"
                ),
                {"id": 100 + i, "t": telefono, "e": extra},
            )
    async with base_vacia.begin() as conn:
        await conn.run_sync(a("head"))
    async with base_vacia.connect() as conn:
        contactos = (await conn.execute(text(
            "SELECT telefono_clave, nombre FROM contactos WHERE tenant_id = 5 ORDER BY telefono_clave"
        ))).all()
        ligados = dict((await conn.execute(text("SELECT id, contacto_id FROM campaign_numbers"))).all())
    assert [tuple(c) for c in contactos] == [("3001112233", "Ana Gómez"), ("3009998877", "")]
    assert ligados[100] == ligados[101] != ligados[102]
