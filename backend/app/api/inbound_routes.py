from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validacion
from app.core.database import get_session
from app.models import InboundRoute
from app.schemas import InboundRouteCreate, InboundRouteOut, InboundRouteUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/inbound-routes", tags=["inbound-routes"])


@router.get("", response_model=list[InboundRouteOut])
async def list_routes(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(InboundRoute).order_by(InboundRoute.priority, InboundRoute.id))
    return result.scalars().all()


@router.post("", response_model=InboundRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: InboundRouteCreate, session: AsyncSession = Depends(get_session)):
    route = InboundRoute(**payload.model_dump())
    session.add(route)
    await session.commit()
    await session.refresh(route)
    try:
        await reloadxml()
    except Exception:
        pass
    return route


@router.get("/{route_id}", response_model=InboundRouteOut)
async def get_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return route


@router.put("/{route_id}", response_model=InboundRouteOut)
async def update_route(route_id: int, payload: InboundRouteUpdate, session: AsyncSession = Depends(get_session)):
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    cambios = payload.model_dump(exclude_unset=True)
    # Un PUT parcial puede cambiar solo el tipo o solo el valor: lo que
    # importa es que el resultado FINAL sea coherente (ej. pasar a "cola"
    # dejando un "bot_3" de voizbot).
    tipo_final = cambios.get("destination_type", route.destination_type)
    valor_final = cambios.get("destination_value", route.destination_value)
    if tipo_final == "hangup":
        cambios["destination_value"] = None
    elif not validacion.destino_valido(tipo_final, valor_final):
        raise HTTPException(
            status_code=422,
            detail="El destino no corresponde al tipo: extensión (dígitos), cola (número) o voizbot (bot_N)",
        )
    for field, value in cambios.items():
        setattr(route, field, value)
    await session.commit()
    await session.refresh(route)
    try:
        await reloadxml()
    except Exception:
        pass
    return route


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(InboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    await session.delete(route)
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass
