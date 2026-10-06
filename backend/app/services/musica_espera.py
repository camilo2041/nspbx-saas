"""Música de espera propia, generada al arrancar.

`$${hold_music}` es `local_stream://moh`, que lee las carpetas
`sounds/music/<frecuencia>` (freeswitch/conf/autoload_configs/
local_stream.conf.xml). La carpeta de sonidos del proyecto no traía música
(los paquetes de FreeSWITCH no se instalan: ver freeswitch/Dockerfile), así
que quien esperaba en un grupo de atención oía SILENCIO y colgaba creyendo
que la llamada se había caído.

En vez de sumar un archivo de audio al repositorio (y la duda de su
licencia), se sintetiza una melodía suave tipo piano: arpegios sobre
Do - La menor - Fa - Sol, unos 24 s que local_stream repite. Se escribe una
vez por frecuencia; si ya existe, no se toca, y si alguien deja su propia
música en esas carpetas, local_stream la mezcla con esta.
"""

import array
import logging
import math
import wave
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

NOMBRE = "nspbx-espera.wav"
# Las carpetas de local_stream.conf.xml (moh/8000, moh/16000…).
FRECUENCIAS = (8000, 16000, 32000, 48000)

_CORCHEA = 0.4  # segundos por nota del arpegio (75 pulsos por minuto)
_DECAIMIENTO = 0.7  # segundos para que la nota baje a ~37 %
_COLA = 1.8  # cuánto suena cada nota después de tocada
_VOLUMEN = 0.22  # pico de la mezcla; el teléfono comprime y satura fácil

# Acordes (MIDI): bajo y arpegio de 8 corcheas por acorde.
_ACORDES = [
    (48, [60, 64, 67, 72, 67, 64, 67, 72]),  # Do
    (45, [57, 60, 64, 69, 64, 60, 64, 69]),  # La menor
    (41, [53, 57, 60, 65, 60, 57, 60, 65]),  # Fa
    (43, [55, 59, 62, 67, 62, 59, 62, 67]),  # Sol
]


def _hz(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _nota(hz: float, frecuencia: int, fuerza: float) -> list[float]:
    """Una nota tipo piano: fundamental con dos armónicos que se apagan antes."""
    n = int(_COLA * frecuencia)
    ataque = max(1, int(0.008 * frecuencia))
    w = 2 * math.pi * hz / frecuencia
    nyquist = frecuencia / 2
    armonicos = [(1, 1.0), (2, 0.35), (3, 0.12)]
    armonicos = [(k, a) for k, a in armonicos if hz * k < nyquist * 0.9]
    salida = []
    for i in range(n):
        env = (i / ataque if i < ataque else 1.0) * math.exp(-i / (_DECAIMIENTO * frecuencia))
        valor = sum(a * math.sin(k * w * i) * math.exp(-i * (k - 1) / (0.5 * frecuencia)) for k, a in armonicos)
        salida.append(fuerza * env * valor)
    return salida


def sintetizar(frecuencia: int) -> bytes:
    """PCM de 16 bits, mono."""
    cache: dict[tuple[int, float], list[float]] = {}
    pasos = [(bajo, nota) for _ in range(2) for bajo, arpegio in _ACORDES for nota in arpegio]
    total = int((len(pasos) * _CORCHEA + _COLA) * frecuencia)
    mezcla = [0.0] * total
    for paso, (bajo, nota) in enumerate(pasos):
        inicio = int(paso * _CORCHEA * frecuencia)
        tocar = [(nota, 0.55)]
        if paso % 8 == 0:
            tocar.append((bajo, 0.6))
        for midi, fuerza in tocar:
            clave = (midi, fuerza)
            if clave not in cache:
                cache[clave] = _nota(_hz(midi), frecuencia, fuerza)
            for i, v in enumerate(cache[clave]):
                j = inicio + i
                if j >= total:
                    break
                mezcla[j] += v
    # El final se funde con el principio: local_stream la repite sin corte.
    largo = int(len(pasos) * _CORCHEA * frecuencia)
    for i in range(largo, total):
        mezcla[i - largo] += mezcla[i]
    mezcla = mezcla[:largo]
    pico = max(abs(v) for v in mezcla) or 1.0
    escala = _VOLUMEN * 32767 / pico
    return array.array("h", (int(v * escala) for v in mezcla)).tobytes()


def _escribir(ruta: Path, frecuencia: int) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    with wave.open(str(temporal), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frecuencia)
        w.writeframes(sintetizar(frecuencia))
    temporal.replace(ruta)


def asegurar() -> bool:
    """Genera la música que falte. True si escribió algo (hay que avisarle a
    FreeSWITCH: local_stream no vuelve a mirar una carpeta que no existía)."""
    escribio = False
    for frecuencia in FRECUENCIAS:
        ruta = Path(settings.fs_sounds_dir) / "music" / str(frecuencia) / NOMBRE
        if ruta.exists():
            continue
        try:
            _escribir(ruta, frecuencia)
            escribio = True
            logger.info("Música de espera generada: %s", ruta)
        except OSError:
            logger.exception("No se pudo escribir la música de espera en %s", ruta)
    return escribio
