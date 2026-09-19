"""Límite de intentos fallidos (fuerza bruta) y dirección real del cliente.

En memoria: el backend corre en un solo proceso, y un reinicio solo "perdona"
los contadores. Si algún día se escala a varios procesos, esto pasa a Redis.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


def ip_cliente(request: Request) -> str:
    """IP del cliente detrás de `proxies_confiables` proxies inversos.

    Cada proxy AÑADE al final de X-Forwarded-For la IP que vio. Lo que el
    cliente escriba queda al principio, así que tomar la primera entrada (lo
    habitual) deja que cualquiera se invente una IP distinta en cada intento y
    esquive el límite. Se toma la entrada que agregó nuestro proxy."""
    directa = request.client.host if request.client else "?"
    saltos = settings.proxies_confiables
    if saltos <= 0:
        return directa
    partes = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(partes) >= saltos:
        return partes[-saltos][:64]
    return directa


class LimiteIntentos:
    """Ventana deslizante de fallos por clave, con bloqueo temporal."""

    def __init__(self, maximo: int, ventana: int, bloqueo: int):
        self.maximo, self.ventana, self.bloqueo = maximo, ventana, bloqueo
        self._fallos: dict[str, deque] = defaultdict(deque)
        self._hasta: dict[str, float] = {}

    def _limpiar(self, clave: str, ahora: float) -> None:
        q = self._fallos.get(clave)
        while q and ahora - q[0] > self.ventana:
            q.popleft()
        if q is not None and not q:
            self._fallos.pop(clave, None)
        if self._hasta.get(clave, 0) <= ahora:
            self._hasta.pop(clave, None)

    def restante(self, clave: str) -> int:
        """Segundos que faltan para poder reintentar (0 = libre)."""
        ahora = time.monotonic()
        self._limpiar(clave, ahora)
        return max(0, int(self._hasta.get(clave, 0) - ahora) + (1 if clave in self._hasta else 0))

    def fallo(self, clave: str) -> None:
        ahora = time.monotonic()
        self._limpiar(clave, ahora)
        q = self._fallos[clave]
        q.append(ahora)
        if len(q) >= self.maximo:
            self._hasta[clave] = ahora + self.bloqueo
            q.clear()
        # Tope de memoria: un atacante que rote claves no debe llenar el proceso.
        if len(self._fallos) > 50000:
            for k in list(self._fallos)[:10000]:
                self._fallos.pop(k, None)

    def exito(self, clave: str) -> None:
        self._fallos.pop(clave, None)
        self._hasta.pop(clave, None)


# Tres frenos a la vez: contra quien prueba claves de una cuenta desde un punto,
# contra quien barre muchas cuentas desde un punto, y contra un ataque repartido
# entre muchas IP a una misma cuenta. El de la cuenta es más alto para que un
# tercero no pueda dejar fuera a un usuario legítimo con solo equivocarse a propósito.
POR_IP_Y_USUARIO = LimiteIntentos(maximo=5, ventana=900, bloqueo=900)
POR_IP = LimiteIntentos(maximo=30, ventana=900, bloqueo=900)
POR_USUARIO = LimiteIntentos(maximo=25, ventana=900, bloqueo=900)


def exigir_libre(ip: str, usuario: str) -> None:
    espera = max(
        POR_IP_Y_USUARIO.restante(f"{ip}|{usuario}"),
        POR_IP.restante(ip),
        POR_USUARIO.restante(usuario),
    )
    if espera:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiados intentos fallidos. Vuelve a intentarlo en {max(1, round(espera / 60))} min.",
            headers={"Retry-After": str(espera)},
        )


def registrar_fallo(ip: str, usuario: str) -> None:
    POR_IP_Y_USUARIO.fallo(f"{ip}|{usuario}")
    POR_IP.fallo(ip)
    POR_USUARIO.fallo(usuario)


def registrar_exito(ip: str, usuario: str) -> None:
    POR_IP_Y_USUARIO.exito(f"{ip}|{usuario}")
