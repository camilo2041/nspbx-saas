"""Respaldo automático de Postgres y retención de grabaciones.

Antes de esto no existía ninguna de las dos cosas: la base de datos vivía
solo en el volumen `pg_data`, sin ninguna copia — un `docker volume rm`
por error, una migración mala, o el volumen corrompiéndose se llevaba
puesto TODO (usuarios, extensiones, agenda, historial) sin forma de
recuperarlo. Y las grabaciones se acumulaban sin límite: un disco lleno no
es un error elegante, tumba a FreeSWITCH y a Postgres a la vez, así que
"sin retención" no es solo un tema de espacio, es un riesgo de caída.

Corre como un worker en el propio proceso del backend, con el mismo
patrón que `app.workers.dialer.CampaignDialer`: un loop que se fija
periódicamente si ya toca trabajar, en vez de un cron aparte — más simple
de operar en un docker-compose de un solo host.
"""

import asyncio
import gzip
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import async_session
from app.models import SystemSettings

logger = logging.getLogger(__name__)

_NOMBRE_BACKUP = re.compile(r"^nspbx-\d{8}-\d{6}\.sql\.gz$")


class MaintenanceWorker:
    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("MaintenanceWorker iniciado")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MaintenanceWorker detenido")

    async def _loop(self):
        # Se corre una vez apenas arranca —para que una instalación nueva
        # tenga su primer respaldo sin esperar un día entero— y de ahí en
        # más cada 6 horas se fija si ya pasaron las 24 horas desde el
        # último. El chequeo frecuente (en vez de dormir 24h de un tirón)
        # es lo que hace que `stop()` no tarde medio día en responder al
        # apagar el contenedor.
        while self._running:
            try:
                await self.ejecutar_una_vez()
            except Exception:
                logger.exception("Error en MaintenanceWorker")
            for _ in range(6 * 60):  # 6 horas, en pasos de 1 minuto
                if not self._running:
                    return
                await asyncio.sleep(60)

    async def ejecutar_una_vez(self) -> None:
        # La sesión es la del DUEÑO (sin RLS): el respaldo es de la base
        # COMPLETA, no de una empresa, y el worker corre una vez para todo
        # el sistema. La configuración (¿respaldar?, retención, topes) es
        # por empresa; se combina de la forma más conservadora: se respalda
        # si CUALQUIER empresa lo tiene activo, y se conserva lo máximo /
        # se borra con el tope mínimo de todas.
        async with async_session() as session:
            filas = (await session.execute(select(SystemSettings))).scalars().all()
            if not filas:
                return
            necesita_backup = any(
                f.backup_enabled
                and (
                    f.last_backup_at is None
                    or datetime.utcnow() - f.last_backup_at >= timedelta(hours=23)
                )
                for f in filas
            )
            retencion_backup = max(f.backup_retention_days for f in filas)
            tope_backup_gb = min(f.backups_max_gb for f in filas)
            retencion_grabaciones = max(f.recordings_retention_days for f in filas)
            tope_gb = min(f.recordings_max_gb for f in filas)

        if necesita_backup:
            await self._respaldar_postgres(retencion_backup, tope_backup_gb)
        await self._limpiar_grabaciones(retencion_grabaciones, tope_gb)

    async def respaldar_ahora(self) -> None:
        """Respaldo a demanda (botón "Respaldar ahora" en Ajustes) — se
        salta el chequeo de "¿ya pasaron 24 horas?" pero respeta la misma
        retención configurada, para no dejar acumular copias de más solo
        porque alguien lo disparó a mano varias veces seguidas."""
        async with async_session() as session:
            filas = (await session.execute(select(SystemSettings))).scalars().all()
            retencion = max((f.backup_retention_days for f in filas), default=14)
            tope_gb = min((f.backups_max_gb for f in filas), default=5.0)
        await self._respaldar_postgres(retencion, tope_gb)

    async def _respaldar_postgres(self, retencion_dias: int, tope_gb: float) -> None:
        destino = Path(settings.backups_dir)
        destino.mkdir(parents=True, exist_ok=True)
        url = make_url(settings.database_url)
        nombre = f"nspbx-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.sql.gz"
        archivo = destino / nombre

        env = {"PGPASSWORD": url.password or ""}
        cmd = [
            "pg_dump",
            "-h", url.host or "postgres",
            "-p", str(url.port or 5432),
            "-U", url.username or "nspbx",
            "-d", url.database or "nspbx",
            # --no-owner/--no-privileges: para poder restaurar en una base
            # nueva sin que falle por roles que no existen ahí.
            "--no-owner",
            "--no-privileges",
        ]
        error = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            volcado, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError((stderr or b"").decode(errors="replace")[:500])
            if not volcado:
                raise RuntimeError("pg_dump no devolvió datos")
            # Comprimido acá y no con `pg_dump -Fc`: un .sql.gz plano se
            # puede inspeccionar con `zcat` sin herramientas de Postgres,
            # útil si el respaldo hay que revisarlo a mano en un apuro.
            archivo.write_bytes(gzip.compress(volcado, compresslevel=6))
            logger.info("Respaldo de Postgres OK: %s (%d KB)", nombre, archivo.stat().st_size // 1024)
        except Exception as exc:
            error = str(exc)[:500]
            logger.error("Falló el respaldo de Postgres: %s", error)

        async with async_session() as session:
            # El resultado se anota en TODAS las empresas: el respaldo es
            # de la base completa, así que vale para todas por igual.
            filas = (await session.execute(select(SystemSettings))).scalars().all()
            for row in filas:
                row.last_backup_at = datetime.utcnow()
                row.last_backup_ok = error is None
                row.last_backup_error = error
            await session.commit()

        if error is None:
            self._purgar_backups_viejos(destino, retencion_dias, tope_gb)

    def _purgar_backups_viejos(self, carpeta: Path, retencion_dias: int, tope_gb: float) -> None:
        limite = datetime.utcnow() - timedelta(days=retencion_dias)
        vigentes = []
        eliminados_por_edad = 0
        for archivo in carpeta.glob("nspbx-*.sql.gz"):
            # Solo se tocan archivos con el patrón exacto de nombre que
            # generamos acá — por si alguien guarda algo propio en la
            # misma carpeta, no se lo lleva puesto.
            if not _NOMBRE_BACKUP.match(archivo.name):
                continue
            if datetime.utcfromtimestamp(archivo.stat().st_mtime) < limite:
                archivo.unlink(missing_ok=True)
                eliminados_por_edad += 1
                logger.info("Respaldo vencido eliminado: %s", archivo.name)
            else:
                vigentes.append(archivo)

        # Misma válvula de seguridad que las grabaciones: aunque todos los
        # respaldos sean recientes, si entre todos pasan el tope de GB se
        # borran los más viejos hasta volver a estar por debajo — evita
        # que una racha de "Respaldar ahora" seguidos llene el disco antes
        # de que la retención por días tenga oportunidad de actuar.
        eliminados_por_tope = 0
        try:
            vigentes.sort(key=lambda f: f.stat().st_mtime)
            total = sum(f.stat().st_size for f in vigentes)
            tope_bytes = tope_gb * (1024 ** 3)
            i = 0
            while total > tope_bytes and i < len(vigentes):
                tam = vigentes[i].stat().st_size
                vigentes[i].unlink(missing_ok=True)
                total -= tam
                eliminados_por_tope += 1
                i += 1
        except FileNotFoundError:
            pass

        if eliminados_por_edad or eliminados_por_tope:
            logger.info(
                "Limpieza de respaldos: %d por antigüedad (>%dd), %d por exceder %.1f GB",
                eliminados_por_edad, retencion_dias, eliminados_por_tope, tope_gb,
            )

    async def _limpiar_grabaciones(self, retencion_dias: int, tope_gb: float) -> None:
        carpeta = Path(settings.recordings_dir)
        if not carpeta.exists():
            return

        # "**/*.wav" (recursivo) y no "*.wav": las grabaciones ahora se
        # organizan en subcarpetas AAAA/MM/DD (ver config_generator.py) —
        # con el glob plano de antes, la limpieza dejaba de ver CUALQUIER
        # grabación nueva y nunca las borraba.
        archivos = [f for f in carpeta.glob("**/*.wav") if f.is_file()]
        limite = datetime.utcnow() - timedelta(days=retencion_dias)
        eliminados_por_edad = 0
        vigentes = []
        for f in archivos:
            try:
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            except FileNotFoundError:
                continue
            if mtime < limite:
                f.unlink(missing_ok=True)
                eliminados_por_edad += 1
            else:
                vigentes.append(f)

        # Válvula de seguridad: aunque todo esté dentro de la retención
        # por días, si el total pasa el tope configurado se borran las
        # más viejas hasta volver a estar por debajo. Esto es lo que
        # evita que un pico de llamadas grabadas llene el disco antes de
        # que la retención por edad tenga oportunidad de actuar.
        tope_bytes = tope_gb * (1024 ** 3)
        eliminados_por_tope = 0
        try:
            vigentes.sort(key=lambda f: f.stat().st_mtime)
            total = sum(f.stat().st_size for f in vigentes)
            i = 0
            while total > tope_bytes and i < len(vigentes):
                tam = vigentes[i].stat().st_size
                vigentes[i].unlink(missing_ok=True)
                total -= tam
                eliminados_por_tope += 1
                i += 1
        except FileNotFoundError:
            pass

        if eliminados_por_edad or eliminados_por_tope:
            self._purgar_carpetas_vacias(carpeta)
            logger.info(
                "Limpieza de grabaciones: %d por antigüedad (>%dd), %d por exceder %.1f GB",
                eliminados_por_edad, retencion_dias, eliminados_por_tope, tope_gb,
            )

    def _purgar_carpetas_vacias(self, carpeta: Path) -> None:
        """Las carpetas AAAA/MM/DD se crean una por día (ver
        config_generator.py) y nunca se borran solas — sin esto, con la
        retención activa se van acumulando miles de carpetas de días
        vacíos con el tiempo. Solo las de fecha (DD bajo MM bajo AAAA),
        de más profundo a más superficial para que un mes/año completo
        también quede vacío y se borre en la misma pasada."""
        for profundidad in (3, 2, 1):
            for sub in carpeta.glob("/".join(["*"] * profundidad)):
                if sub.is_dir():
                    try:
                        sub.rmdir()
                    except OSError:
                        pass  # no estaba vacía, se deja


maintenance = MaintenanceWorker()
