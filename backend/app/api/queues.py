import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Queue, Tenant
from app.schemas import QueueCreate, QueueUpdate
from app.services import esl
from app.services.ajustes import dominios_tenants
from app.services.queues_sync import parse_agents, remove_queue, sync_queue, write_callcenter_conf

router = APIRouter(prefix="/api/queues", tags=["queues"])


def _out(queue: Queue) -> dict:
    return {
        "id": queue.id,
        "name": queue.name,
        "extension": queue.extension,
        "strategy": queue.strategy,
        "moh_sound": queue.moh_sound,
        "agents": parse_agents(queue.agents),
        "max_wait_time": queue.max_wait_time,
        "max_wait_time_with_no_agent": queue.max_wait_time_with_no_agent,
        "agent_ring_timeout": queue.agent_ring_timeout,
        "max_no_answer": queue.max_no_answer,
        "wrap_up_time": queue.wrap_up_time,
        "record": queue.record,
        "failover_extension": queue.failover_extension,
        "announce_position": queue.announce_position,
        "enabled": queue.enabled,
        "created_at": queue.created_at,
    }


async def _dominio_de(session: AsyncSession, tenant_id: int) -> str:
    tenant = await session.get(Tenant, tenant_id)
    return tenant.sip_domain if tenant else "nspbx.local"


async def _rewrite_conf_file(session: AsyncSession) -> None:
    """Regenera callcenter.conf.xml completo (necesario porque los agentes
    se declaran ahí con todos sus parámetros) y refresca el árbol XML en
    memoria de FreeSWITCH. `reloadxml` NO reinicia mod_callcenter ni
    afecta colas ya cargadas — solo actualiza qué vería un `queue
    load/reload` posterior."""
    rows = (await session.execute(select(Queue))).scalars().all()
    dominios = await dominios_tenants(session)
    write_callcenter_conf(rows, dominios)
    try:
        await esl.api("reloadxml")
    except Exception:
        pass


@router.get("")
async def list_queues(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Queue).order_by(Queue.id))
    return [_out(q) for q in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_queue(payload: QueueCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump()
    agents = data.pop("agents")
    queue = Queue(**data, agents=json.dumps(agents))
    session.add(queue)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o extensión de cola duplicados")
    await session.refresh(queue)
    await _rewrite_conf_file(session)
    await sync_queue(queue, await _dominio_de(session, queue.tenant_id))
    return _out(queue)


@router.get("/{queue_id}")
async def get_queue(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    return _out(queue)


@router.put("/{queue_id}")
async def update_queue(queue_id: int, payload: QueueUpdate, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    old_name = queue.name
    data = payload.model_dump(exclude_unset=True)
    if "agents" in data:
        data["agents"] = json.dumps(data["agents"])
    for field, value in data.items():
        setattr(queue, field, value)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre o extensión de cola duplicados")
    await session.refresh(queue)
    await _rewrite_conf_file(session)
    if old_name != queue.name:
        # Si cambió el nombre, la cola vieja queda huérfana en mod_callcenter.
        await remove_queue(old_name, await _dominio_de(session, queue.tenant_id))
    await sync_queue(queue, await _dominio_de(session, queue.tenant_id))
    return _out(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_endpoint(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    name = queue.name
    dominio = await _dominio_de(session, queue.tenant_id)
    await session.delete(queue)
    await session.commit()
    await _rewrite_conf_file(session)
    await remove_queue(name, dominio)


@router.get("/{queue_id}/status")
async def queue_status(queue_id: int, session: AsyncSession = Depends(get_session)):
    """Consulta en vivo a mod_callcenter: agentes y llamadas en espera,
    para un panel tipo Issabel."""
    queue = await session.get(Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    qkey = f"{queue.name}@{await _dominio_de(session, queue.tenant_id)}"
    try:
        agents_raw = await esl.api(f"callcenter_config queue list agents {qkey}")
        tiers_raw = await esl.api(f"callcenter_config queue list tiers {qkey}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"agents": agents_raw, "tiers": tiers_raw}
