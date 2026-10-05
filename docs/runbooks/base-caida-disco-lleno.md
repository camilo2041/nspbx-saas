# Runbook 5 — Base de datos caída o disco lleno

Sin base no hay panel, ni app, ni dialplan: FreeSWITCH pide el dialplan al
backend en cada llamada, así que **tampoco entran ni salen llamadas**. Un
disco lleno suele ser la causa: Postgres deja de escribir y se cae.

Severidad: **S1** (toda la plataforma sin servicio).

## Síntomas

- Panel y app: «No hay conexión con el servidor» o errores 500/502.
- Llamadas entrantes que se cuelgan solas; los teléfonos siguen
  registrados pero no marcan.
- `bash scripts/verificar.sh` → «postgres no responde».
- Log del backend con `connection refused` o `could not write`.

## Confirmar

```bash
docker compose ps postgres                 # ¿corriendo? ¿healthy?
docker compose logs --tail=50 postgres     # "No space left on device", "PANIC", "FATAL"
df -h /                                    # disco
du -sh freeswitch/recordings backups /var/lib/docker 2>/dev/null
```

## Contener

### Si el disco está lleno

1. Liberar espacio **sin tocar** `pg_data` (el volumen de la base):
   ```bash
   docker system prune -f                  # imágenes y contenedores viejos
   docker builder prune -f
   ls -lh backups/ | head                   # respaldos locales: dejar SIEMPRE el último
   ```
   Si hace falta más: mover grabaciones viejas fuera del servidor (o
   borrarlas si ya están en el off-site):
   ```bash
   find freeswitch/recordings -type f -mtime +30 | head
   ```
2. Nunca borrar archivos dentro del volumen de Postgres a mano (`pg_wal`
   incluido): corrompe la base.

### Si Postgres no arranca

```bash
docker compose up -d postgres
docker compose logs -f postgres            # esperar "database system is ready"
docker compose up -d backend voicebot      # reconectan solos, pero esto lo acelera
bash scripts/verificar.sh
```

Si los logs dicen que la base está corrupta o el volumen se perdió: runbook
8 (recuperación desde respaldo), restaurando en este mismo servidor con
`bash scripts/restore.sh backups/nspbx-<fecha>.sql.gz` (el último respaldo bueno; pide escribir RESTAURAR).

## Recuperar

- `bash scripts/verificar.sh` en verde.
- Una llamada entrante y una saliente de prueba.
- Respaldo inmediato (Ajustes → «Respaldar ahora»): el último bueno era de
  antes de la caída.

## Que no vuelva a pasar

- Topes de disco: `RECORDINGS_MAX_GB` y `BACKUPS_MAX_GB` en `.env` (con
  varias empresas) o Ajustes → Disco y respaldos (con una). El worker de
  mantenimiento borra lo más viejo al pasarse, aunque esté dentro de la
  retención.
- Retención de grabaciones en días (Ajustes): el audio vence, el registro
  de la llamada queda.
- Alerta de disco: `scripts/verificar.sh` en cron cada hora con aviso si
  falla, hasta tener monitoreo (ver `docs/seguridad-y-robustez.md` §6.1).

## Cerrar

Informe S1: causa (qué llenó el disco), duración, llamadas perdidas
(estimar con el historial de la troncal), y qué tope o alerta faltó.
