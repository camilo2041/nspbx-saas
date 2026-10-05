# Runbook 4 — Empresa saturando la plataforma

Una empresa consume tanto (llamadas, CPU, disco, troncal) que las demás se
degradan: audio entrecortado, llamadas que no entran, panel lento. Suele ser
una campaña mal configurada o un voizbot en bucle; a veces es fraude
(entonces: runbook 1).

Severidad: **S2** si afecta a varias empresas; **S1** si además hay gasto
anómalo (salientes internacionales, picos de madrugada).

## Síntomas

- Quejas de varias empresas a la vez: audio cortado, llamadas que no
  conectan, el panel tarda.
- Resumen (app) o Dashboard (panel): CPU o memoria arriba del 85 %.
- Alertas de tráfico saliente («Pico de salientes», «Cerca del cupo diario»).
- `docker stats --no-stream` muestra un contenedor (casi siempre
  `freeswitch` o `voicebot`) en su tope. Para fijar los topes con datos,
  `scripts/medir-recursos.sh` mide un día entero.

## Confirmar quién es

1. Llamadas activas por empresa, desde el servidor:
   ```bash
   docker compose exec freeswitch fs_cli -x "show channels count"
   docker compose exec freeswitch fs_cli -x "show channels" | grep -o "ctx_[a-z0-9-]*" | sort | uniq -c | sort -rn
   ```
   El contexto `ctx_<slug>` dice de qué empresa es cada canal.
2. Campañas en curso de todas las empresas, desde el servidor:
   ```bash
   docker compose exec postgres psql -U nspbx -d nspbx -c \
     "SELECT t.slug, c.name, c.max_concurrency, c.calls_today FROM campaigns c JOIN tenants t ON t.id = c.tenant_id WHERE c.status = 'running'"
   ```
   El administrador de esa empresa ve el detalle en Campañas (avance, «en
   llamada» y topes de hoy).
3. Consumo de IA de la empresa (si el voizbot es el que consume).
4. Disco: Ajustes → Disco y respaldos (grabaciones y respaldos) o
   `df -h` en el servidor.

## Contener (de lo más fino a lo más grueso)

1. **Pausar la campaña** que causa el pico (Campañas → Detener). No da
   números por fallidos: retoma donde quedó.
2. **Bajarle la concurrencia** a esa campaña (Editar → «Llamadas a la vez»)
   y ponerle **topes diarios** de llamadas y minutos.
3. **Cortar las salientes de la empresa**: Empresas → la empresa → Cortar
   salientes (ofrece colgar también las que están en curso). La empresa no
   puede reactivarlas sola.
4. **Bajarle la licencia**: Empresas → Licencia → minutos por día y
   llamadas por segundo. Aplica en el acto en el dialplan.
5. Último recurso: **suspender la licencia** (estado «Suspendida»): la
   empresa deja de operar.

Si la que satura es toda la central y no una empresa:
`MAX_CONCURRENT_CALLS_GLOBAL` en `.env` (y `docker compose up -d backend`)
pone techo a los canales simultáneos; el marcador deja de originar al
llegar, sin tocar las entrantes.

## Recuperar

- Revisar que el audio de las demás empresas se normalizó (una llamada de
  prueba en otra empresa) y que CPU/memoria bajaron.
- Hablar con la empresa: qué campaña, qué cambió. Reactivar con topes
  (concurrencia y diarios) puestos.

## Cerrar

Informe S2. La pregunta de cierre: ¿qué tope faltaba? Una campaña sin
`max_calls_per_day` ni `max_minutes_per_day` o una licencia sin
`max_concurrent_calls` es el hallazgo típico: dejarlo puesto y, si aplica,
como valor por omisión del plan (`services/licensing.py`).
