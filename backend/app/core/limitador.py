"""Límite de intentos fallidos (fuerza bruta) y dirección real del cliente.

Los intentos de inicio de sesión se cuentan en la base (tabla
`intentos_acceso`): con varias réplicas, quien prueba claves no consigue el
doble de intentos repartiéndolos entre ellas. Si la base no responde, se
sigue contando en memoria de la réplica: mejor un freno por réplica que
dejar entrar sin freno o dejar a todos fuera.

Los topes de uso baratos (LimiteIntentos + limitar_uso, p. ej. los reportes
CSP) siguen en memoria.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)


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


class LimiteCompartido:
    """Como LimiteIntentos, pero en la base y con ventana fija desde el
    primer fallo: todas las réplicas ven el mismo conteo y el mismo bloqueo.
    `memoria` es el respaldo si la base falla."""

    _FALLO = text(
        "INSERT INTO intentos_acceso (clave, fallos, inicio, hasta) VALUES (:clave, 1, :ahora, 0) "
        "ON CONFLICT (clave) DO UPDATE SET "
        "fallos = CASE WHEN intentos_acceso.inicio < :desde THEN 1 ELSE intentos_acceso.fallos + 1 END, "
        "inicio = CASE WHEN intentos_acceso.inicio < :desde THEN :ahora ELSE intentos_acceso.inicio END "
        "RETURNING fallos"
    )
    _BLOQUEAR = text("UPDATE intentos_acceso SET fallos = 0, inicio = :ahora, hasta = :hasta WHERE clave = :clave")

    def __init__(self, nombre: str, maximo: int, ventana: int, bloqueo: int):
        self.nombre, self.maximo, self.ventana, self.bloqueo = nombre, maximo, ventana, bloqueo
        self.memoria = LimiteIntentos(maximo, ventana, bloqueo)

    def clave(self, clave: str) -> str:
        return f"{self.nombre}:{clave}"[:200]

    async def fallo(self, session, clave: str, ahora: float) -> None:
        k = self.clave(clave)
        fallos = (await session.execute(self._FALLO, {"clave": k, "ahora": ahora, "desde": ahora - self.ventana})).scalar_one()
        if fallos >= self.maximo:
            await session.execute(self._BLOQUEAR, {"clave": k, "ahora": ahora, "hasta": ahora + self.bloqueo})


# Tres frenos a la vez: contra quien prueba claves de una cuenta desde un punto,
# contra quien barre muchas cuentas desde un punto, y contra un ataque repartido
# entre muchas IP a una misma cuenta. El de la cuenta es más alto para que un
# tercero no pueda dejar fuera a un usuario legítimo con solo equivocarse a propósito.
POR_IP_Y_USUARIO = LimiteCompartido("ipu", maximo=5, ventana=900, bloqueo=900)
POR_IP = LimiteCompartido("ip", maximo=30, ventana=900, bloqueo=900)
POR_USUARIO = LimiteCompartido("u", maximo=25, ventana=900, bloqueo=900)


def _frenos(ip: str, usuario: str) -> list[tuple[LimiteCompartido, str]]:
    return [(POR_IP_Y_USUARIO, f"{ip}|{usuario}"), (POR_IP, ip), (POR_USUARIO, usuario)]


def _sesion():
    from app.core.database import async_session  # tarde: database importa la config completa

    return async_session()


async def exigir_libre(ip: str, usuario: str) -> None:
    ahora = time.time()
    frenos = _frenos(ip, usuario)
    try:
        async with _sesion() as session:
            filas = await session.execute(
                text("SELECT max(hasta) FROM intentos_acceso WHERE clave = ANY(:claves)"),
                {"claves": [f.clave(c) for f, c in frenos]},
            )
            hasta = filas.scalar() or 0
        espera = max(0, int(hasta - ahora) + 1) if hasta > ahora else 0
    except Exception:
        logger.warning("Límite de inicio de sesión: la base no respondió; se usa el de esta réplica", exc_info=True)
        espera = max(f.memoria.restante(c) for f, c in frenos)
    if espera:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiados intentos fallidos. Vuelve a intentarlo en {max(1, round(espera / 60))} min.",
            headers={"Retry-After": str(espera)},
        )


async def registrar_fallo(ip: str, usuario: str) -> None:
    ahora = time.time()
    frenos = _frenos(ip, usuario)
    try:
        async with _sesion() as session:
            for freno, clave in frenos:
                await freno.fallo(session, clave, ahora)
            await session.commit()
    except Exception:
        logger.warning("Límite de inicio de sesión: la base no respondió; se cuenta en esta réplica", exc_info=True)
        for freno, clave in frenos:
            freno.memoria.fallo(clave)


async def registrar_exito(ip: str, usuario: str) -> None:
    """Solo perdona el par IP+usuario: los frenos por IP y por cuenta siguen."""
    clave = POR_IP_Y_USUARIO.clave(f"{ip}|{usuario}")
    POR_IP_Y_USUARIO.memoria.exito(f"{ip}|{usuario}")
    try:
        async with _sesion() as session:
            await session.execute(text("DELETE FROM intentos_acceso WHERE clave = :clave"), {"clave": clave})
            await session.commit()
    except Exception:
        logger.warning("Límite de inicio de sesión: no se pudo limpiar el contador", exc_info=True)


async def purgar() -> None:
    """Los contadores viejos y los bloqueos vencidos (mantenimiento)."""
    ahora = time.time()
    async with _sesion() as session:
        await session.execute(
            text("DELETE FROM intentos_acceso WHERE hasta < :ahora AND inicio < :viejo"),
            {"ahora": ahora, "viejo": ahora - 3600},
        )
        await session.commit()


def limitar_uso(limite: LimiteIntentos, clave: str, mensaje: str = "Demasiadas solicitudes seguidas; espera un momento") -> None:
    """Tope de uso (no de fallos): cada llamada cuenta, y al pasar el máximo se bloquea un rato."""
    espera = limite.restante(clave)
    if espera:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, mensaje, headers={"Retry-After": str(espera)})
    limite.fallo(clave)

