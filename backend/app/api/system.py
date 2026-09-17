import asyncio
import socket
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models import Tenant, Trunk
from app.services import network
from app.services.ajustes import ajustes_de
from app.services.esl import gateway_status, internal_profile_ip
from app.services.esl import status as fs_status
from app.services.gateways import nombre_gateway
from app.workers.maintenance import maintenance

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
async def system_status():
    try:
        return await fs_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")


@router.get("/detect-ip")
async def detect_ip():
    """Autodetección para llenar los campos de IP de Ajustes con un clic
    en vez de tener que buscarlas a mano (ipconfig/ip addr, o peor,
    esperar a que alguien reporte que las llamadas no entran). La IP LAN
    sale de FreeSWITCH (ver internal_profile_ip): un truco de socket
    hecho desde este contenedor da la red interna de Docker, no la LAN
    real — quedó comprobado en vivo que en Docker Desktop están aisladas.
    Si FreeSWITCH no responde, cae al truco de socket como mejor esfuerzo
    (funciona bien en despliegues sin ese aislamiento, ej. sin Docker)."""
    pub_task = network.public_ip()
    try:
        lan = await internal_profile_ip()
    except Exception:
        lan = None
    if not lan:
        lan = await asyncio.to_thread(network.lan_ip)
    return {"lan_ip": lan, "public_ip": await pub_task}


async def _puerto_abierto(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (OSError, asyncio.TimeoutError, socket.gaierror):
        return False


@router.get("/diagnostics")
async def diagnostics(session: AsyncSession = Depends(get_session)):
    """Todo lo que hoy solo se podía ver entrando por consola a revisar
    logs y `sofia status`, en un solo vistazo: si FreeSWITCH responde, si
    el WebSocket del softphone está escuchando, la IP pública real de
    este servidor, y — el punto ciego que más dolió — si cada troncal le
    está anunciando al proveedor una IP por la que jamás podría recibir
    una llamada real (privada, loopback o CGNAT), algo que un simple
    "REGED" no revela porque el proveedor no valida esa dirección."""
    fila = await ajustes_de(session)
    esl_host = fila.fs_esl_host if fila else settings.fs_esl_host

    esl_task = fs_status()
    ws_task = _puerto_abierto(esl_host, 7443)
    ip_task = network.public_ip()
    trunks_result = await session.execute(select(Trunk).where(Trunk.enabled.is_(True)).order_by(Trunk.id))
    trunks = trunks_result.scalars().all()
    slugs = {t.id: t.slug for t in (await session.execute(select(Tenant))).scalars().all()}

    esl_ok = True
    try:
        await esl_task
    except Exception:
        esl_ok = False
    ws_ok = await ws_task
    ip_publica = await ip_task

    troncales = []
    for t in trunks:
        try:
            g = await gateway_status(nombre_gateway(t.name, slugs.get(t.tenant_id, "x")))
        except Exception:
            g = {"state": None, "status": None, "contact_ip": None}
        troncales.append(
            {
                "id": t.id,
                "name": t.name,
                "gateway_host": t.gateway_host,
                "register_enabled": t.register_enabled,
                "state": g.get("state"),
                "status": g.get("status"),
                "contact_ip": g.get("contact_ip"),
                "contact_no_alcanzable": network.ip_parece_no_alcanzable(g.get("contact_ip")),
            }
        )

    return {
        "esl_ok": esl_ok,
        "sip_ws_ok": ws_ok,
        "public_ip": ip_publica,
        "trunks": troncales,
    }


def _tamano_carpeta(carpeta: Path) -> tuple[int, int]:
    """(cantidad de archivos, bytes totales). No falla si algún archivo
    desaparece a mitad de la cuenta (el limpiador de retención puede
    correr al mismo tiempo)."""
    total = 0
    cantidad = 0
    if not carpeta.exists():
        return 0, 0
    # rglob (recursivo) y no iterdir: las grabaciones viven en subcarpetas
    # AAAA/MM/DD (ver config_generator.py) — con un listado plano, el
    # tamaño de "grabaciones" mostrado en Ajustes quedaba siempre en 0.
    for f in carpeta.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
                cantidad += 1
        except FileNotFoundError:
            continue
    return cantidad, total


@router.get("/maintenance")
async def maintenance_status(session: AsyncSession = Depends(get_session)):
    """Lo que antes no se podía ver sin entrar al servidor a mano: si el
    último respaldo salió bien, cuántos hay guardados, y cuánto disco
    ocupan las grabaciones frente al tope configurado."""
    row = await ajustes_de(session)

    n_backups, bytes_backups = _tamano_carpeta(Path(settings.backups_dir))
    n_grabaciones, bytes_grabaciones = _tamano_carpeta(Path(settings.recordings_dir))

    return {
        "backup_enabled": row.backup_enabled if row else True,
        "backup_retention_days": row.backup_retention_days if row else 14,
        "last_backup_at": row.last_backup_at if row else None,
        "last_backup_ok": row.last_backup_ok if row else None,
        "last_backup_error": row.last_backup_error if row else None,
        "backups_count": n_backups,
        "backups_size_mb": round(bytes_backups / (1024 * 1024), 1),
        "recordings_retention_days": row.recordings_retention_days if row else 90,
        "recordings_max_gb": row.recordings_max_gb if row else 20.0,
        "recordings_count": n_grabaciones,
        "recordings_size_gb": round(bytes_grabaciones / (1024 ** 3), 2),
    }


@router.post("/maintenance/backup-now")
async def backup_now():
    """Respaldo manual, para antes de un cambio riesgoso — no hace falta
    esperar a la corrida automática ni a que pasen las 24 horas."""
    await maintenance.respaldar_ahora()
    return {"ok": True}


def _uso_disco(punto: str, nombre: str) -> dict | None:
    try:
        u = psutil.disk_usage(punto)
    except OSError:
        return None
    return {
        "nombre": nombre,
        "punto": punto,
        "total_gb": round(u.total / (1024 ** 3), 1),
        "usado_gb": round(u.used / (1024 ** 3), 1),
        "libre_gb": round(u.free / (1024 ** 3), 1),
        "porcentaje": u.percent,
    }


def _leer_recursos() -> dict:
    """Bloqueante a propósito (psutil no tiene API async): se llama desde
    un hilo aparte (ver el endpoint) para no trabar el loop de asyncio
    mientras psutil.cpu_percent muestrea."""
    cpu_total = psutil.cpu_percent(interval=0.3)
    cpu_nucleos = psutil.cpu_percent(interval=0, percpu=True)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    discos = []
    # "/" es el disco propio del contenedor (su capa overlay); las
    # grabaciones y respaldos viven en volúmenes montados desde la
    # máquina real (ver docker-compose.yml) — en Docker Desktop / Windows
    # confirmado que son dos discos DISTINTOS (el de la VM de Docker vs.
    # el C:\ real), así que reportar solo "/" daría una cifra que no
    # tiene nada que ver con lo que de verdad se puede llenar.
    contenedor = _uso_disco("/", "Contenedor (backend)")
    if contenedor:
        discos.append(contenedor)
    datos = _uso_disco(settings.recordings_dir, "Datos (grabaciones y respaldos)")
    # Evita el duplicado si en algún despliegue coincidieran (ej. corriendo
    # sin Docker, todo en el mismo disco) — se comparan tamaño y uso, no
    # el punto de montaje, porque adentro del contenedor son rutas
    # distintas aunque apunten al mismo disco físico.
    ya_esta = contenedor and datos and contenedor["total_gb"] == datos["total_gb"] and contenedor["usado_gb"] == datos["usado_gb"]
    if datos and not ya_esta:
        discos.append(datos)

    return {
        "cpu": {
            "porcentaje": cpu_total,
            "nucleos": len(cpu_nucleos) or (psutil.cpu_count() or 1),
            "por_nucleo": cpu_nucleos,
        },
        "memoria": {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "usado_gb": round(mem.used / (1024 ** 3), 2),
            "disponible_gb": round(mem.available / (1024 ** 3), 2),
            "porcentaje": mem.percent,
        },
        "swap": {
            "total_gb": round(swap.total / (1024 ** 3), 2),
            "usado_gb": round(swap.used / (1024 ** 3), 2),
            "porcentaje": swap.percent,
        },
        "discos": discos,
    }


@router.get("/recursos")
async def recursos():
    """CPU, RAM, swap y disco de la máquina que hospeda todo esto — lo
    que antes había que revisar entrando al servidor a mano (o al
    Administrador de tareas de Windows) para saber si hay margen antes de
    prender otra campaña o si el disco se está por llenar."""
    return await asyncio.to_thread(_leer_recursos)
