# Runbook 3 — Sospecha de fuga entre empresas

Una empresa ve, modifica o recibe algo de otra: datos en el panel, una
llamada que termina en la extensión de otra empresa, una grabación ajena.
Es la invariante más importante del sistema (I1–I4): se trata como S1
aunque sea un solo caso.

## Confirmar

1. Pedir a quien lo reporta: usuario, pantalla, hora aproximada y, si lo
   tiene, el `X-Request-ID` de la respuesta (herramientas de desarrollador
   del navegador → Red).
2. Auditoría con ese `request_id` o ese usuario: qué ruta y qué recurso.
3. Reproducir con dos cuentas de empresas distintas en un entorno de prueba.

## Contener

- Si el panel muestra datos ajenos: desactivar temporalmente la ruta
  afectada (o el módulo de la empresa en Empresas) mientras se corrige.
- Si es telefonía (una llamada que cruza): revisar `/fs/dialplan` y
  `/fs/directory` de las dos empresas; si una ruta entrante o una troncal
  está mal asignada, deshabilitarla.
- Verificar que la base esté aislando:
  ```bash
  docker compose logs backend | grep -i "Aislamiento por empresa activo"
  ```
  Si no aparece, `DATABASE_URL_APP` no está en uso: en producción el
  backend no debería haber arrancado (ver `core/arranque.py`).

## Investigar

- La suite de `backend/tests/` corre en CI con RLS y sin RLS: si la fuga
  pasó igual, falta una prueba. Escribirla **primero**, verla fallar contra
  el código actual, y recién ahí corregir.
- Revisar si el código usa la sesión del dueño (`async_session`,
  `get_admin_session`) donde debería usar la de la aplicación: ahí no
  aplican ni RLS ni el filtro automático.
- Alcance: auditoría de todas las acciones de esa ruta desde el último
  despliegue que la tocó.

## Recuperar

Desplegar la corrección con su prueba en verde en CI. Si hubo datos
personales expuestos, evaluar la obligación de notificar (Ley 1581 en
Colombia) con quien corresponda.

## Cerrar

Informe con la prueba nueva que lo cubre. Este runbook no se cierra sin
esa prueba.
