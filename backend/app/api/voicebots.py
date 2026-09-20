import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limitador, validacion
from app.core.auth import usuario_actual
from app.core.database import get_session, tenant_de_sesion
from app.core import permissions
from app.core.clock import now_local
from app.models import Appointment, Debt, User, VoiceBot
from app.schemas import (
    VoiceBotCreate,
    VoiceBotFlowUpdate,
    VoiceBotNodeTtsRequest,
    VoiceBotOut,
    VoiceBotTtsRequest,
    VoiceBotUpdate,
)
from app.services import bot_sim, deepgram, greetings, tts, tts_elevenlabs
from app.services.ajustes import ajustes_de
from app.services.esl import reloadxml
from app.services.flow_engine import legacy_flow_from_bot

router = APIRouter(prefix="/api/voicebots", tags=["voicebots"])


async def _get_elevenlabs_key(session: AsyncSession) -> str:
    row = await ajustes_de(session)
    return (row.elevenlabs_api_key if row else None) or ""


async def _synthesize(text: str, voice: str, provider: str, session: AsyncSession) -> tuple[bytes, str]:
    """Devuelve (audio, extensión). ElevenLabs y Deepgram entregan WAV
    (PCM 16 kHz) y edge-tts entrega MP3 24 kHz — todos formatos que
    FreeSWITCH reproduce bien en una llamada de 8 kHz."""
    if provider == "elevenlabs":
        api_key = await _get_elevenlabs_key(session)
        return await tts_elevenlabs.synthesize(text, voice, api_key), "wav"
    if provider == "deepgram":
        row = await ajustes_de(session)
        return await deepgram.synthesize(text, voice, (row.deepgram_api_key if row else None) or ""), "wav"
    return await tts.synthesize(text, voice), "mp3"


@router.get("/tts/voices")
async def list_tts_voices(provider: str = "edge", session: AsyncSession = Depends(get_session)):
    if provider == "elevenlabs":
        api_key = await _get_elevenlabs_key(session)
        try:
            return await tts_elevenlabs.list_voices(api_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Error consultando ElevenLabs: {exc}")
    if provider == "deepgram":
        # Lista fija: los modelos de Aura-2 son fijos, no dependen de la
        # cuenta como las voces de ElevenLabs.
        return await deepgram.list_voices()
    return tts.SPANISH_VOICES


@router.get("", response_model=list[VoiceBotOut])
async def list_voicebots(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(VoiceBot).order_by(VoiceBot.id))
    return result.scalars().all()


@router.post("", response_model=VoiceBotOut, status_code=status.HTTP_201_CREATED)
async def create_voicebot(payload: VoiceBotCreate, session: AsyncSession = Depends(get_session)):
    if payload.bot_type not in ("ivr", "ai"):
        raise HTTPException(status_code=400, detail="bot_type debe ser 'ivr' o 'ai'")
    bot = VoiceBot(**payload.model_dump())
    session.add(bot)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre de bot duplicado")
    await session.refresh(bot)
    return bot


@router.get("/{bot_id}", response_model=VoiceBotOut)
async def get_voicebot(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    return bot


@router.put("/{bot_id}", response_model=VoiceBotOut)
async def update_voicebot(
    bot_id: int, payload: VoiceBotUpdate, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bot, field, value)
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voicebot(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    await session.delete(bot)
    await session.commit()
    greetings.remove_greeting(bot_id)
    greetings.remove_all_node_audio(bot_id)


@router.get("/{bot_id}/flow")
async def get_flow(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    if not bot.flow_json:
        # Bot creado antes del editor visual: se reconstruye su menú simple
        # (config JSON + saludo) como nodos, para que se vea y se pueda
        # seguir editando en el nuevo editor en vez de aparecer vacío.
        return legacy_flow_from_bot(bot)
    try:
        parsed = json.loads(bot.flow_json)
        if isinstance(parsed, dict) and parsed.get("nodes"):
            return parsed
        return legacy_flow_from_bot(bot)
    except (ValueError, TypeError):
        return legacy_flow_from_bot(bot)


@router.put("/{bot_id}/flow")
async def save_flow(bot_id: int, payload: VoiceBotFlowUpdate, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    bot.flow_json = json.dumps({"nodes": payload.nodes, "edges": payload.edges})
    await session.commit()
    try:
        await reloadxml()
    except Exception:
        pass  # el flujo queda guardado igual; el próximo reload lo recoge
    return {"ok": True}


@router.post("/{bot_id}/flow/nodes/{node_id}/audio")
async def upload_node_audio(bot_id: int, node_id: str, file: UploadFile, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    if not validacion.id_nodo_valido(node_id):
        raise HTTPException(status_code=422, detail="Id de nodo no válido")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        path = greetings.save_audio(bot_id, file.filename or "audio.wav", content, node_id=node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"path": path}


@router.post("/{bot_id}/flow/nodes/{node_id}/tts")
async def generate_node_tts(
    bot_id: int, node_id: str, payload: VoiceBotNodeTtsRequest, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    if not validacion.id_nodo_valido(node_id):
        raise HTTPException(status_code=422, detail="Id de nodo no válido")
    try:
        audio, ext = await _synthesize(payload.text, payload.voice, payload.provider, session)
        suffix = "whisper" if payload.kind == "whisper" else "audio"
        path = greetings.save_audio(bot_id, f"{suffix}.{ext}", audio, node_id=f"{node_id}_{suffix}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error generando el audio: {exc}")
    return {"path": path}


@router.delete("/{bot_id}/flow/nodes/{node_id}/audio")
async def delete_node_audio(bot_id: int, node_id: str, session: AsyncSession = Depends(get_session)):
    # Sin esta comprobación cualquier empresa podía borrar los audios de un bot
    # AJENO: los archivos están fuera de la base y no los cubre el aislamiento
    # por empresa; `session.get` sí (devuelve None si el bot es de otra).
    if not await session.get(VoiceBot, bot_id):
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    if not validacion.id_nodo_valido(node_id):
        raise HTTPException(status_code=422, detail="Id de nodo no válido")
    greetings.remove_audio(bot_id, node_id=node_id)
    return {"ok": True}


@router.post("/{bot_id}/greeting", response_model=VoiceBotOut)
async def upload_greeting(
    bot_id: int, file: UploadFile, session: AsyncSession = Depends(get_session)
):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        path = greetings.save_greeting(bot_id, file.filename or "greeting.wav", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    bot.greeting_audio_path = path
    await session.commit()
    await session.refresh(bot)
    return bot


@router.post("/{bot_id}/tts", response_model=VoiceBotOut)
async def generate_greeting_tts(
    bot_id: int, payload: VoiceBotTtsRequest, session: AsyncSession = Depends(get_session)
):
    """Genera el audio de saludo con una voz neuronal en español (edge-tts,
    gratis, sin API key) y lo deja como el audio propio del bot."""
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    try:
        audio, ext = await _synthesize(payload.text, payload.voice, payload.provider, session)
        path = greetings.save_greeting(bot_id, f"greeting.{ext}", audio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error generando el audio: {exc}")
    bot.greeting_audio_path = path
    await session.commit()
    await session.refresh(bot)
    return bot


@router.delete("/{bot_id}/greeting", response_model=VoiceBotOut)
async def delete_greeting(bot_id: int, session: AsyncSession = Depends(get_session)):
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    greetings.remove_greeting(bot_id)
    bot.greeting_audio_path = None
    await session.commit()
    await session.refresh(bot)
    return bot


@router.post("/reload")
async def voicebots_reload():
    try:
        out = await reloadxml()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}


class MensajePrueba(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=bot_sim.MAX_CHARS)


class PruebaBot(BaseModel):
    """Un turno de la simulación. Menú: `nodo` + `tecla` (sin nodo = empezar).
    IA: `mensajes` con la conversación hasta ahora."""

    nodo: str | None = Field(default=None, max_length=60)
    tecla: str | None = Field(default=None, max_length=1)
    mensajes: list[MensajePrueba] = Field(default_factory=list, max_length=bot_sim.MAX_MENSAJES)
    intencion: str = Field(default="general", max_length=30, pattern="^[a-z_]{1,30}$")
    modo: str | None = Field(default=None, pattern="^(ivr|ia)$")
    # Número desde el que "llama" quien prueba: con él el bot ve la cita o la deuda REALES
    # de ese teléfono, igual que en una llamada entrante.
    telefono: str | None = Field(default=None, max_length=30, pattern=r"^[0-9+ ()\-]{0,30}$")


@router.get("/probar/datos")
async def datos_para_probar(
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    """Teléfonos con cita o deuda REALES para simular una llamada de cada uno (solo lo que el rol puede ver)."""
    salida: dict = {"citas": [], "deudas": []}
    if permissions.puede(usuario.role, permissions.CITAS_GESTIONAR):
        filas = (
            await session.execute(
                select(Appointment)
                .where(Appointment.status == "confirmed", Appointment.appointment_date >= now_local())
                .order_by(Appointment.appointment_date)
                .limit(8)
            )
        ).scalars().all()
        salida["citas"] = [
            {"telefono": a.phone, "nombre": a.patient_name, "cuando": a.appointment_date.strftime("%d/%m %H:%M")}
            for a in filas
        ]
    if permissions.puede(usuario.role, permissions.CAMPANAS_GESTIONAR):
        filas = (
            await session.execute(
                select(Debt).where(Debt.status.in_(("open", "promised", "overdue"))).order_by(Debt.updated_at.desc()).limit(8)
            )
        ).scalars().all()
        salida["deudas"] = [{"telefono": d.phone, "nombre": d.debtor_name, "monto": int(d.amount)} for d in filas]
    return salida


@router.post("/{bot_id}/probar")
async def probar_bot(
    bot_id: int,
    payload: PruebaBot,
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    """Simula una conversación con el bot SIN llamar y SIN escribir en la agenda ni en la cobranza
    (ver services/bot_sim.py)."""
    bot = await session.get(VoiceBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")
    limitador.limitar_uso(limitador.POR_SIMULADOR, f"sim:{usuario.id}")

    modo = payload.modo or ("ia" if bot.bot_type == "ai" else "ivr")
    if modo == "ivr":
        return bot_sim.paso_ivr(bot, payload.nodo, payload.tecla)

    if not payload.mensajes or payload.mensajes[-1].role != "user":
        raise HTTPException(status_code=422, detail="Escribe un mensaje para el bot")
    ajustes = await ajustes_de(session)
    try:
        return await bot_sim.turno_ia(
            session, ajustes, tenant_de_sesion(session),
            [{"role": m.role, "content": m.content} for m in payload.mensajes], payload.intencion,
            payload.telefono or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="El modelo de IA no respondió. Revisa la configuración en Ajustes.")
