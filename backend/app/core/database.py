import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session as SyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# Motor del DUEÑO: migraciones, login y alta de empresas. No pasa por
# Row-Level Security, y esa es justamente la razón de tenerlo separado.
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Motor de la APLICACIÓN: todo lo demás. Sujeto a RLS.
app_engine = create_async_engine(
    settings.database_url_app or settings.database_url, echo=False, pool_pre_ping=True
)
app_session = async_sessionmaker(app_engine, expire_on_commit=False)

AISLAMIENTO_ACTIVO = bool(settings.database_url_app)


# El identificador de empresa se guarda en `session.info` y se aplica a la
# conexión en CADA transacción, no una sola vez al abrir la sesión.
#
# El motivo es la trampa más común de RLS con un ORM: `SET LOCAL` dura lo
# que dura la transacción. Cualquier `commit()` en medio de la petición
# —y hay endpoints que hacen varios— la cierra; la consulta siguiente
# abre una transacción nueva SIN el valor puesto, y desde ahí las
# políticas no encuentran empresa y no devuelven ninguna fila. No falla:
# devuelve vacío. Listados que aparecen sin datos, y solo después del
# primer commit.
@event.listens_for(SyncSession, "after_begin")
def _aplicar_tenant(session, transaction, connection):
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None:
        return
    # set_config(..., true) hace lo mismo que SET LOCAL pero es una
    # función, así que acepta el valor como PARÁMETRO. Con "SET LOCAL"
    # habría que interpolar el número dentro del texto del SQL, que es
    # justo lo que no conviene hacer con un dato que llega en un token.
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def fijar_tenant(session, tenant_id: int | None) -> None:
    """Ata una sesión asíncrona a una empresa. Ver `_aplicar_tenant`."""
    session.sync_session.info["tenant_id"] = tenant_id


async def get_session():
    """Sesión de la operación normal — con RLS si está configurado.

    Nace SIN empresa a propósito. Quien la ata es `sesion_obligatoria`,
    leyendo el token (ver app/core/auth.py). Si algo consultara antes de
    ese paso, las políticas no encontrarían empresa y no devolverían
    filas: el comportamiento por omisión es no mostrar nada, no
    mostrarlo todo.
    """
    async with app_session() as session:
        yield session


async def get_admin_session():
    """Sesión del dueño, SIN aislamiento por empresa.

    Solo para lo que no puede estar limitado a una empresa: buscar al
    usuario que intenta entrar —todavía no se sabe de cuál es— y dar de
    alta empresas nuevas. Cada uso es una excepción al aislamiento, así
    que conviene que sean pocos y evidentes.
    """
    async with async_session() as session:
        yield session


async def verificar_rol_sin_privilegios() -> None:
    """Comprueba que el rol de la aplicación NO se saltee RLS.

    Existe porque la forma en que esto se rompe es silenciosa: si
    DATABASE_URL_APP queda vacía, apunta al usuario dueño, o alguien le
    da superusuario para "arreglar" un permiso, las políticas siguen
    definidas, las consultas siguen andando y el aislamiento desaparece
    sin un solo error. Un arranque ruidoso es preferible a enterarse
    cuando un cliente ve los datos de otro.
    """
    if not AISLAMIENTO_ACTIVO:
        logger.warning(
            "DATABASE_URL_APP sin configurar: la aplicación usa el rol dueño y el "
            "aislamiento por empresa NO se aplica. Aceptable en desarrollo; en "
            "producción hay que definirla."
        )
        return

    async with app_engine.connect() as conn:
        fila = (
            await conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).first()

    if fila is None:
        raise RuntimeError("No se pudo verificar el rol de la aplicación")
    usuario, es_super, saltea_rls = fila
    if es_super or saltea_rls:
        raise RuntimeError(
            f"El rol '{usuario}' de DATABASE_URL_APP es superusuario o tiene "
            "BYPASSRLS: las políticas de aislamiento no se le aplican y cada "
            "empresa vería los datos de las demás. Usá un rol común."
        )
    logger.info("Aislamiento por empresa activo (rol '%s', sujeto a RLS).", usuario)
