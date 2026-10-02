# Matriz de permisos (rol × ruta)

Generada de las dependencias de cada ruta por `backend/tests/test_matriz_permisos.py`, que
además prueba cada celda ✗ contra el backend (403). No se edita a mano: después de cambiar
un permiso, `ACTUALIZAR_MATRIZ=1 python -m pytest tests/test_matriz_permisos.py`.

Son los permisos por omisión de cada rol; cada empresa puede ajustarlos en Roles y permisos.
«global» = solo con una empresa en la instalación (si hay varias, solo la plataforma).

| Método | Ruta | Permiso | Admin | Supervisor | Coordinador | Asesor |
|---|---|---|---|---|---|---|
| GET | `/api/ai-usage/calls` | `consumo_ia:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/ai-usage/daily` | `consumo_ia:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/ai-usage/summary` | `consumo_ia:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/appointments` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/appointments` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/appointments/agent/availability` | sesión (agente externo) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/appointments/agent/book` | sesión (agente externo) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/appointments/agent/cancel` | sesión (agente externo) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/appointments/agent/reschedule` | sesión (agente externo) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/appointments/availability` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/appointments/gestion` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| DELETE | `/api/appointments/{appointment_id}` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| PUT | `/api/appointments/{appointment_id}` | `citas:gestionar` | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/assistant/chat` | sesión (asistente) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/dispositivo` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| DELETE | `/api/auth/dispositivo/{platform}` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/dnd` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/login` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/logout` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/auth/me` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/auth/mfa` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/mfa/activar` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/mfa/desactivar` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/mfa/iniciar` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/mfa/verificar` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/auth/mi-entorno` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/password` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/probar-push` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/refresh` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/auth/sesiones` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/auth/sesiones/cerrar-todas` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| DELETE | `/api/auth/sesiones/{sesion_id}` | sesión (la propia cuenta) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/dias` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/serie` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/stats` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/{call_id}` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/{call_id}/recording` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/calls/{call_id}/summary` | `llamadas:ver_propias` | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/campaigns` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/campaigns` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/horario` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/list/detail` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/campaigns/{campaign_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/{campaign_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/campaigns/{campaign_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/{campaign_id}/listas` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/campaigns/{campaign_id}/listas/{lista_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/campaigns/{campaign_id}/numbers` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/{campaign_id}/numbers` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/campaigns/{campaign_id}/numbers` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/campaigns/{campaign_id}/numbers/{number_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/campaigns/{campaign_id}/numbers/{number_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/campaigns/{campaign_id}/retry` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/campaigns/{campaign_id}/start` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/campaigns/{campaign_id}/stats` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/campaigns/{campaign_id}/stop` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/claves-api` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/claves-api` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/claves-api/escopos` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/claves-api/{key_id}` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/cobranza/debts` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/cobranza/debts` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/cobranza/debts/{debt_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/cobranza/debts/{debt_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/cobranza/promises` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/cobranza/promises/{promise_id}` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/cobranza/summary` | `campanas:gestionar` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/consumo` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/consumo/csv` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/crm/campos` | `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/campos` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/crm/campos/{campo_id}` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/crm/campos/{campo_id}` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/crm/contactos` | `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/contactos` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/crm/contactos/{contacto_id}` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/crm/contactos/{contacto_id}` | `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/crm/contactos/{contacto_id}` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/contactos/{contacto_id}/notas` | `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/importar` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/importar/vista-previa` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| GET | `/api/crm/no-llamar` | `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/crm/no-llamar` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/crm/no-llamar/{no_llamar_id}` | `crm:gestionar`, `crm:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/csp-report` | sesión (avisos de CSP del navegador, sin sesión) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/extensions` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/extensions` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/extensions/reload` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/extensions/{extension_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/extensions/{extension_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/extensions/{extension_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/extensions/{extension_id}/call` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/inbound-routes` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/inbound-routes` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/inbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/inbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/inbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/outbound-routes` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/outbound-routes` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/outbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/outbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/outbound-routes/{route_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/alertas` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/auditoria` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/consumo` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/consumo/csv` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/csp` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/destinos-bloqueados` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| PUT | `/api/plataforma/destinos-bloqueados` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/plataforma/salientes` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| PUT | `/api/plataforma/salientes` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/plataforma/salientes/colgar` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/privacidad/titular/consultar` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/privacidad/titular/suprimir` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/queues` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/queues` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| DELETE | `/api/queues/{queue_id}` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/queues/{queue_id}` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| PUT | `/api/queues/{queue_id}` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/queues/{queue_id}/status` | `colas:gestionar` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/role-permissions` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/role-permissions` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/security/alertas` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/security/auditoria` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/security/bans` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/security/claves-debiles` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/system/detect-ip` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/system/diagnostics` | `ajustes:gestionar` · global | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/system/maintenance` | `ajustes:gestionar` · global | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/system/maintenance/backup-now` | `ajustes:gestionar` · global | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/system/recursos` | `ajustes:gestionar` · global | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/system/salientes` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/system/salientes/colgar` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/system/settings` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/system/settings` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/system/status` | `ajustes:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/tenants` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/tenants` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| DELETE | `/api/tenants/{tenant_id}` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| PUT | `/api/tenants/{tenant_id}` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/tenants/{tenant_id}/cerrar-sesiones` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/tenants/{tenant_id}/licencia` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| PUT | `/api/tenants/{tenant_id}/licencia` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| POST | `/api/tenants/{tenant_id}/salientes/colgar` | `empresas:gestionar` | ✗ | ✗ | ✗ | ✗ |
| GET | `/api/trunks` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/trunks` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/trunks/{trunk_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/trunks/{trunk_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/trunks/{trunk_id}` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/trunks/{trunk_id}/rescan` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/trunks/{trunk_id}/status` | `telefonia:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/users` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/users` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| GET | `/api/users/roles` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| DELETE | `/api/users/{user_id}` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| PUT | `/api/users/{user_id}` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/users/{user_id}/cerrar-sesiones` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/users/{user_id}/mfa/reset` | `usuarios:gestionar` | ✓ | ✗ | ✗ | ✗ |
| POST | `/api/v1/campanas/{campaign_id}/numeros` | sesión (API pública) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/citas` | sesión (API pública) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/citas` | sesión (API pública) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/consumo` | sesión (API pública) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/llamadas` | sesión (API pública) | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/voicebots` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/voicebots` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/voicebots/probar/datos` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/voicebots/reload` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/voicebots/tts/voices` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| DELETE | `/api/voicebots/{bot_id}` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/voicebots/{bot_id}` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/voicebots/{bot_id}` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/voicebots/{bot_id}/flow` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| PUT | `/api/voicebots/{bot_id}/flow` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| DELETE | `/api/voicebots/{bot_id}/flow/nodes/{node_id}/audio` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/voicebots/{bot_id}/flow/nodes/{node_id}/audio` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/voicebots/{bot_id}/flow/nodes/{node_id}/tts` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| DELETE | `/api/voicebots/{bot_id}/greeting` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/voicebots/{bot_id}/greeting` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/voicebots/{bot_id}/probar` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| POST | `/api/voicebots/{bot_id}/tts` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/voicebots/{bot_id}/versiones` | `voizbots:ver` | ✓ | ✓ | ✓ | ✗ |
| POST | `/api/voicebots/{bot_id}/versiones/{version_id}/restaurar` | `voizbots:gestionar`, `voizbots:ver` | ✓ | ✓ | ✗ | ✗ |
| GET | `/api/webcall/config` | sesión (widget de llamada web) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/webcall/session` | sesión (widget de llamada web) | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/webcall/session/{username}/end` | sesión (widget de llamada web) | ✓ | ✓ | ✓ | ✓ |
