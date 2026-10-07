"""Consumo mensual por empresa: lo que se factura o se controla.

Un resumen por mes con minutos, conversaciones con IA y su costo
estimado, y el espacio de las grabaciones. Lo ven la empresa (lo suyo), la
plataforma (todas, para facturar) y las integraciones por /api/v1.

Los minutos que se cobran son los que salieron por una troncal
(`CallLog.via_trunk`): una llamada entre extensiones no le cuesta nada a
nadie. El costo de IA se estima con las tarifas de Ajustes de cada empresa,
igual que la pantalla de Consumo IA.
"""

import csv
import io
from datetime import datetime
from pathlib import Path

from sqlalchemy import case, func, select

from app.core.config import settings
from app.models import AiCallUsage, CallLog
from app.services.ajustes import ajustes_de


class MesInvalido(ValueError):
    pass


def rango_del_mes(mes: str | None) -> tuple[str, datetime, datetime]:
    """"AAAA-MM" (o vacío = el mes en curso) → (etiqueta, inicio, fin)."""
    if not mes:
        hoy = datetime.utcnow()
        anio, num = hoy.year, hoy.month
    else:
        try:
            anio, num = (int(p) for p in mes.split("-"))
            datetime(anio, num, 1)
        except (ValueError, TypeError):
            raise MesInvalido("El mes va como AAAA-MM")
    inicio = datetime(anio, num, 1)
    fin = datetime(anio + (num == 12), num % 12 + 1, 1)
    return f"{anio:04d}-{num:02d}", inicio, fin


def bytes_de_grabaciones(tenant_id: int) -> int:
    """Espacio que ocupan HOY las grabaciones de la empresa (no es del mes:
    lo que se guarda es lo que la retención no borró todavía)."""
    from app.services.config_generator import carpeta_grabaciones

    base = Path(settings.recordings_dir)
    archivos = list((base / carpeta_grabaciones(tenant_id)).glob("**/*.wav"))
    archivos += list(base.glob(f"queue_t{int(tenant_id)}_*.wav"))
    total = 0
    for f in archivos:
        try:
            total += f.stat().st_size
        except OSError:
            continue
    return total


async def resumen(session, tenant_id: int, mes: str | None) -> dict:
    from app.api.ai_usage import Tarifas, agregado, es_del_voizbot

    etiqueta, inicio, fin = rango_del_mes(mes)
    llamadas = (
        await session.execute(
            select(
                func.count(CallLog.id),
                func.count(case((CallLog.status == "answered", 1))),
                func.coalesce(func.sum(CallLog.billsec), 0),
                func.count(case((CallLog.via_trunk.is_(True), 1))),
                func.coalesce(func.sum(case((CallLog.via_trunk.is_(True), CallLog.billsec), else_=0)), 0),
            ).where(CallLog.tenant_id == tenant_id, CallLog.started_at >= inicio, CallLog.started_at < fin)
        )
    ).one()
    # Sumado en la base (ver ai_usage.agregado): un mes de una empresa grande
    # son decenas de miles de conversaciones.
    conversaciones = await agregado(
        session, AiCallUsage.tenant_id == tenant_id, AiCallUsage.started_at >= inicio, AiCallUsage.started_at < fin,
        de_la_sesion=False,
    )
    tarifas = Tarifas(await ajustes_de(session, tenant_id))
    return {
        "mes": etiqueta,
        "tenant_id": tenant_id,
        "llamadas": llamadas[0],
        "llamadas_contestadas": llamadas[1],
        "minutos_hablados": round(llamadas[2] / 60, 1),
        "llamadas_por_troncal": llamadas[3],
        "minutos_por_troncal": round(llamadas[4] / 60, 1),
        "conversaciones_ia": sum(c.calls for c in conversaciones if es_del_voizbot(c)),
        "minutos_ia": round(sum(c.duration_seconds or 0 for c in conversaciones) / 60, 1),
        "tts_caracteres": sum(c.tts_chars or 0 for c in conversaciones),
        "stt_segundos": sum(c.stt_seconds or 0 for c in conversaciones),
        "llm_tokens": sum((c.llm_prompt_tokens or 0) + (c.llm_completion_tokens or 0) for c in conversaciones),
        "costo_ia_usd": round(sum(tarifas.costo_llamada(c) for c in conversaciones), 4),
        "grabaciones_mb": round(bytes_de_grabaciones(tenant_id) / 1024 / 1024, 1),
    }


def _celda(valor):
    # Un nombre de empresa que empiece con "=" se ejecutaría como fórmula al
    # abrir el CSV en una hoja de cálculo.
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def a_csv(filas: list[dict]) -> str:
    if not filas:
        return ""
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=list(filas[0]))
    escritor.writeheader()
    escritor.writerows({k: _celda(v) for k, v in f.items()} for f in filas)
    return salida.getvalue()


def meses_anteriores(cantidad: int) -> list[str]:
    """Los últimos `cantidad` meses, el actual incluido, del más viejo al más nuevo."""
    hoy = datetime.utcnow()
    indice = hoy.year * 12 + hoy.month - 1
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(indice - cantidad + 1, indice + 1)]
