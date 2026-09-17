from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, tenant_de_sesion
from app.models import Tenant, Trunk
from app.schemas import TrunkCreate, TrunkOut, TrunkUpdate
from app.services import licensing
from app.services.esl import gateway_status, rescan_profile
from app.services.gateways import nombre_gateway, remove_gateway_file, write_gateway_file

router = APIRouter(prefix="/api/trunks", tags=["trunks"])


async def _slug_de(session: AsyncSession, tenant_id: int) -> str:
    ten = await session.get(Tenant, tenant_id)
    return ten.slug if ten else "x"


@router.get("", response_model=list[TrunkOut])
async def list_trunks(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Trunk).order_by(Trunk.id))
    return result.scalars().all()


@router.post("", response_model=TrunkOut, status_code=status.HTTP_201_CREATED)
async def create_trunk(payload: TrunkCreate, session: AsyncSession = Depends(get_session)):
    tid = tenant_de_sesion(session)
    if tid is not None:
        lic = await licensing.obtener(session, tid)
        if not await licensing.hay_cupo(session, lic, "max_trunks", await licensing.contar_troncales(session, tid)):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Alcanzaste el límite de troncales de tu plan. Mejora la licencia para agregar más.",
            )
    trunk = Trunk(**payload.model_dump())
    session.add(trunk)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre de troncal duplicado")
    await session.refresh(trunk)
    write_gateway_file(trunk, await _slug_de(session, trunk.tenant_id))
    try:
        await rescan_profile("external")
    except Exception:
        pass
    return trunk


@router.get("/{trunk_id}", response_model=TrunkOut)
async def get_trunk(trunk_id: int, session: AsyncSession = Depends(get_session)):
    trunk = await session.get(Trunk, trunk_id)
    if not trunk:
        raise HTTPException(status_code=404, detail="Troncal no encontrado")
    return trunk


@router.put("/{trunk_id}", response_model=TrunkOut)
async def update_trunk(
    trunk_id: int, payload: TrunkUpdate, session: AsyncSession = Depends(get_session)
):
    trunk = await session.get(Trunk, trunk_id)
    if not trunk:
        raise HTTPException(status_code=404, detail="Troncal no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(trunk, field, value)
    await session.commit()
    await session.refresh(trunk)
    write_gateway_file(trunk, await _slug_de(session, trunk.tenant_id))
    try:
        await rescan_profile("external")
    except Exception:
        pass
    return trunk


@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(trunk_id: int, session: AsyncSession = Depends(get_session)):
    trunk = await session.get(Trunk, trunk_id)
    if not trunk:
        raise HTTPException(status_code=404, detail="Troncal no encontrado")
    await session.delete(trunk)
    await session.commit()
    remove_gateway_file(nombre_gateway(trunk.name, await _slug_de(session, trunk.tenant_id)))
    try:
        await rescan_profile("external")
    except Exception:
        pass


@router.post("/{trunk_id}/rescan")
async def trunk_rescan(trunk_id: int, session: AsyncSession = Depends(get_session)):
    trunk = await session.get(Trunk, trunk_id)
    if not trunk:
        raise HTTPException(status_code=404, detail="Troncal no encontrado")
    try:
        out = await rescan_profile("external")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "gateway": nombre_gateway(trunk.name, await _slug_de(session, trunk.tenant_id)), "output": out}


@router.get("/{trunk_id}/status")
async def trunk_status(trunk_id: int, session: AsyncSession = Depends(get_session)):
    trunk = await session.get(Trunk, trunk_id)
    if not trunk:
        raise HTTPException(status_code=404, detail="Troncal no encontrado")
    try:
        return await gateway_status(nombre_gateway(trunk.name, await _slug_de(session, trunk.tenant_id)))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
