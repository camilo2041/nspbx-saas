"""Consumo del voizbot con IA: totales, serie diaria y detalle por llamada.

Las unidades vienen medidas de `ai_call_usage`; el dinero se calcula acá
con las tarifas de Ajustes, porque cambian según el plan contratado.

El gasto se agrupa POR PROVEEDOR y de forma dinámica: cada llamada guarda
con quién sintetizó la voz y con quién transcribió, así que una cuenta que
mezcle proveedores (por ejemplo voz gratis con transcripción de Deepgram)
se reparte bien sin tener que tocar código.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_local
from app.core.database import get_session
from app.models import AiCallUsage
from app.services.ajustes import ajustes_de

router = APIRouter(prefix="/api/ai-usage", tags=["ai-usage"])

ETIQUETAS = {
    "elevenlabs": "ElevenLabs",
    "deepgram": "Deepgram",
    "edge": "edge-tts",
}


class Tarifas:
    def __init__(self, row):
        self.tts = {
            "elevenlabs": float(getattr(row, "rate_tts_per_1k_chars", 0.0655) or 0),
            "deepgram": float(getattr(row, "rate_dg_tts_per_1k_chars", 0.030) or 0),
            "edge": 0.0,  # gratis
        }
        self.stt = {
            "elevenlabs": float(getattr(row, "rate_stt_per_minute", 0.0065) or 0),
            "deepgram": float(getattr(row, "rate_dg_stt_per_minute", 0.00483) or 0),
        }
        self.llm_in = float(getattr(row, "rate_llm_in_per_1m", 0.04) or 0)
        self.llm_out = float(getattr(row, "rate_llm_out_per_1m", 0.04) or 0)
        # El bloque del modelo se agrupa bajo el nombre que esté configurado
        # AHORA en Ajustes, no bajo un proveedor fijo — si ayer era DeepSeek
        # y hoy es OpenAI, el consumo histórico también aparece bajo el
        # nombre actual (mismo criterio que ya se usa para las tarifas:
        # se aplican las de hoy, no las de cuando se hizo la llamada).
        self.llm_provider = str(getattr(row, "ai_llm_provider_name", None) or "Modelo de lenguaje")

    def costo_tts(self, proveedor: str | None, chars: int) -> float:
        return round((chars or 0) / 1000 * self.tts.get(proveedor or "elevenlabs", 0), 5)

    def costo_stt(self, proveedor: str | None, segundos: int) -> float:
        return round((segundos or 0) / 60 * self.stt.get(proveedor or "elevenlabs", 0), 5)

    def costo_llm(self, tok_in: int, tok_out: int) -> float:
        return round((tok_in or 0) / 1_000_000 * self.llm_in + (tok_out or 0) / 1_000_000 * self.llm_out, 5)

    def costo_llamada(self, f) -> float:
        return round(
            self.costo_tts(f.tts_provider, f.tts_chars)
            + self.costo_stt(f.stt_provider, f.stt_seconds)
            + self.costo_llm(f.llm_prompt_tokens, f.llm_completion_tokens),
            5,
        )

    def as_dict(self) -> dict:
        return {
            "tts": self.tts,
            "stt": self.stt,
            "llm_in_per_1m": self.llm_in,
            "llm_out_per_1m": self.llm_out,
            "llm_provider": self.llm_provider,
        }


async def _tarifas(session: AsyncSession) -> Tarifas:
    return Tarifas(await ajustes_de(session))


def _agrupar_por_proveedor(filas, t: Tarifas) -> list[dict]:
    """Un bloque por proveedor con lo que consumió y lo que costó.

    Un mismo proveedor puede aportar por dos vías (Deepgram hace voz y
    transcripción), así que se acumulan juntas bajo su nombre."""
    acc: dict[str, dict] = {}

    def bloque(clave: str) -> dict:
        return acc.setdefault(
            clave,
            {
                "key": clave,
                "label": ETIQUETAS.get(clave, clave),
                "cost_usd": 0.0,
                "tts_chars": 0,
                "stt_seconds": 0,
                "tokens": 0,
                "requests": 0,
                "roles": set(),
            },
        )

    for f in filas:
        if f.tts_chars:
            b = bloque(f.tts_provider or "elevenlabs")
            b["tts_chars"] += f.tts_chars
            b["cost_usd"] += t.costo_tts(f.tts_provider, f.tts_chars)
            b["roles"].add("voz")
        if f.stt_seconds:
            b = bloque(f.stt_provider or "elevenlabs")
            b["stt_seconds"] += f.stt_seconds
            b["cost_usd"] += t.costo_stt(f.stt_provider, f.stt_seconds)
            b["roles"].add("transcripción")
        if f.llm_calls:
            b = bloque(t.llm_provider)
            b["tokens"] += (f.llm_prompt_tokens or 0) + (f.llm_completion_tokens or 0)
            b["requests"] += f.llm_calls
            b["cost_usd"] += t.costo_llm(f.llm_prompt_tokens, f.llm_completion_tokens)
            b["roles"].add("modelo")

    total = sum(b["cost_usd"] for b in acc.values())
    salida = []
    for b in acc.values():
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["share"] = round(b["cost_usd"] / total, 3) if total else 0
        b["role"] = " y ".join(sorted(b.pop("roles"))).capitalize()
        salida.append(b)
    return sorted(salida, key=lambda b: -b["cost_usd"])


@router.get("/summary")
async def summary(days: int = 30, session: AsyncSession = Depends(get_session)):
    desde = now_local() - timedelta(days=days)
    t = await _tarifas(session)
    filas = (
        await session.execute(select(AiCallUsage).where(AiCallUsage.started_at >= desde))
    ).scalars().all()

    llamadas = len(filas)
    resueltas = sum(1 for f in filas if f.resolved)
    turnos = sum(f.turns for f in filas)
    dur_s = sum(f.duration_seconds for f in filas)
    proveedores = _agrupar_por_proveedor(filas, t)
    costo = round(sum(b["cost_usd"] for b in proveedores), 4)

    return {
        "days": days,
        "calls": llamadas,
        "resolved": resueltas,
        # Tasa de contención: gestiones resueltas por el bot sin humano.
        # Es el número que justifica el costo frente a un cliente.
        "containment_rate": round(resueltas / llamadas, 3) if llamadas else 0,
        "talk_seconds": dur_s,
        "turns": turnos,
        "cost_usd": costo,
        "cost_per_call": round(costo / llamadas, 4) if llamadas else 0,
        "cost_per_resolved": round(costo / resueltas, 4) if resueltas else 0,
        "cost_per_minute": round(costo / (dur_s / 60), 4) if dur_s else 0,
        "avg_turns": round(turnos / llamadas, 1) if llamadas else 0,
        "avg_duration": round(dur_s / llamadas) if llamadas else 0,
        "providers": proveedores,
        "rates": t.as_dict(),
    }


@router.get("/daily")
async def daily(days: int = 14, session: AsyncSession = Depends(get_session)):
    """Serie por día, con los días sin llamadas rellenos en cero — si no,
    la gráfica junta días separados y miente sobre la tendencia."""
    t = await _tarifas(session)
    hoy = now_local().date()
    desde = hoy - timedelta(days=days - 1)

    filas = (
        await session.execute(select(AiCallUsage).where(AiCallUsage.started_at >= desde))
    ).scalars().all()

    por_dia: dict[str, dict] = {}
    for f in filas:
        d = f.started_at.date().isoformat()
        b = por_dia.setdefault(d, {"calls": 0, "tts_chars": 0, "stt_seconds": 0, "tokens": 0, "cost_voz": 0.0, "cost_modelo": 0.0})
        b["calls"] += 1
        b["tts_chars"] += f.tts_chars
        b["stt_seconds"] += f.stt_seconds
        b["tokens"] += (f.llm_prompt_tokens or 0) + (f.llm_completion_tokens or 0)
        # La gráfica separa "voz y transcripción" del "modelo": es el corte
        # que importa para decidir dónde recortar, y no cambia si mañana se
        # cambia de proveedor de voz.
        b["cost_voz"] += t.costo_tts(f.tts_provider, f.tts_chars) + t.costo_stt(f.stt_provider, f.stt_seconds)
        b["cost_modelo"] += t.costo_llm(f.llm_prompt_tokens, f.llm_completion_tokens)

    vacio = {"calls": 0, "tts_chars": 0, "stt_seconds": 0, "tokens": 0, "cost_voz": 0.0, "cost_modelo": 0.0}
    serie = []
    for i in range(days):
        d = (desde + timedelta(days=i)).isoformat()
        b = dict(por_dia.get(d, vacio))
        b["cost_voz"] = round(b["cost_voz"], 4)
        b["cost_modelo"] = round(b["cost_modelo"], 4)
        b["cost_usd"] = round(b["cost_voz"] + b["cost_modelo"], 4)
        serie.append({"date": d, **b})
    return serie


@router.get("/calls")
async def calls(
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """`offset` y `search` para poder mirar más atrás de las últimas 25:
    antes el tope era fijo y no había manera de llegar al consumo de una
    llamada anterior desde la interfaz."""
    t = await _tarifas(session)
    query = select(AiCallUsage)
    if search:
        query = query.where(AiCallUsage.phone.ilike(f"%{search.strip()}%"))
    query = query.order_by(AiCallUsage.started_at.desc()).limit(min(limit, 500)).offset(max(0, offset))
    filas = (await session.execute(query)).scalars().all()
    return [
        {
            "id": f.id,
            "phone": f.phone,
            "started_at": f.started_at,
            "duration_seconds": f.duration_seconds,
            "turns": f.turns,
            "tts_chars": f.tts_chars,
            "tts_provider": ETIQUETAS.get(f.tts_provider or "", f.tts_provider or "—"),
            "stt_seconds": f.stt_seconds,
            "stt_provider": ETIQUETAS.get(f.stt_provider or "", f.stt_provider or "—"),
            "tokens": (f.llm_prompt_tokens or 0) + (f.llm_completion_tokens or 0),
            "cost_voz": round(t.costo_tts(f.tts_provider, f.tts_chars) + t.costo_stt(f.stt_provider, f.stt_seconds), 5),
            "cost_modelo": t.costo_llm(f.llm_prompt_tokens, f.llm_completion_tokens),
            "outcome": f.outcome,
            "resolved": f.resolved,
            "cost_usd": t.costo_llamada(f),
        }
        for f in filas
    ]
