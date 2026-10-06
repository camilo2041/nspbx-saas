import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, get_session, traer_propio
from app.models import Queue, Tenant
from app.schemas import QueueCreate, QueueUpdate
from app.services import esl
from app.services.ajustes import dominios_tenants
from app.services.numeracion import numero_en_uso
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


# Dos empresas guardando una cola a la vez pisaban el mismo archivo.
_escritura_conf = asyncio.Lock()


async def _rewrite_conf_file(session: AsyncSession) -> None:
    """Regenera callcenter.conf.xml completo (necesario porque los agentes
    se declaran ahí con todos sus parámetros) y refresca el árbol XML en
    memoria de FreeSWITCH. `reloadxml` NO reinicia mod_callcenter ni
    afecta colas ya cargadas — solo actualiza qué vería un `queue
    load/reload` posterior."""
    # callcenter.conf.xml es UN archivo para TODAS las empresas. La sesión de la
    # petición está atada a una sola (aislamiento por empresa) y solo ve SUS colas:
    # regenerarlo con ella borraba las de todas las demás hasta el siguiente
    # reinicio. Se lee con la sesión del DUEÑO, que ve todas.
    async with _escritura_conf:
        async with async_session() as admin:
            rows = (await admin.execute(select(Queue))).scalars().all()
            dominios = await dominios_tenants(admin)
        write_callcenter_conf(rows, dominios)
        try:
            await esl.api("reloadxml")
        except Exception:
            pass


async def _exigir_numeros_libres(
    session: AsyncSession, numero: str | None, desborde: str | None, queue_id: int | None = None, numero_propio: str | None = None
) -> None:
    """El número de la cola no puede ser el de una extensión ni el de otra
    cola (la extensión se evalúa antes en el dialplan y la cola quedaba
    inalcanzable), y el desborde no puede ser la propia cola (bucle)."""
    if numero and (uso := await numero_en_uso(session, numero, salvo_cola=queue_id)):
        raise HTTPException(status_code=409, detail=f"El número {numero} ya lo usa {uso}")
    if desborde and desborde == (numero_propio or numero):
        raise HTTPException(status_code=400, detail="El desborde no puede ser la misma cola")


async def _todas(session: AsyncSession) -> list[Queue]:
    """Las colas de la empresa: los parámetros de un agente salen de todos
    sus grupos (queues_sync.parametros_agente)."""
    return list((await session.execute(select(Queue))).scalars().all())


@router.get("")
async def list_queues(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Queue).order_by(Queue.id))
    return [_out(q) for q in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_queue(payload: QueueCreate, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump()
    await _exigir_numeros_libres(session, data["extension"], data.get("failover_extension"))
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
    await sync_queue(queue, await _dominio_de(session, queue.tenant_id), await _todas(session))
    return _out(queue)


@router.get("/{queue_id}")
async def get_queue(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await traer_propio(session, Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    return _out(queue)


@router.put("/{queue_id}")
async def update_queue(queue_id: int, payload: QueueUpdate, session: AsyncSession = Depends(get_session)):
    queue = await traer_propio(session, Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    old_name = queue.name
    data = payload.model_dump(exclude_unset=True)
    nuevo_numero = data.get("extension")
    await _exigir_numeros_libres(
        session,
        nuevo_numero if nuevo_numero and nuevo_numero != queue.extension else None,
        data.get("failover_extension", queue.failover_extension) or None,
        queue_id=queue.id,
        numero_propio=nuevo_numero or queue.extension,
    )
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
    await sync_queue(queue, await _dominio_de(session, queue.tenant_id), await _todas(session))
    return _out(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_endpoint(queue_id: int, session: AsyncSession = Depends(get_session)):
    queue = await traer_propio(session, Queue, queue_id)
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
    queue = await traer_propio(session, Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Cola no encontrada")
    qkey = f"{queue.name}@{await _dominio_de(session, queue.tenant_id)}"
    try:
        agents_raw = await esl.api(f"callcenter_config queue list agents {qkey}")
        tiers_raw = await esl.api(f"callcenter_config queue list tiers {qkey}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"agents": agents_raw, "tiers": tiers_raw}
