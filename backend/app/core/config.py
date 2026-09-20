from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "NSPBX"

    # Conexión del DUEÑO de las tablas. Se usa para migrar al arrancar y
    # para las dos operaciones que por definición no pueden estar
    # limitadas a una empresa: el login —todavía no se sabe de quién es
    # el usuario que se escribió— y el alta de empresas.
    database_url: str = "postgresql+asyncpg://nspbx:nspbx_secret@localhost:5432/nspbx"

    # Conexión con la que se atiende TODA la operación normal. Es un rol
    # distinto, sin privilegios de dueño y sin BYPASSRLS, para que las
    # políticas de Row-Level Security se le apliquen de verdad: un
    # superusuario —y el usuario por omisión de la imagen de Postgres lo
    # es— se las saltea siempre, incluso con FORCE ROW LEVEL SECURITY.
    #
    # Con RLS activo y esta conexión mal puesta, el aislamiento sería
    # decorativo y nada lo delataría. Por eso el arranque lo comprueba en
    # vez de confiar (ver app/core/database.py).
    #
    # Vacía = se usa la de arriba y NO hay aislamiento por base. Solo
    # tiene sentido en desarrollo.
    database_url_app: str = ""

    fs_esl_host: str = "localhost"
    fs_esl_port: int = 8021
    # Sin "ClueCon" como respaldo: si alguna vez esta clase se instancia
    # sin FS_ESL_PASSWORD en el entorno (fuera de docker-compose, en un
    # script suelto), que quede vacío y falle a la vista, no que caiga en
    # la contraseña de fábrica de FreeSWITCH.
    fs_esl_password: str = ""

    fs_http_base: str = "http://localhost:8080"

    # Secreto que FreeSWITCH manda como query string al pedir /fs/directory
    # y /fs/dialplan (ver xml_curl.conf.xml). Sin esto, cualquiera que
    # llegue al puerto del backend podía pedir /fs/directory y llevarse la
    # contraseña SIP de cada extensión en texto plano, sin loguearse.
    fs_xml_secret: str = ""

    fs_conf_dir: str = "/freeswitch-conf"
    fs_sounds_dir: str = "/freeswitch-sounds"
    # Mismo valor que la ruta montada en docker-compose.yml para el
    # backend y para FreeSWITCH (con otro nombre de punto de montaje).
    recordings_dir: str = "/freeswitch-recordings"
    # Cómo VE FreeSWITCH ese mismo directorio (su propio $${recordings_dir},
    # confirmado con `eval $${recordings_dir}` por ESL) — es el prefijo que
    # trae `recording_path` en el CDR, y hay que pelarlo para reconstruir
    # la ruta LOCAL del backend (que monta el mismo volumen en otro punto).
    fs_recordings_dir: str = "/var/lib/freeswitch/recordings"

    # Volumen APARTE del de Postgres a propósito (ver docker-compose.yml,
    # volumen `pg_backups`): si los dumps vivieran en el mismo volumen que
    # la base, una corrupción del volumen de datos se lleva puesto también
    # el respaldo.
    backups_dir: str = "/backups"

    fs_domain: str = "nspbx.local"

    # Topes de la PLATAFORMA (no de una empresa): disco de grabaciones y de
    # respaldos, y llamadas simultáneas máximas en toda la central. Con varias
    # empresas ninguna puede fijarlos; con una sola, sus Ajustes los sobrescriben.
    recordings_max_gb: float = 20.0
    backups_max_gb: float = 5.0
    max_concurrent_calls_global: int = 200
    # Solo para desarrollo o un modelo propio dentro de tu red: deja que las URLs
    # que fijan las empresas (modelo de IA) apunten a direcciones privadas.
    permitir_urls_privadas: bool = False
    # Proxies inversos delante del backend (Traefik = 1). Define de dónde se toma la
    # IP real del cliente; 0 = sin proxy, se usa la conexión directa.
    proxies_confiables: int = 1

    # Zona horaria del negocio. La agenda (horario de atención, "hoy",
    # "mañana", si un cupo ya pasó) se interpreta siempre en esta zona,
    # sin importar en qué zona corra el contenedor. Ver app/core/clock.py.
    timezone: str = "America/Bogota"

    sip_ws_url: str = "wss://localhost:7443"

    # URL que usa mod_audio_fork (desde el contenedor de FreeSWITCH) para
    # streamear el audio del canal hacia el endpoint websocket del voizbot
    # IA. "voicebot" es el servicio dedicado en docker-compose.yml — vive
    # aparte del backend (API REST) a propósito: si compartieran proceso,
    # cada despliegue del backend (mucho más frecuente) cortaría de
    # cuajo cualquier llamada de IA en curso en ese instante.
    voicebot_ws_base: str = "ws://voicebot:8090/ws/voicebot"

    # Dónde le dice el dialplan a FreeSWITCH que conecte el "socket"
    # (ESL outbound) para entregarle el control de la llamada al voizbot
    # de IA. Mismo motivo que voicebot_ws_base: servicio propio, no el
    # backend. Lo usa app/services/flow_engine.py al generar el dialplan.
    voicebot_esl_socket: str = "voicebot:8085"

    # IP/puerto que deben usar softphones de escritorio (3CXPhone, X-Lite,
    # Zoiper) para registrarse — NO es la URL websocket del softphone del
    # navegador. Debe ser una IP alcanzable por esos programas (LAN o
    # pública con NAT/puertos abiertos), no localhost/127.0.0.1.
    sip_server_ip: str = "192.168.100.6"
    sip_server_port: int = 5060

    # --- TURN (relay de audio para el softphone del navegador) --------
    # El audio de WebRTC viaja por UDP directo al contenedor de
    # FreeSWITCH. Muchas redes —oficinas de clientes, hoteles, datos
    # móviles, y la propia empresa donde corre esto— solo dejan salir
    # 80 y 443, así que ese UDP nunca llega y la llamada conecta muda.
    # Con TURN el navegador manda el audio al relay por TCP/443 (lo
    # único abierto) y coturn se lo entrega a FreeSWITCH por la red
    # interna de Docker.
    #
    # Vacío = desactivado: el softphone usa solo STUN y el audio va
    # directo. Sirve en LAN o con los puertos UDP abiertos.
    turn_host: str = ""
    # El mismo valor que --static-auth-secret de coturn. Con él el
    # backend firma credenciales de un solo uso; nunca se manda al
    # navegador el secreto en sí, solo una firma que caduca.
    turn_secret: str = ""
    # Cuánto vale la credencial firmada. Corta a propósito: solo tiene
    # que durar lo que tarda en establecerse la llamada, no la llamada.
    turn_ttl_segundos: int = 3600

    # --- Push a la app móvil (avisar una llamada entrante) -------------
    # Todo vacío por defecto = push desactivado (services/push.py se
    # limita a loguear una advertencia y no manda nada), igual criterio
    # que turn_host: sin esto configurado, la app sigue sirviendo para
    # llamar con la app abierta, solo no despierta en segundo plano.
    #
    # APNs (voz/VoIP en iOS). Salen de una cuenta de Apple Developer:
    # clave .p8 con capability "Apple Push Notifications service (VoIP)".
    apns_key_id: str = ""
    apns_team_id: str = ""
    # Contenido completo del archivo .p8 (empieza con "-----BEGIN PRIVATE KEY-----").
    apns_auth_key: str = ""
    # Bundle id de la app SIN el sufijo ".voip" — services/push.py se lo agrega.
    apns_bundle_id: str = ""
    # true = usa api.sandbox.push.apple.com (builds de desarrollo/TestFlight interno).
    apns_use_sandbox: bool = False

    # FCM (push en Android). Sale de un proyecto de Firebase: Configuración
    # del proyecto → Cuentas de servicio → Generar nueva clave privada.
    fcm_project_id: str = ""
    # Contenido completo del JSON de la cuenta de servicio (no la ruta).
    fcm_service_account_json: str = ""
    # Alternativa al JSON en una variable (multilínea, incómodo en un .env): ruta de un
    # archivo montado en el contenedor, p. ej. /run/secrets/fcm.json.
    fcm_service_account_file: str = ""


settings = Settings()
