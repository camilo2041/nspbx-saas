from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import alcance, validacion
from app.core.database import get_session
from app.models import InboundRoute
from app.schemas import InboundRouteCreate, InboundRouteOut, InboundRouteUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/inbound-routes", tags=["inbound-routes"])


@router.get("", response_model=list[InboundRouteOut])
async def list_routes(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(InboundRoute).order_by(InboundRoute.priority, InboundRoute.id))
    return result.scalars().all()


async def _validar_comodin(session: AsyncSession, did: str | None) -> None:
    """El comodín "any" recibe TODA llamada que no coincida con ningún DID, y el
    contexto de entrada es compartido por todas las empresas: con varias, una que
    lo reclame se queda con las llamadas de las demás. Solo se permite cuando la
    instalación tiene una única empresa."""
    if did == "any" and not await alcance.instalacion_unica(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El comodín \"any\" captura las llamadas de todas las empresas; pídele a quien "
            "administra la plataforma que te asigne números concretos.",
        )


async def _guardar(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # El número entrante es único en toda la plataforma (ver InboundRoute).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese número entrante ya está asignado a una ruta")


@router.post("", response_model=InboundRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: InboundRouteCreate, session: AsyncSession = Depends(get_session)):
    await _validar_comodin(session, payload.did_pattern)
    route = InboundRoute(**payload.model_dump())
    session.add(route)
    await _guardar(session)
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
    await _validar_comodin(session, cambios.get("did_pattern"))
    for field, value in cambios.items():
        setattr(route, field, value)
    await _guardar(session)
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
