"""Calidad de llamadas: evaluar llamadas grabadas contra los criterios de la
empresa, a mano o con una sugerencia de la IA que alguien revisa.

- Cada criterio se califica 0 (no cumple), 1 (a medias) o 2 (cumple), con un
  peso. El total es el % de lo posible: sum(peso * puntaje) / sum(peso * 2).
- La IA lee la transcripción de la grabación (Deepgram, guardada en
  CallLog.transcripcion para pagarla una sola vez) y propone puntajes y un
  comentario. No se guarda sola: la persona que evalúa la revisa y guarda.
"""

import json
import logging
import re
from datetime import datetime

from sqlalchemy import select

from app.models import CallLog, CriterioCalidad, Extension, User

logger = logging.getLogger(__name__)

PUNTAJE_MAX = 2
CRITERIOS_EJEMPLO = (
    ("Saludó y se presentó", "Dijo su nombre y el de la empresa al empezar."),
    ("Entendió lo que necesitaba el cliente", "Preguntó y confirmó el motivo de la llamada antes de responder."),
    ("Dio información correcta y completa", "Lo que dijo es correcto y no dejó dudas abiertas."),
    ("Fue amable y paciente", "Buen tono, no interrumpió, no apuró al cliente."),
    ("Cerró la llamada con los siguientes pasos", "Resumió lo acordado y se despidió."),
)


class ErrorCalidad(Exception):
    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


async def criterios(session, tenant_id: int, solo_activos: bool = True) -> list[CriterioCalidad]:
    """Los de la empresa; la primera vez se crean los de ejemplo."""
    filas = list((await session.execute(select(CriterioCalidad).order_by(CriterioCalidad.orden, CriterioCalidad.id))).scalars())
    if not filas:
        for i, (nombre, descripcion) in enumerate(CRITERIOS_EJEMPLO):
            session.add(CriterioCalidad(tenant_id=tenant_id, nombre=nombre, descripcion=descripcion, peso=1, orden=i))
        await session.flush()
        filas = list((await session.execute(select(CriterioCalidad).order_by(CriterioCalidad.orden, CriterioCalidad.id))).scalars())
    return [c for c in filas if c.activo or not solo_activos]


def total(puntajes: dict[str, int], lista: list[CriterioCalidad]) -> float:
    posible = sum(c.peso * PUNTAJE_MAX for c in lista)
    logrado = sum(c.peso * max(0, min(PUNTAJE_MAX, int(puntajes.get(str(c.id), 0)))) for c in lista)
    return round(100.0 * logrado / posible, 1) if posible else 0.0


def validar_puntajes(puntajes: dict, lista: list[CriterioCalidad]) -> dict[str, int]:
    """Un puntaje 0-2 por cada criterio activo, ni más ni menos."""
    ids = {str(c.id) for c in lista}
    limpios = {str(k): v for k, v in (puntajes or {}).items()}
    if set(limpios) != ids:
        raise ErrorCalidad("Califica todos los criterios (y solo esos)", 422)
    for v in limpios.values():
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= PUNTAJE_MAX:
            raise ErrorCalidad("Cada criterio va de 0 a 2", 422)
    return limpios


async def agente_de(session, call: CallLog) -> int | None:
    """Quién atendió: el agente de la campaña, quien la tomó en el grupo o
    la extensión de la llamada."""
    if call.agente_id:
        return call.agente_id
    for numero in (call.cola_agente, call.callee_number, call.caller_number):
        if not numero or not numero.isdigit() or len(numero) > 6:
            continue
        uid = (
            await session.execute(
                select(User.id).join(Extension, Extension.id == User.extension_id).where(Extension.number == numero).limit(1)
            )
        ).scalar_one_or_none()
        if uid:
            return uid
    return None


async def _anotar_uso(session, call: CallLog, stt_segundos: int = 0, uso_llm: dict | None = None) -> None:
    """Lo que gastó la IA en esta llamada, en Consumo IA (origen «calidad»)."""
    import secrets

    from app.models import AiCallUsage

    uso_llm = uso_llm or {}
    session.add(AiCallUsage(
        tenant_id=call.tenant_id, call_uuid=f"calidad-{call.id}-{secrets.token_hex(4)}", origen="calidad",
        stt_provider="deepgram" if stt_segundos else None, stt_seconds=int(stt_segundos or 0),
        llm_calls=1 if uso_llm is not None and (uso_llm.get("prompt_tokens") or uso_llm.get("completion_tokens")) else 0,
        llm_prompt_tokens=int(uso_llm.get("prompt_tokens") or 0),
        llm_completion_tokens=int(uso_llm.get("completion_tokens") or 0),
        outcome="completed", started_at=datetime.utcnow(),
    ))


async def transcripcion(session, call: CallLog) -> list[dict]:
    """La de la grabación; se transcribe (y se guarda) la primera vez."""
    if call.transcripcion:
        return call.transcripcion
    from app.api.calls import _local_recording_path
    from app.services import deepgram
    from app.services.ajustes import ajustes_de

    local = _local_recording_path(call.recording_path) if call.recording_path else None
    if local is None or not local.exists():
        raise ErrorCalidad("La llamada no tiene grabación", 404)
    ajustes = await ajustes_de(session)
    clave = (ajustes.deepgram_api_key if ajustes else None) or ""
    if not clave:
        raise ErrorCalidad("Falta la API key de Deepgram en Ajustes para transcribir", 400)
    try:
        turnos = await deepgram.transcribir_grabacion(local.read_bytes(), clave)
    except Exception as exc:
        logger.exception("No se pudo transcribir la llamada %s", call.id)
        raise ErrorCalidad(f"No se pudo transcribir la grabación: {exc}", 502) from None
    call.transcripcion = turnos or []
    # Deepgram cobra por minuto de audio: el de la grabación entera.
    await _anotar_uso(session, call, stt_segundos=call.billsec or call.duration or 0)
    await session.commit()
    return call.transcripcion


def _json_de(texto: str) -> dict:
    """El primer objeto JSON de la respuesta del modelo (a veces lo envuelve
    en ```json … ``` o le agrega una frase)."""
    m = re.search(r"\{.*\}", texto or "", re.DOTALL)
    if not m:
        raise ValueError("sin JSON")
    return json.loads(m.group(0))


async def sugerir(session, call: CallLog, lista: list[CriterioCalidad]) -> dict:
    """Puntajes y comentario que propone la IA (no se guardan)."""
    from app.services import llm
    from app.services.ajustes import ajustes_de

    turnos = await transcripcion(session, call)
    if not turnos:
        raise ErrorCalidad("La grabación no tiene voz reconocible", 422)
    ajustes = await ajustes_de(session)
    base = (getattr(ajustes, "ai_llm_base_url", None) if ajustes else None) or "https://api.deepseek.com/v1"
    modelo = (getattr(ajustes, "ai_llm_model", None) if ajustes else None) or "deepseek-chat"
    clave = (getattr(ajustes, "ai_llm_api_key", None) if ajustes else None) or ""
    if not clave:
        raise ErrorCalidad("Falta la API key del modelo de lenguaje en Ajustes", 400)
    charla = "\n".join(f"{t.get('rol', '?').upper()}: {t.get('texto', '')}" for t in turnos)[:20000]
    lista_txt = "\n".join(f'- id {c.id}: {c.nombre}{f" ({c.descripcion})" if c.descripcion else ""}' for c in lista)
    try:
        mensaje, uso = await llm.chat(
            base, modelo, clave,
            [
                {
                    "role": "system",
                    "content": (
                        "Evalúas la calidad de la atención en llamadas de un call center, para que un supervisor "
                        "lo revise. Para cada criterio pon 2 si se cumplió, 1 si se cumplió a medias y 0 si no. "
                        "La transcripción es automática y los hablantes vienen numerados: deduce quién es el "
                        "agente y quién el cliente por el contenido. Si algo no se puede saber por la "
                        "transcripción, pon 1 y dilo en el comentario. Responde SOLO un JSON: "
                        '{"puntajes": {"<id>": 0|1|2, ...}, "comentario": "<máximo 3 frases en español, '
                        'concretas: qué hizo bien y qué mejorar>"}'
                    ),
                },
                {"role": "user", "content": f"Criterios:\n{lista_txt}\n\nTranscripción:\n{charla}"},
            ],
            tool_choice="none",
            tools=[],
        )
        await _anotar_uso(session, call, uso_llm=uso)
        await session.commit()
        datos = _json_de(mensaje.get("content") or "")
    except Exception as exc:
        logger.warning("La IA no pudo evaluar la llamada %s: %s", call.id, exc)
        raise ErrorCalidad(f"La IA no pudo evaluar la llamada: {exc}", 502) from None
    crudos = datos.get("puntajes") if isinstance(datos.get("puntajes"), dict) else {}
    puntajes = {}
    for c in lista:
        try:
            puntajes[str(c.id)] = max(0, min(PUNTAJE_MAX, int(crudos.get(str(c.id), 1))))
        except (TypeError, ValueError):
            puntajes[str(c.id)] = 1
    return {
        "puntajes": puntajes,
        "comentario": str(datos.get("comentario") or "").strip()[:1000],
        "total_pct": total(puntajes, lista),
    }
