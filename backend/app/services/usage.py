"""Medición del consumo de una conversación con IA.

Una llamada del voizbot gasta en tres frentes a la vez — texto a voz, voz
a texto y el modelo de lenguaje — y hasta acá no quedaba registro de
ninguno: no se podía saber cuánto cuesta una llamada, ni por qué se agotó
una cuota, ni si el bot resolvió algo a cambio de ese gasto.

Se miden UNIDADES, no dinero. Los caracteres, los tokens y los segundos
son hechos; el costo depende del plan contratado y se calcula al
consultar, con las tarifas de Ajustes.
"""

import json
import logging

from app.core.clock import now_local
from app.core.database import async_session
from app.models import AiCallUsage

logger = logging.getLogger(__name__)

# Audio del STT: PCM de 16 bits a 8 kHz = 16.000 bytes por segundo.
STT_BYTES_PER_SECOND = 8000 * 2


class UsageMeter:
    """Acumula el consumo de UNA llamada y lo guarda al terminar."""

    def __init__(
        self,
        call_uuid: str,
        phone: str | None,
        tts_provider: str,
        stt_provider: str = "elevenlabs",
        tenant_id: int | None = None,
    ):
        self.call_uuid = call_uuid
        self.phone = phone
        self.tenant_id = tenant_id
        self.tts_provider = tts_provider
        self.stt_provider = stt_provider
        self.turns = 0
        self.tts_chars = 0
        self.stt_bytes = 0
        self.llm_calls = 0
        self.llm_prompt_tokens = 0
        self.llm_completion_tokens = 0
        self.outcome = "hangup"
        self.resolved = False
        # Qué hizo la llamada sobre la agenda, y una fotografía de esa
        # cita en ese instante — ver AiCallUsage en app/models/models.py.
        self.action: str | None = None
        self.appointment_id: int | None = None
        self.action_appointment_date = None
        self.action_patient_name: str | None = None
        self.started_at = now_local()

    def tts(self, texto: str) -> None:
        self.tts_chars += len(texto)

    def stt(self, pcm_bytes: int) -> None:
        self.stt_bytes += pcm_bytes

    def llm(self, uso: dict) -> None:
        self.llm_calls += 1
        self.llm_prompt_tokens += int(uso.get("prompt_tokens") or 0)
        self.llm_completion_tokens += int(uso.get("completion_tokens") or 0)

    async def save(self) -> None:
        """Nunca puede tumbar una llamada: si falla, se pierde la métrica
        pero la conversación ya terminó igual."""
        try:
            fin = now_local()
            async with async_session() as session:
                session.add(
                    AiCallUsage(
                        tenant_id=self.tenant_id,
                        call_uuid=self.call_uuid,
                        phone=self.phone,
                        turns=self.turns,
                        tts_chars=self.tts_chars,
                        tts_provider=self.tts_provider,
                        stt_provider=self.stt_provider,
                        stt_seconds=int(self.stt_bytes / STT_BYTES_PER_SECOND),
                        llm_calls=self.llm_calls,
                        llm_prompt_tokens=self.llm_prompt_tokens,
                        llm_completion_tokens=self.llm_completion_tokens,
                        outcome=self.outcome,
                        resolved=self.resolved,
                        action=self.action,
                        appointment_id=self.appointment_id,
                        action_appointment_date=self.action_appointment_date,
                        action_patient_name=self.action_patient_name,
                        duration_seconds=int((fin - self.started_at).total_seconds()),
                        started_at=self.started_at,
                        ended_at=fin,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("No se pudo guardar el consumo de la llamada %s", self.call_uuid)


def estimar_costo(fila, rate_tts_1k: float, rate_in_1m: float, rate_out_1m: float) -> float:
    """Costo estimado en USD a partir de las unidades medidas."""
    return (
        fila.tts_chars / 1000 * rate_tts_1k
        + fila.llm_prompt_tokens / 1_000_000 * rate_in_1m
        + fila.llm_completion_tokens / 1_000_000 * rate_out_1m
    )
