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
"""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import SystemSettings
from app.services import deepgram

logger = logging.getLogger(__name__)

PROMPTS_DIR = "prompts"
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"

# Voz fija para estos avisos, sin importar qué proveedor tenga elegido el
# voizbot de IA en este momento: son anuncios cortos del sistema, no
# conversación, y no tiene sentido que dependan de esa configuración.
_VOZ = "aura-2-celeste-es"

_TEXTOS = {
    "dnd_on": "No molestar activado.",
    "dnd_off": "No molestar desactivado.",
    "dnd_no_disponible": "La extensión no está disponible en este momento.",
}


def _local_path(key: str) -> Path:
    return Path(settings.fs_sounds_dir) / PROMPTS_DIR / f"{key}.wav"


def prompt_path(key: str) -> str | None:
    """Ruta que ve FreeSWITCH para reproducir el audio con `playback`, o
    None si todavía no se generó (por ejemplo, sin API key de Deepgram
    configurada) — quien llama debe tener un plan B para ese caso."""
    if not _local_path(key).exists():
        return None
    return f"{FS_SIDE_SOUNDS_DIR}/{PROMPTS_DIR}/{key}.wav"


async def ensure_prompts(session: AsyncSession, tenant_id: int | None = None) -> None:
    """Genera los audios que falten. Se llama una vez al arrancar el
    backend; si no hay API key todavía, no revienta nada — el dialplan
    cae de vuelta a `speak` con flite hasta que se configure una."""
    faltantes = [k for k in _TEXTOS if not _local_path(k).exists()]
    if not faltantes:
        return

    from app.services.ajustes import ajustes_de

    fila = await ajustes_de(session, tenant_id)
    api_key = (fila.deepgram_api_key if fila else None) or ""
    if not api_key:
        logger.info(
            "Sin API key de Deepgram todavía: los avisos de DND van a sonar con la voz de "
            "respaldo (flite) hasta que se configure una en Ajustes."
        )
        return

    carpeta = Path(settings.fs_sounds_dir) / PROMPTS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    for key in faltantes:
        try:
            audio = await deepgram.synthesize(_TEXTOS[key], _VOZ, api_key)
            _local_path(key).write_bytes(audio)
            logger.info("Generado el aviso de voz '%s'", key)
        except Exception:
            logger.exception("No se pudo generar el aviso de voz '%s'; sigue con flite de respaldo", key)
