# Fase H: guías en pantalla y cabos sueltos de la G

**Estado: hecha.**

| Bloque | Dónde | Notas |
|---|---|---|
| H1. Guías en pantalla | `frontend/lib/guias.ts`, `components/guia.tsx`, asistente | 18 recorridos (cargar una base predictiva, crear extensión, conectar proveedor, escuchar una grabación, festivos, PIN del buzón…). Un recuadro sobre el botón y una tarjeta al lado: no oscurece ni bloquea, y la persona hace los cambios. Se abren desde «Guías» en el asistente, con el botón «Muéstrame» que agrega la IA (`[[guia:id]]`) o con la búsqueda local, que funciona sin IA. |
| H2. Buzón con PIN | `config_generator._append_buzon_remoto` (*96), `/api/buzon/pin`, revisión 0030 | Desde cualquier extensión, o un número entrante con destino «Escuchar mensajes del buzón». El PIN va cifrado en la base y en el dialplan solo como md5 con sal nueva por llamada. 3 intentos por llamada; rechaza PIN fáciles. |
| H3. Tope de inicio de sesión compartido | `core/limitador.py`, tabla `intentos_acceso`, revisión 0031 | Un solo conteo entre réplicas. Si la base no responde, cada réplica cuenta en memoria. |
| H4. Calidad con IA en Consumo IA | `services/calidad.py`, `api/ai_usage.py`, revisión 0032 | Transcripción y tokens de cada evaluación quedan con origen «calidad»: suman al costo, no a las métricas del voizbot. |

## Cómo agregar una guía

1. Marca los botones o campos con `guia="pantalla:accion"` (componentes de `ui.tsx`) o `data-guia`.
2. Agrega la guía en `frontend/lib/guias.ts`, con su permiso y las palabras con que la buscarían.
3. Agrega el mismo id en `GUIAS` de `backend/app/api/assistant.py`. Una prueba exige que coincidan.

## Pendiente de comprobar en vivo

- *96 con una llamada real: el Lua en línea se probó con una sesión simulada (lupa), no contra FreeSWITCH.
- Los avisos de voz nuevos (`buzon_remoto_*`) se generan con el resto. Mientras no existan, suena la voz de respaldo en inglés.
