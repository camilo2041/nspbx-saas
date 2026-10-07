"""Frases fijas del sistema (no molestar, avisos cortos) pre-generadas con
voz de calidad — no con `flite`, el sintetizador que trae FreeSWITCH de
fábrica.

`flite|kal` (usado en otras partes viejas del dialplan, ej. bot_1) es una
voz robótica en inglés de los 2000: pronuncia el texto en español con
fonética inglesa, así que suena mal Y en el idioma equivocado a la vez. Y
como `speak` sintetiza EN EL MOMENTO de la llamada, la primera vez que
FreeSWITCH carga el modelo de flite hay un salto perceptible antes de que
arranque el audio — eso es lo que se sentía como demora al "contestar".

La solución es la misma que ya usa el resto del proyecto para el bot de
IA: sintetizar UNA VEZ con Deepgram (voz en español real) y reproducir el
archivo ya listo con `playback`, que no tiene ningún retraso de síntesis.

Sin API key de Deepgram en ninguna empresa, se usan las voces gratuitas de
edge-tts (services/tts.py, MP3 que FreeSWITCH reproduce con mod_shout): una
instalación nueva ya habla en español. flite queda solo para cuando tampoco
hay salida a internet. El mantenimiento vuelve a intentarlo cada hora.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import SystemSettings
from app.services import deepgram, tts
from app.services.numeros import numero_a_palabras

logger = logging.getLogger(__name__)

PROMPTS_DIR = "prompts"
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"

# Voz fija para estos avisos, sin importar qué proveedor tenga elegido el
# voizbot de IA en este momento: son anuncios cortos del sistema, no
# conversación, y no tiene sentido que dependan de esa configuración.
_VOZ = "aura-2-celeste-es"
_VOZ_GRATIS = "es-CO-SalomeNeural"
_FORMATOS = (".wav", ".mp3")

_TEXTOS = {
    "dnd_on": "No molestar activado.",
    "dnd_off": "No molestar desactivado.",
    "dnd_no_disponible": "La extensión no está disponible en este momento.",
    "ivr_opcion_invalida": "Esa opción no es válida. Hasta luego.",
    "buzon_saludo": "La persona que llamas no está disponible. Deja tu mensaje después del tono y cuelga al terminar.",
    # Grupos de atención (services/queues_sync.py y config_generator._append_queue_routes).
    "cola_aviso": "Gracias por esperar. En un momento te atendemos.",
    "cola_delante_0": "Eres el siguiente en ser atendido.",
    "cola_delante_1": "Hay una persona antes que tú.",
    **{f"cola_delante_{n}": f"Hay {numero_a_palabras(n)} personas antes que tú." for n in range(2, 10)},
    "cola_delante_mas": "Hay más de nueve personas antes que tú. Gracias por esperar.",
    # Devolución de llamada (services/vigia_colas.py).
    "cola_devolucion_oferta": "Si prefieres que te devolvamos la llamada sin perder tu turno, marca 1.",
    "cola_devolucion_ok": "Listo. Te llamaremos a este número apenas te toque. Ya puedes colgar.",
}


def _local_path(key: str, formato: str = ".wav") -> Path:
    return Path(settings.fs_sounds_dir) / PROMPTS_DIR / f"{key}{formato}"


def _existente(key: str) -> str | None:
    """El formato del audio ya generado (WAV de Deepgram o MP3 de edge-tts)."""
    return next((f for f in _FORMATOS if _local_path(key, f).exists()), None)


def prompt_path(key: str) -> str | None:
    """Ruta que ve FreeSWITCH para reproducir el audio con `playback`, o
    None si todavía no se generó — quien llama debe tener un plan B."""
    formato = _existente(key)
    if formato is None:
        return None
    return f"{FS_SIDE_SOUNDS_DIR}/{PROMPTS_DIR}/{key}{formato}"


async def _clave_deepgram(session: AsyncSession, tenant_id: int | None) -> str:
    """La de la empresa, o la de cualquiera: los avisos son de todo el sistema."""
    from sqlalchemy import select

    from app.services.ajustes import ajustes_de

    fila = await ajustes_de(session, tenant_id)
    if fila is not None and fila.deepgram_api_key:
        return fila.deepgram_api_key
    for (clave,) in (await session.execute(select(SystemSettings.deepgram_api_key))).all():
        if clave:
            return clave
    return ""


async def ensure_prompts(session: AsyncSession, tenant_id: int | None = None) -> int:
    """Genera los audios que falten y dice cuántos generó. Se llama al
    arrancar y cada hora (workers/maintenance.py); nunca revienta: el
    dialplan cae a flite mientras falte un audio."""
    faltantes = [k for k in _TEXTOS if _existente(k) is None]
    if not faltantes:
        return 0
    try:
        api_key = await _clave_deepgram(session, tenant_id)
    except Exception:
        logger.exception("No se pudo leer la API key de Deepgram para los avisos de voz")
        api_key = ""

    carpeta = Path(settings.fs_sounds_dir) / PROMPTS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    generados = 0
    for key in faltantes:
        try:
            if api_key:
                _local_path(key).write_bytes(await deepgram.synthesize(_TEXTOS[key], _VOZ, api_key))
            else:
                _local_path(key, ".mp3").write_bytes(
                    await asyncio.wait_for(tts.synthesize(_TEXTOS[key], _VOZ_GRATIS), timeout=20)
                )
            generados += 1
            logger.info("Generado el aviso de voz '%s'", key)
        except Exception as exc:
            logger.warning("No se pudo generar el aviso de voz '%s' (sigue con flite de respaldo): %s", key, exc)
            if not api_key:
                break  # sin internet: no insistir con cada frase
    return generados
