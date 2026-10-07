# Fase I: la app al día, aviso de buzón en iPhone y desbloqueo de IP

**Estado: hecha.**

| Bloque | Dónde | Notas |
|---|---|---|
| I1. Guías en la app | `mobile/src/guias.ts`, `mobile/src/GuiaFlotante.tsx`, asistente de la app | 12 guías de lo que se hace desde el teléfono, con los mismos ids del asistente. Tarjeta pequeña sobre las pestañas, con «Llévame». El buzón de la app ya permite poner el PIN de *96. |
| I2. Aviso de buzón en iPhone | `services/push.py` (`enviar_aviso_ios`), `mobile/src/avisos.ts` | Token APNs normal registrado aparte (`ios-avisos`); las llamadas siguen solo con PushKit/FCM. Pone en el ícono los mensajes sin escuchar. Requiere el permiso de notificaciones y la build nueva de la app (plugin `expo-notifications`). |
| I3. Desbloquear IP | `services/desbloqueos.py`, `scripts/fail2ban-desbloquear.sh`, Plataforma › Empresas, revisión 0033 | El panel solo deja el pedido; el script del host corre `unbanip` y nada más. Instalación en `docs/runbooks/desbloquear-ip.md`. |

## Para desplegar

1. Migraciones hasta la 0033.
2. Cron del host para `scripts/fail2ban-desbloquear.sh` (ver el runbook).
3. Nueva build de la app (EAS) para el aviso de buzón en iPhone y las guías.
