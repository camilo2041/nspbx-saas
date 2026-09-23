from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import OutboundRoute, Trunk
from app.schemas import OutboundRouteCreate, OutboundRouteOut, OutboundRouteUpdate
from app.services.esl import reloadxml

router = APIRouter(prefix="/api/outbound-routes", tags=["outbound-routes"])


@router.get("", response_model=list[OutboundRouteOut])
async def list_routes(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OutboundRoute).order_by(OutboundRoute.priority, OutboundRoute.id))
    return result.scalars().all()


async def _validar_troncales(session: AsyncSession, trunk_ids: str | None) -> None:
    """Las troncales referidas tienen que ser de ESTA empresa.

    La sesión ya aplica el aislamiento por empresa, así que basta con
    comprobar que aparezcan: una troncal de otra empresa simplemente no
    se encuentra. Se valida al guardar y no solo al generar el dialplan
    porque una regla que apunta a una troncal inexistente se omite en
    silencio, y el síntoma —"esas llamadas no salen"— no señala la causa.
    """
    pedidos = [int(t) for t in (trunk_ids or "").split(",") if t.strip().isdigit()]
    if not pedidos:
        return
    existentes = set(
        (await session.execute(select(Trunk.id).where(Trunk.id.in_(pedidos)))).scalars().all()
    )
    faltan = [i for i in pedidos if i not in existentes]
    if faltan:
        raise HTTPException(
            status_code=422,
            detail=f"No existe la troncal {', '.join(str(i) for i in faltan)} en esta empresa",
        )


async def _aplicar(session: AsyncSession) -> None:
    await session.commit()
    # Una ruta que no se refleja en FreeSWITCH es peor que no tenerla: en
    # el panel figura y las llamadas siguen saliendo por donde antes.
    try:
        await reloadxml()
    except Exception:
        pass


@router.post("", response_model=OutboundRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(payload: OutboundRouteCreate, session: AsyncSession = Depends(get_session)):
    await _validar_troncales(session, payload.trunk_ids)
    route = OutboundRoute(**payload.model_dump())
    session.add(route)
    await _aplicar(session)
    await session.refresh(route)
    return route


@router.get("/{route_id}", response_model=OutboundRouteOut)
async def get_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    return route


@router.put("/{route_id}", response_model=OutboundRouteOut)
async def update_route(route_id: int, payload: OutboundRouteUpdate, session: AsyncSession = Depends(get_session)):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    cambios = payload.model_dump(exclude_unset=True)
    # El patrón y los dígitos a quitar se validan JUNTOS: cambiar solo uno
    # puede dejar una combinación imposible ("quitar 3" sobre un patrón de
    # 2 símbolos), y por separado cada valor parece correcto.
    from app.core import validacion

    patron_final = cambios.get("pattern", route.pattern)
    quitar_final = cambios.get("strip_digits", route.strip_digits)
    try:
        validacion.patron_marcado_a_regex(patron_final, quitar_final or 0)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if "trunk_ids" in cambios:
        await _validar_troncales(session, cambios["trunk_ids"])
    for field, value in cambios.items():
        setattr(route, field, value)
    await _aplicar(session)
    await session.refresh(route)
    return route


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: int, session: AsyncSession = Depends(get_session)):
    route = await session.get(OutboundRoute, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    await session.delete(route)
    await _aplicar(session)
