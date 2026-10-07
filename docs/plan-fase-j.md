# Fase J: confianza en producción

**Estado: hecha.**

| Bloque | Dónde | Notas |
|---|---|---|
| J1. Verificación en vivo | `services/verificacion.py`, Plataforma › Empresas, revisión 0034 | 17 pruebas con teléfonos reales y sus pasos. «Comprobar» busca el rastro desde que se empezó (CDR, auditoría de transferencias, mensaje, saludo, devolución); las demás se cierran a mano con nota. Historial por empresa. |
| J3. Errores del panel y la app | `services/errores_cliente.py`, `POST /api/errores`, `frontend/lib/errores.ts`, `mobile/src/errores.ts`, revisión 0035 | Agrupados por firma, sin tokens ni números largos. Con sesión y tope por usuario. «Arreglado» los saca; reaparecen si vuelven a pasar. |
| J2. Calidad de audio | `services/calidad_audio.py`, Reportes › Calidad de audio, revisión 0036 | MOS, % de calidad y paquetes perdidos del CDR (`rtp_audio_in_*`) y el proveedor (`sip_gateway_name`). Punto de color en Llamadas. |
| J4. Retención | `services/retencion.py`, `workers/maintenance.py`, revisión 0037 | La retención borra también transcripciones y resúmenes. «Conservar» en Llamadas. Aviso en Ajustes de lo que se borrará en 7 días. Arreglo: el saludo del buzón ya no vence. |
| J5. Preguntas sin guía | `services/preguntas_sin_guia.py`, Plataforma › Empresas, revisión 0038 | Solo «cómo hago…», sin números ni correos, agrupadas. Las más repetidas son las próximas guías. |

## Para desplegar

1. Migraciones hasta la 0038.
2. Nueva build de la app para que reporte sus errores y sus preguntas sin guía.
3. Empezar la verificación en vivo desde Plataforma › Empresas.
