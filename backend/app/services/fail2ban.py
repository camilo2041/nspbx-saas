"""Lectura de los bloqueos de fail2ban.

fail2ban corre en el HOST, no en este contenedor, así que no se puede
ejecutar `fail2ban-client`. Se lee su base sqlite montada en SOLO LECTURA
(ver docker-compose): alcanza para mostrar qué está bloqueado y por qué, y
no le da a la aplicación web ninguna capacidad sobre el cortafuegos.

Esa limitación es deliberada. El socket de control de fail2ban no permite
solo desbloquear: también bloquear, recargar y reconfigurar. Montarlo acá
convertiría cualquier fallo de autenticación del panel en control del
cortafuegos del servidor, y un atacante se desbloquearía a sí mismo.
"""

import logging
import sqlite3
import time
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Bloqueo:
    jail: str
    ip: str
    desde: int
    """Epoch en que se aplicó."""
    segundos: int
    """Duración; 0 o negativo = permanente."""
    veces: int
    """Cuántas veces reincidió esta IP (fail2ban lo usa para escalar)."""

    @property
    def hasta(self) -> int | None:
        return None if self.segundos <= 0 else self.desde + self.segundos

    @property
    def vigente(self) -> bool:
        hasta = self.hasta
        return hasta is None or hasta > time.time()


def _conectar() -> sqlite3.Connection | None:
    """Abre la base en solo lectura. None si no está disponible.

    Devuelve None en vez de propagar el error porque esto es una pantalla
    de diagnóstico: en una máquina de desarrollo no hay fail2ban, y eso no
    debe romper el panel entero.
    """
    try:
        return sqlite3.connect(f"file:{settings.fail2ban_db}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error as e:
        logger.info("No se pudo leer la base de fail2ban (%s): %s", settings.fail2ban_db, e)
        return None


def disponible() -> bool:
    con = _conectar()
    if con is None:
        return False
    con.close()
    return True


def bloqueos() -> list[Bloqueo]:
    """Bloqueos vigentes, del más reciente al más viejo."""
    con = _conectar()
    if con is None:
        return []
    try:
        filas = con.execute(
            "SELECT jail, ip, timeofban, bantime, bancount FROM bips ORDER BY timeofban DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Error leyendo bloqueos de fail2ban: %s", e)
        return []
    finally:
        con.close()
    # Se filtran los vencidos acá y no en SQL: fail2ban deja la fila hasta
    # que pasa su limpieza, así que la tabla puede mostrar como bloqueada
    # una IP que ya volvió a entrar.
    return [b for b in (Bloqueo(*f) for f in filas) if b.vigente]


def historico(limite: int = 100) -> list[Bloqueo]:
    """Todos los bloqueos aplicados, vigentes o no."""
    con = _conectar()
    if con is None:
        return []
    try:
        filas = con.execute(
            "SELECT jail, ip, timeofban, bantime, bancount FROM bans ORDER BY timeofban DESC LIMIT ?",
            (max(1, min(limite, 500)),),
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Error leyendo el histórico de fail2ban: %s", e)
        return []
    finally:
        con.close()
    return [Bloqueo(*f) for f in filas]
