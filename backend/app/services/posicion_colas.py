"""Quién espera en la fila de un grupo de atención (mod_callcenter).

Lo usan el vigía de los grupos (services/vigia_colas.py: aviso periódico de
la posición, devoluciones, tablero en vivo) y la prueba de humo. El orden es
el de llegada (joined_epoch), que es el que usa el grupo con
`time-base-score=system`.
"""

import re

PRIMERA_SEG = 40  # al entrar ya se dijo la posición; la primera repetición, después de esto
CADA_SEG = 45
_ESPERANDO = {"Waiting", "Trying"}
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def esperando(salida: str) -> list[dict]:
    """Los que esperan, en orden de llegada, de `callcenter_config queue list members`."""
    lineas = [l for l in (salida or "").splitlines() if "|" in l]
    if not lineas:
        return []
    campos = lineas[0].split("|")
    filas = []
    for linea in lineas[1:]:
        valores = linea.split("|")
        if len(valores) != len(campos):
            continue
        fila = dict(zip(campos, valores))
        if fila.get("state") in _ESPERANDO and _UUID_RE.fullmatch(fila.get("session_uuid") or ""):
            try:
                fila["_llego"] = float(fila.get("joined_epoch") or fila.get("system_epoch") or 0)
            except ValueError:
                fila["_llego"] = 0.0
            filas.append(fila)
    return sorted(filas, key=lambda f: f["_llego"])
