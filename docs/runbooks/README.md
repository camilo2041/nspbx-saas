# Runbooks

Qué hacer, en orden, cuando algo pasa. Cada uno tiene la misma forma:
**síntomas → confirmar → contener → investigar → recuperar → cerrar**.
Contener va antes que entender: primero se corta la pérdida.

| # | Runbook | Severidad típica |
|---|---|---|
| 1 | [Fraude telefónico en curso](fraude-en-curso.md) | S1 |
| 2 | [Credencial filtrada](credencial-filtrada.md) | S1–S2 |
| 3 | [Sospecha de fuga entre empresas](fuga-entre-empresas.md) | S1 |
| 4 | [Empresa saturando la plataforma](empresa-saturando.md) | S2 |
| 5 | [Base de datos caída o disco lleno](base-caida-disco-lleno.md) | S1 |
| 6 | [Proveedor de IA caído](proveedor-ia-caido.md) | S2–S3 |
| 7 | [Troncal caída](troncal-caida.md) | S2–S3 |
| 8 | [Recuperación total desde respaldo](recuperacion-total.md) | S1 |
| 9 | [Rotación de cada secreto](rotacion-de-secretos.md) | — |

Severidades: **S1** viola una invariante o hay pérdida económica en curso;
**S2** degradación para varias empresas; **S3** una empresa o una función.
Todo S1 y S2 cierra con un informe breve: qué pasó, cuánto duró, a quién
afectó y **qué prueba automática nueva lo habría detectado** (y se agrega).

Herramientas que se usan en varios runbooks:

- **Auditoría**: Empresas → Auditoría de la plataforma, o
  `GET /api/plataforma/auditoria?actor=…&accion=…&resultado=…`. Cada fila
  trae `request_id`, que también aparece en cada línea del log del backend
  (`docker compose logs backend | grep <request_id>`).
- **Alertas de tráfico**: Empresas → Alertas (plataforma) o Seguridad
  (empresa). También llegan a `ALERTAS_WEBHOOK_URL` si está definido.
- **Interruptores de salientes**: Ajustes → Pausar (la empresa), Empresas →
  Cortar salientes (una empresa), Empresas → Cortar todas las salientes.
