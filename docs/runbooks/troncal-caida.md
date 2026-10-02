# Runbook 7 — Troncal caída

La troncal es la conexión con el proveedor que da los números y la salida a
la red telefónica. Si cae, las llamadas internas y el voizbot por WebRTC
siguen, pero **no entran ni salen llamadas a números de afuera** (o salen
por otra troncal si hay más de una en la ruta).

Severidad: **S2** si es una troncal compartida o de varias empresas; **S3**
si es de una empresa.

## Síntomas

- Salientes a números de afuera que fallan al instante.
- Nadie recibe llamadas de afuera; las internas funcionan.
- Troncales (app o panel): estado distinto de «Registrada»
  (`NOREG`, `FAIL_WAIT`, `TRYING`) o ping alto.
- Una troncal «Registrada» pero sin llamadas entrantes: casi siempre la IP
  que anuncia (ver la tabla de causas).

## Confirmar

1. Troncales → la troncal → «Verificar estado»: estado, ping y la IP que
   anuncia la central.
2. Ajustes → Diagnóstico: todas las troncales, la IP pública actual y
   si alguna anuncia una IP no alcanzable.
3. Desde el servidor:
   ```bash
   docker compose exec freeswitch fs_cli -x "sofia status gateway"
   docker compose exec freeswitch fs_cli -x "sofia status gateway <empresa>_<troncal>"
   ```
4. Página de estado o soporte del proveedor.

## Causas frecuentes y qué hacer

| Causa | Cómo se ve | Qué hacer |
|---|---|---|
| El proveedor está caído | `FAIL_WAIT` en todas sus troncales; su soporte lo confirma | contener abajo y esperar |
| Credenciales cambiadas o cuenta suspendida (saldo) | `FAIL_WAIT` con 401/403 en `fs_cli -x "sofia global siptrace on"` | corregir usuario/clave en Troncales; revisar saldo |
| La IP pública del servidor cambió | registrada, pero el proveedor rechaza o no entran llamadas; Diagnóstico muestra la IP nueva | avisar al proveedor si autoriza por IP; «Reescanear en la central» |
| Anuncia una IP privada o de CGNAT | «Registrada» pero sin entrantes; aviso en la troncal | corregir la IP externa en la configuración de FreeSWITCH y reescanear |
| Firewall o fail2ban bloqueó al proveedor | ping falla; la IP del proveedor en Seguridad → Bloqueos | desbloquearla en el servidor (`fail2ban-client set <jail> unbanip <ip>`) y agregarla a `ignoreip` en `deploy/fail2ban/jail.d/*.local` |

## Contener

- **Segunda troncal**: Rutas salientes → la ruta → «Troncales, en orden de
  reintento»: poner la de respaldo. Si la primera rechaza, se intenta la
  siguiente en la misma llamada.
- **Campañas**: detenerlas (Campañas → Detener) para no gastar los
  reintentos de cada número contra una troncal caída.
- **Entrantes**: si el proveedor permite desviar los números a otra troncal
  o a un celular durante la caída, pedirlo.

## Recuperar

- «Verificar estado» en «Registrada», una saliente y una entrante de
  prueba.
- Reintentar las campañas (Campañas → Reintentar): vuelve a poner como
  pendientes los números que fallaron.

## Cerrar

Informe: proveedor, duración, llamadas perdidas (CDR del rango con causa
`NORMAL_TEMPORARY_FAILURE`, `GATEWAY_DOWN` o similares). Si no había troncal
de respaldo, evaluar contratar una segunda con otro proveedor.
