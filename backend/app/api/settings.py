from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.runtime_settings import runtime_settings
from app.models import SystemSettings
from app.schemas import SystemSettingsOut, SystemSettingsUpdate
from app.services import esl
from app.services.ajustes import get_or_create_settings

router = APIRouter(prefix="/api/system", tags=["system"])


def apply_to_runtime(row: SystemSettings):
    """Vuelca a la config de proceso SOLO lo que es de infraestructura.

    `app_name` y `fs_domain` ya no están acá: cambian por empresa y
    volcarlos a un objeto único haría que la última empresa procesada
    pisara la configuración de todas las demás — un fallo dependiente del
    orden, que es de los peores de reproducir.
    """
    runtime_settings.fs_esl_host = row.fs_esl_host
    runtime_settings.fs_esl_port = row.fs_esl_port
    runtime_settings.fs_esl_password = row.fs_esl_password
    runtime_settings.fs_http_base = row.fs_http_base


@router.get("/settings", response_model=SystemSettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)):
    return await get_or_create_settings(session)


@router.put("/settings", response_model=SystemSettingsOut)
async def update_settings(
    payload: SystemSettingsUpdate, session: AsyncSession = Depends(get_session)
):
    row = await get_or_create_settings(session)
    cambios = payload.model_dump(exclude_unset=True)
    for field, value in cambios.items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
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
    return row
