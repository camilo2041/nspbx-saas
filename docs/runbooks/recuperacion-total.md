# Runbook 8 — Recuperación total desde respaldo

El servidor se perdió (disco, proveedor, borrado accidental, ataque) y hay
que levantar todo en otro desde los respaldos.

Hoy el respaldo es un volcado diario de la base (worker de mantenimiento)
más un paquete cifrado off-site (`scripts/backup-offsite.sh`) con la base,
las grabaciones y los audios de los bots. **RPO actual: hasta 24 h** de
datos. La meta de 15 min requiere archivado continuo de WAL (pendiente,
ver `docs/seguridad-y-robustez.md` §6.2).

## Antes de que pase: simulacro mensual

```bash
bash scripts/simulacro-restauracion.sh                       # último respaldo local
BACKUP_PASSPHRASE_FILE=/ruta/clave \
  bash scripts/simulacro-restauracion.sh nspbx-AAAAMMDD-HHMMSS.tar.gz.enc   # paquete off-site
```

Restaura en un Postgres descartable (contenedor sin red), comprueba
empresas, usuarios, políticas de aislamiento y la última llamada, mide el
tiempo y deja una línea en `backups/simulacros.log`. No toca producción.
Una vez por trimestre, completarlo en un servidor de pruebas con los pasos
de abajo y anotar el tiempo total: **ese es el RTO real**.

El panel muestra el estado de las tres capas en Plataforma › Empresas ›
«Respaldos» (services/operacion.py): el volcado diario, el último paquete
cifrado de `backups/offsite/` (atrasado si tiene más de 48 h) y la última
línea de `backups/simulacros.log` (atrasado si tiene más de 35 días). Con
`METRICS_TOKEN`, las mismas cifras salen en `/metrics` para alertar desde
Prometheus (`nspbx_respaldo_externo_edad_horas`, `nspbx_simulacro_ok`,
`nspbx_simulacro_edad_dias`).

## Qué hace falta tener fuera del servidor

- El último paquete off-site (`nspbx-*.tar.gz.enc`) y su `.sha256`.
- **La clave de cifrado de los respaldos** (`BACKUP_PASSPHRASE_FILE`). Sin
  ella no hay restauración posible.
- **`DATA_ENCRYPTION_KEY`** (está en el `.env`). Sin ella la base se
  restaura y funciona, pero las claves de proveedores de IA y las
  contraseñas de troncales y extensiones quedan ilegibles: hay que volver a
  cargarlas todas y reconfigurar los teléfonos.
- El `.env` de producción (secretos) o, si se perdió, generar uno nuevo
  (paso 3) y aceptar rotar todo.
- Acceso al DNS y al proveedor SIP (la IP pública cambia).

## Pasos

1. **Servidor nuevo** con Docker y el repositorio clonado en la versión
   desplegada.
2. **Verificar el paquete**:
   ```bash
   sha256sum -c nspbx-AAAAMMDD-HHMMSS.tar.gz.enc.sha256
   ```
3. **Secretos y configuración de FreeSWITCH**: copiar el `.env` guardado y
   correr `bash scripts/setup.sh`. Con un `.env` ya presente, genera los
   archivos que no están en el repositorio (los tres XML con secretos y
   `vars.xml` con la IP pública de **este** servidor) a partir del `.env`.
   Si el `.env` se perdió, el mismo script genera uno nuevo: las claves de
   FreeSWITCH y de sesión cambian (todos vuelven a entrar), las SIP no.
4. **Abrir el paquete** (trae la base, las grabaciones y los audios):
   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/ruta/clave \
     -in nspbx-AAAAMMDD-HHMMSS.tar.gz.enc | tar -xzf -
   ```
5. **Levantar solo la base** y restaurar:
   ```bash
   docker compose up -d postgres
   bash scripts/restore.sh backups/nspbx-AAAAMMDD-HHMMSS.sql.gz
   ```
   `restore.sh` pide escribir RESTAURAR y luego levanta backend y voicebot,
   que recrean el rol de la aplicación y el aislamiento al arrancar.
6. **Levantar todo**: `docker compose up -d` y `bash scripts/verificar.sh`.
7. **DNS y proveedor**: actualizar los registros DNS del panel y del TURN a
   la IP nueva (el paso 3 ya la dejó en `vars.xml`) y avisar al proveedor
   SIP si autoriza por IP.
8. **Comprobar**:
   - el backend arranca y el log dice "Aislamiento por empresa activo";
   - se puede entrar al panel (con MFA si aplica);
   - una extensión registra;
   - una llamada interna y una saliente de prueba se completan;
   - las troncales aparecen registradas;
   - las campañas que estaban corriendo quedaron como estaban.
9. **Anotar** la hora de inicio y de fin: es el RTO de este incidente.

## Después

- Lo perdido es lo posterior al respaldo usado (hasta 24 h): avisar a las
  empresas qué período falta en historial y grabaciones.
- Si la pérdida fue por un ataque: runbook 2 completo antes de reabrir
  (todas las credenciales se consideran filtradas).
- Informe con el RTO y el RPO reales; si superan la meta (RTO 2 h), qué
  paso tardó y cómo acortarlo.
