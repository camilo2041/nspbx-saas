"""Migraciones versionadas (Alembic).

Antes, el esquema se llevaba con una lista de ALTER TABLE ... IF NOT
EXISTS en main.py que corría entera en cada arranque: sin versión, sin
orden garantizado entre cambios y sin forma de deshacer uno. Ahora:

- `versiones/0001_base.py` es el esquema tal como estaba (esa lista,
  congelada en `main._PARCHES_BASE`). Es idempotente: en una base
  existente no cambia nada y la deja registrada en la versión 0001.
- Cada cambio nuevo es una revisión en `versiones/`, con su downgrade:
      cd backend && alembic revision -m "agrega tal cosa"
- Las revisiones tienen que poder correr sobre una base creada desde
  cero, donde la 0001 ya creó las tablas con los modelos ACTUALES (usar
  `IF NOT EXISTS` o comprobar antes). tests/test_migraciones.py lo
  verifica en CI.
- Permisos, RLS y la auditoría de solo agregar no son revisiones: corren
  en cada arranque después de ellas (ver main._PARCHES_CONVERGENCIA).
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

CARPETA = Path(__file__).parent


def configuracion() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(CARPETA))
    cfg.set_main_option("version_locations", str(CARPETA / "versiones"))
    return cfg


def actualizar(conexion) -> None:
    """Lleva la base a la última revisión, sobre una conexión síncrona ya
    abierta (se llama con `AsyncConnection.run_sync` desde main.migrar)."""
    cfg = configuracion()
    cfg.attributes["connection"] = conexion
    command.upgrade(cfg, "head")


def version_actual(conexion) -> str | None:
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(conexion).get_current_revision()
