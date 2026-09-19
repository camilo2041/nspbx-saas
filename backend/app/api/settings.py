from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alcance
from app.core.auth import usuario_actual
from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import Queue, SystemSettings, User
from app.schemas import SystemSettingsOut, SystemSettingsUpdate
from app.services import esl
from app.services.ajustes import get_or_create_settings

router = APIRouter(prefix="/api/system", tags=["system"])

# Ajustes que NO son de una empresa sino de toda la plataforma: el Event
# Socket y la URL HTTP de FreeSWITCH, el dominio SIP (que identifica a la
# empresa dentro de FreeSWITCH), los topes de disco y los respaldos. Una
# empresa no los puede cambiar ni ver cuando hay varias en la instalación
# (ver app/core/alcance.py). Con una sola empresa siguen editables, como antes.
CAMPOS_GLOBALES = frozenset(
    {
        "fs_domain",
        "fs_esl_host",
        "fs_esl_port",
        "fs_esl_password",
        "fs_http_base",
        "recordings_max_gb",
        "backups_max_gb",
        "backup_enabled",
        "backup_retention_days",
        "ari_base_url",
        "ari_user",
        "ari_password",
        "ari_app",
    }
)

def apply_to_runtime(row: SystemSettings):
    """Vuelca a la config de proceso SOLO lo que es de infraestructura.

    `app_name` y `fs_domain` ya no están acá: cambian por empresa y
    volcarlos a un objeto único haría que la última empresa procesada
    pisara la configuración de todas las demás — un fallo dependiente del
    orden, que es de los peores de reproducir.

    Solo se llama con UNA empresa en la instalación (ver `alcance`): con
    varias, cada una tendría su propia fila y la última en llamarse
    reconfiguraría el Event Socket de todas. Una contraseña vacía no pisa la
    del entorno.
    """
    runtime_settings.fs_esl_host = row.fs_esl_host or runtime_settings.fs_esl_host
    runtime_settings.fs_esl_port = row.fs_esl_port or runtime_settings.fs_esl_port
    if row.fs_esl_password:
        runtime_settings.fs_esl_password = row.fs_esl_password
    runtime_settings.fs_http_base = row.fs_http_base or runtime_settings.fs_http_base


def _salida(row: SystemSettings, puede_infra: bool) -> SystemSettingsOut:
    out = SystemSettingsOut.model_validate(row)
    out.puede_infraestructura = puede_infra
    if not puede_infra:
        # Lo global no se muestra a una empresa: incluía la contraseña REAL del
        # Event Socket (sembrada en la fila de cada empresa) y el error de
        # pg_dump del respaldo de toda la base.
        out.fs_esl_host = ""
        out.fs_esl_port = 0
        out.fs_esl_password = ""
        out.fs_http_base = ""
        out.last_backup_error = None
        out.last_backup_at = None
        out.last_backup_ok = None
        out.ari_base_url = None
        out.ari_user = None
        out.ari_password = None
    return out


@router.get("/settings", response_model=SystemSettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)):
    row = await get_or_create_settings(session)
    return _salida(row, await alcance.instalacion_unica(session))


@router.put("/settings", response_model=SystemSettingsOut)
async def update_settings(
    payload: SystemSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    row = await get_or_create_settings(session)
    puede_infra = await alcance.instalacion_unica(session)
    cambios = payload.model_dump(exclude_unset=True)

    if not puede_infra:
        # El panel manda el formulario completo, así que no se rechaza: se
        # ignoran los campos globales (que la empresa nunca debió poder fijar).
        for campo in CAMPOS_GLOBALES:
            cambios.pop(campo, None)
    else:
        # Una contraseña vacía en el formulario significa "no la toqué".
        if not cambios.get("fs_esl_password"):
            cambios.pop("fs_esl_password", None)

    # La cola del widget de llamada web tiene que ser de ESTA empresa: el id
    # se valida con la sesión atada a la empresa (RLS), que no ve las ajenas.
    cola = cambios.get("webcall_queue_id")
    if cola and not await session.get(Queue, cola):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La cola indicada no existe")

    cambio_esl = any(k in cambios for k in ("fs_esl_host", "fs_esl_port", "fs_esl_password", "fs_http_base"))
    for field, value in cambios.items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    if puede_infra and cambio_esl:
        apply_to_runtime(row)
        await esl.invalidate_client()
    # El contexto de dialplan `webcall_<slug>` se genera según estos campos
    # (ver config_generator.build_dialplan_xml). Se sirve en vivo por
    # xml_curl, pero un reloadxml purga el árbol cacheado para que el
    # próximo lookup traiga el nuevo.
    if any(k.startswith("webcall_") for k in cambios):
        try:
            await esl.reloadxml()
        except Exception:
            pass
    return _salida(row, puede_infra)
