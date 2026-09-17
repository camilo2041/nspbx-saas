import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.config import settings
from app.services import esl

logger = logging.getLogger(__name__)

CALLCENTER_CONF_PATH = "autoload_configs/callcenter.conf.xml"


def parse_agents(agents_json: str | None) -> list[str]:
    if not agents_json:
        return []
    try:
        data = json.loads(agents_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(a).strip() for a in data if str(a).strip()]


# El dominio llega como parámetro y ya no sale de una variable de
# proceso. En mod_callcenter los nombres de cola y de agente son un
# espacio de nombres GLOBAL: con un dominio único, la cola "soporte" de
# una empresa y la de otra serían literalmente la misma cola y sus
# agentes atenderían llamadas cruzadas. El dominio por empresa es lo que
# las separa, así que tiene que viajar con cada cola en vez de ser un
# valor ambiente que la última empresa procesada deja pisado.
def _queue_key(name: str, dominio: str) -> str:
    return f"{name}@{dominio}"


def _agent_key(extension: str, dominio: str) -> str:
    return f"{extension}@{dominio}"


def build_callcenter_xml(queues: list, dominios: dict[int, str]) -> str:
    """Genera callcenter.conf.xml completo (settings + queues + agents +
    tiers) a partir de las colas en la base de datos. mod_callcenter solo
    permite declarar agentes con TODOS sus parámetros (max-no-answer,
    wrap-up-time, etc.) vía este archivo — el API en caliente
    (`callcenter_config`) solo ajusta agentes/tiers ya existentes. Por eso
    se regenera completo, pero se aplica con recargas DIRIGIDAS por cola
    (`queue load`/`reload`), no reiniciando el módulo — eso NO afecta a
    las demás colas activas (confirmado: recargar A no altera el estado
    de B)."""
    root = ET.Element("configuration", attrib={"name": "callcenter.conf", "description": "CallCenter"})
    ET.SubElement(root, "settings")

    queues_el = ET.SubElement(root, "queues")
    agents_el = ET.SubElement(root, "agents")
    tiers_el = ET.SubElement(root, "tiers")

    seen_agents: set[str] = set()

    for queue in queues:
        if not queue.enabled:
            continue
        qkey = _queue_key(queue.name, dominios[queue.tenant_id])
        queue_el = ET.SubElement(queues_el, "queue", attrib={"name": qkey})
        params = {
            "strategy": queue.strategy,
            "moh-sound": queue.moh_sound,
            "time-base-score": "system",
            "max-wait-time": str(queue.max_wait_time),
            "max-wait-time-with-no-agent": str(queue.max_wait_time_with_no_agent),
            "max-wait-time-with-no-agent-time-reached": "5",
            "tier-rules-apply": "false",
            "tier-rule-wait-second": "300",
            "tier-rule-wait-multiply-level": "true",
            "tier-rule-no-agent-no-wait": "false",
            "discard-abandoned-after": "60",
            "abandoned-resume-allowed": "false",
        }
        if queue.record:
            params["record-template"] = (
                "$${recordings_dir}/queue_"
                + queue.name
                + "_${strftime(%Y-%m-%d-%H-%M-%S)}_${caller_id_number}.wav"
            )
        for name, value in params.items():
            ET.SubElement(queue_el, "param", attrib={"name": name, "value": value})

        for ext in parse_agents(queue.agents):
            akey = _agent_key(ext, dominios[queue.tenant_id])
            if akey not in seen_agents:
                seen_agents.add(akey)
                contact = f"[leg_timeout={queue.agent_ring_timeout}]user/{ext}@{dominios[queue.tenant_id]}"
                ET.SubElement(
                    agents_el,
                    "agent",
                    attrib={
                        "name": akey,
                        "type": "callback",
                        "contact": contact,
                        "status": "Available",
                        "max-no-answer": str(queue.max_no_answer),
                        "wrap-up-time": str(queue.wrap_up_time),
                        "reject-delay-time": "2",
                        "busy-delay-time": "10",
                    },
                )
            ET.SubElement(tiers_el, "tier", attrib={"agent": akey, "queue": qkey, "level": "1", "position": "1"})

    return ET.tostring(root, encoding="unicode")


def write_callcenter_conf(queues: list, dominios: dict[int, str]) -> Path:
    path = Path(settings.fs_conf_dir) / CALLCENTER_CONF_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_callcenter_xml(queues, dominios), encoding="utf-8")
    logger.info("callcenter.conf.xml regenerado (%d colas)", len(queues))
    return path


async def _run(cmd: str) -> str:
    try:
        return await esl.api(cmd)
    except Exception as exc:
        logger.warning("callcenter_config falló (%s): %s", cmd, exc)
        return ""


async def _current_tier_agents(qkey: str) -> set[str]:
    raw = await _run(f"callcenter_config queue list tiers {qkey}")
    agents = set()
    for line in raw.strip().splitlines()[1:]:  # 1ra línea es el header
        parts = line.split("|")
        if len(parts) >= 2 and parts[1]:
            agents.add(parts[1])
    return agents


async def sync_queue(queue, dominio: str) -> None:
    """Aplica los cambios de UNA cola sin tocar las demás: borra los tiers
    que ya no correspondan y recarga (o carga por primera vez) solo esa
    cola en mod_callcenter."""
    qkey = _queue_key(queue.name, dominio)
    new_agents = {_agent_key(e, dominio) for e in parse_agents(queue.agents)} if queue.enabled else set()

    current_agents = await _current_tier_agents(qkey)
    for stale in current_agents - new_agents:
        await _run(f"callcenter_config tier del {qkey} {stale}")

    if not queue.enabled:
        await _run(f"callcenter_config queue unload {qkey}")
        return

    result = await _run(f"callcenter_config queue reload {qkey}")
    if "-ERR" in result:
        await _run(f"callcenter_config queue load {qkey}")


async def remove_queue(name: str, dominio: str) -> None:
    qkey = _queue_key(name, dominio)
    for agent in await _current_tier_agents(qkey):
        await _run(f"callcenter_config tier del {qkey} {agent}")
    await _run(f"callcenter_config queue unload {qkey}")


async def apply_queues(queues: list, dominios: dict[int, str]) -> None:
    """Reescribe callcenter.conf.xml completo y recarga XML, luego aplica
    (carga/recarga) cada cola habilitada de forma dirigida. Se usa al
    arrancar el backend, cuando mod_callcenter pierde todo su estado."""
    write_callcenter_conf(queues, dominios)
    await _run("reloadxml")
    for queue in queues:
        if queue.enabled:
            qkey = _queue_key(queue.name, dominios[queue.tenant_id])
            result = await _run(f"callcenter_config queue reload {qkey}")
            if "-ERR" in result:
                await _run(f"callcenter_config queue load {qkey}")
