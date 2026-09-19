import logging
import os
import secrets

# Sin esto, los logger.info() de todo el proyecto se perdían en silencio:
# uvicorn configura SUS PROPIOS loggers ("uvicorn", "uvicorn.error") pero
# nunca toca el logger raíz, así que sin ningún handler propio Python solo
# saca por stderr los WARNING+ (el "handler de último recurso"). Costó
# darse cuenta al verificar el contenedor "voicebot" recién separado: no
# aparecía ni el log de "arrancó" aunque todo funcionaba bien.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text, update

from app.api import ai_usage, appointments as appointments_api, assistant, auth as auth_api, calls as calls_api, campaigns, cobranza, extensions, fs_push, inbound_routes, logs_ws, queues as queues_api, settings as settings_api, system, tenants as tenants_api, trunks, users as users_api, voicebots, webcall as webcall_api
from app.core import permissions
from app.core.auth import escribir_requiere, licencia_operativa, requiere, requiere_modulo, sesion_obligatoria
from app.core.config import settings
from app.core.database import Base, async_session, engine, verificar_rol_sin_privilegios
from app.core.security import hash_password
from app.models import CampaignNumber, Queue, Tenant, Trunk, User

logger = logging.getLogger(__name__)
from app.services import voice_prompts, xml_endpoints
from app.services.gateways import sync_gateways
from app.services.queues_sync import apply_queues
from app.workers.dialer import dialer
from app.workers.maintenance import maintenance

# create_all no altera tablas existentes: estas columnas se agregaron
# después del primer despliegue, así que se parchan manualmente.
_COLUMN_PATCHES = [
    "ALTER TABLE trunks DROP COLUMN IF EXISTS register",
    "ALTER TABLE trunks ADD COLUMN IF NOT EXISTS register_enabled BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE trunks ADD COLUMN IF NOT EXISTS caller_id_number VARCHAR(30)",
    "ALTER TABLE trunks ADD COLUMN IF NOT EXISTS transport VARCHAR(10) NOT NULL DEFAULT 'udp'",
    "ALTER TABLE trunks ADD COLUMN IF NOT EXISTS ping INTEGER",
    "ALTER TABLE trunks ADD COLUMN IF NOT EXISTS codec_prefs VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS sip_ws_url VARCHAR(255) NOT NULL DEFAULT 'ws://localhost:5066'",
    "ALTER TABLE voicebots ADD COLUMN IF NOT EXISTS greeting_audio_path VARCHAR(500)",
    "ALTER TABLE voicebots ADD COLUMN IF NOT EXISTS flow_json TEXT",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS sip_server_ip VARCHAR(255) NOT NULL DEFAULT '192.168.100.6'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS sip_server_port INTEGER NOT NULL DEFAULT 5060",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS elevenlabs_api_key VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS agent_webhook_secret VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS deepseek_api_key VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS record_all_calls BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS allow_international BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS sesiones_desde TIMESTAMP",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_voice_provider VARCHAR(20) NOT NULL DEFAULT 'elevenlabs'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_voice_id VARCHAR(100) NOT NULL DEFAULT 'Xb7hH8MSUJpSbSDYk0k2'",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS uuid VARCHAR(64)",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS caller_name VARCHAR(100)",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS billsec INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS hangup_cause VARCHAR(50)",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS recording_path VARCHAR(500)",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS answered_at TIMESTAMP",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_call_logs_uuid ON call_logs (uuid)",
    # Última defensa contra la doble reserva: agendar consulta si el hueco
    # está libre y DESPUÉS inserta, así que dos llamadas simultáneas del
    # voizbot pueden colarse en el mismo horario. El índice parcial deja que
    # convivan varias canceladas en la misma hora, pero solo una confirmada.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_appointments_slot "
    "ON appointments (appointment_date) WHERE status = 'confirmed'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_tts_per_1k_chars DOUBLE PRECISION NOT NULL DEFAULT 0.0655",
    # La fila ya existía con el 0.30 estimado a ojo; se recalibra al valor
    # real del panel del proveedor, salvo que alguien la haya ajustado.
    "UPDATE system_settings SET rate_tts_per_1k_chars = 0.0655 WHERE rate_tts_per_1k_chars = 0.30",
    # Ídem con el modelo: las tarifas de lista ignoraban el descuento por
    # caché y sobreestimaban 7,5 veces el gasto real medido.
    "UPDATE system_settings SET rate_llm_in_per_1m = 0.04 WHERE rate_llm_in_per_1m = 0.27",
    "UPDATE system_settings SET rate_llm_out_per_1m = 0.04 WHERE rate_llm_out_per_1m = 1.10",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS deepgram_api_key VARCHAR(200)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_stt_provider VARCHAR(20) NOT NULL DEFAULT 'elevenlabs'",
    "ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS stt_provider VARCHAR(20)",
    # El resumen se arma transcribiendo la grabación cuando alguien lo pide;
    # guardar la conversación era duplicar lo que el audio ya contiene.
    "ALTER TABLE ai_call_usage DROP COLUMN IF EXISTS transcript",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE ai_call_usage DROP COLUMN IF EXISTS summary",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_stt_per_minute DOUBLE PRECISION NOT NULL DEFAULT 0.0",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_dg_tts_per_1k_chars DOUBLE PRECISION NOT NULL DEFAULT 0.030",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_dg_stt_per_minute DOUBLE PRECISION NOT NULL DEFAULT 0.00483",
    # Scribe en tiempo real cuesta $0,39/hora = $0,0065/minuto. Estaba en
    # cero porque no lo teníamos; ya con el dato, se completa.
    "UPDATE system_settings SET rate_stt_per_minute = 0.0065 WHERE rate_stt_per_minute = 0",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_llm_in_per_1m DOUBLE PRECISION NOT NULL DEFAULT 0.27",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS rate_llm_out_per_1m DOUBLE PRECISION NOT NULL DEFAULT 1.10",
    # Respaldo automático de Postgres y retención de grabaciones — ver
    # app/workers/maintenance.py.
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS backup_enabled BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS backup_retention_days INTEGER NOT NULL DEFAULT 14",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS last_backup_at TIMESTAMP",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS last_backup_ok BOOLEAN",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS last_backup_error VARCHAR(500)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS recordings_retention_days INTEGER NOT NULL DEFAULT 90",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS recordings_max_gb DOUBLE PRECISION NOT NULL DEFAULT 20.0",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS backups_max_gb DOUBLE PRECISION NOT NULL DEFAULT 5.0",
    # Protección contra fraude telefónico y contra saturar la troncal —
    # ver app/services/config_generator.py y app/workers/dialer.py.
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS max_call_duration_minutes INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS max_concurrent_calls INTEGER NOT NULL DEFAULT 20",
    # El LLM del voizbot deja de estar atado a DeepSeek en el código (ver
    # app/services/llm.py) — se migra la key que ya tenían configurada para
    # que no haya que volver a pegarla, y se borra la columna vieja porque
    # ya no la lee nada.
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_llm_provider_name VARCHAR(60) NOT NULL DEFAULT 'DeepSeek'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_llm_base_url VARCHAR(255) NOT NULL DEFAULT 'https://api.deepseek.com/v1'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_llm_model VARCHAR(100) NOT NULL DEFAULT 'deepseek-chat'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ai_llm_api_key VARCHAR(255)",
    "UPDATE system_settings SET ai_llm_api_key = deepseek_api_key "
    "WHERE ai_llm_api_key IS NULL AND deepseek_api_key IS NOT NULL",
    "ALTER TABLE system_settings DROP COLUMN IF EXISTS deepseek_api_key",
    # Campañas de confirmación de citas: mensaje de apertura con
    # {variables} por campaña, y los valores de esas variables por número
    # — ver app/services/templating.py y app/workers/dialer.py.
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS message_template TEXT",
    "ALTER TABLE campaign_numbers ADD COLUMN IF NOT EXISTS extra_data TEXT",
    # Registro de gestión: qué hizo cada llamada sobre la agenda (no solo
    # si "resolved"), y a qué cita EXACTA se refería un número de
    # campaña — ver app/services/ai_agent.py y app/api/campaigns.py.
    "ALTER TABLE campaign_numbers ADD COLUMN IF NOT EXISTS appointment_id "
    "INTEGER REFERENCES appointments(id) ON DELETE SET NULL",
    "ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS action VARCHAR(20)",
    "ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS appointment_id "
    "INTEGER REFERENCES appointments(id) ON DELETE SET NULL",
    "ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS action_appointment_date TIMESTAMP",
    "ALTER TABLE ai_call_usage ADD COLUMN IF NOT EXISTS action_patient_name VARCHAR(150)",
    # Intención del voizbot por campaña (confirmar / cobranza / …) — ver
    # Campaign.ai_intent en los modelos.
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS ai_intent VARCHAR(30)",
    # Subdominio del panel por empresa (ver Tenant.subdomain). Se siembra
    # del slug para que las empresas existentes queden con su subdominio
    # sin migrar datos a mano.
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS subdomain VARCHAR(80)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_subdomain ON tenants (subdomain)",
    "UPDATE tenants SET subdomain = slug WHERE subdomain IS NULL",
    # Tipo de negocio de la empresa (general | clinica | cobranza).
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS business_type VARCHAR(30) NOT NULL DEFAULT 'general'",
    # Módulos de la empresa (CSV: "voicebot,pbx"). Las existentes quedan
    # con el pack completo.
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS modules VARCHAR(120) NOT NULL DEFAULT 'voicebot,pbx'",
    # Licencia por empresa (tabla nueva; create_all la crea). Las empresas
    # existentes reciben una licencia trial de 15 días para no cortarles
    # la operación de golpe.
    "INSERT INTO licenses (tenant_id, plan, status, started_at, expires_at, created_at, updated_at) "
    "SELECT id, 'trial', 'trial', NOW(), NOW() + INTERVAL '15 days', NOW(), NOW() "
    "FROM tenants ON CONFLICT (tenant_id) DO NOTHING",
    # Conector Issabel (ARI): base URL, credenciales y app Stasis. Vacíos =
    # desactivado (NSPBX usa su FreeSWITCH).
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ari_base_url VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ari_user VARCHAR(80)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ari_password VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ari_app VARCHAR(80) NOT NULL DEFAULT 'nspbx'",
    # Widget de llamada web ("hablar con un agente") — ver app/api/webcall.py.
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_enabled BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_queue_id INTEGER "
    "REFERENCES queues(id) ON DELETE SET NULL",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_max_concurrent INTEGER NOT NULL DEFAULT 5",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_turnstile_site_key VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_turnstile_secret VARCHAR(255)",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_schedule TEXT",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_greeting VARCHAR(255) "
    "DEFAULT 'Presione para hablar con un agente'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_button_text VARCHAR(120) "
    "DEFAULT 'Hablar con un agente'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS webcall_offline_text VARCHAR(255) "
    "DEFAULT 'Estamos fuera de horario de atención'",
]

# --- Multiempresa: paso 1 -------------------------------------------
# Ver docs/arquitectura-multitenant.md.
#
# Tablas que pasan a pertenecer a una empresa. `users` NO está acá: su
# tenant_id admite NULL para el usuario de la plataforma (ver el modelo),
# así que se trata aparte, sin SET NOT NULL.
_TABLAS_CON_TENANT = [
    "trunks",
    "extensions",
    "voicebots",
    "campaigns",
    "campaign_numbers",
    "system_settings",
    "call_logs",
    "ai_call_usage",
    "queues",
    "inbound_routes",
    "appointments",
    "debts",
    "payment_promises",
    "licenses",
    "device_tokens",
]

# Restricciones que Postgres creó con nombre automático cuando la columna
# era `unique=True`. Hay que soltarlas ANTES de crear las compuestas: si
# quedaran, la vieja seguiría prohibiendo que dos empresas usen el mismo
# número de extensión o el mismo nombre de troncal — justo lo que este
# paso viene a habilitar. Y el error que daría ("duplicate key") no
# menciona en ningún momento que la culpa es de una restricción heredada
# del modelo de una sola empresa.
_UNIQUES_VIEJOS = [
    ("trunks", "trunks_name_key"),
    ("extensions", "extensions_number_key"),
    ("voicebots", "voicebots_name_key"),
    ("campaigns", "campaigns_name_key"),
    ("queues", "queues_name_key"),
    ("queues", "queues_extension_key"),
]

_UNIQUES_NUEVOS = [
    ("ux_trunks_tenant_name", "trunks (tenant_id, name)"),
    ("ux_extensions_tenant_number", "extensions (tenant_id, number)"),
    ("ux_voicebots_tenant_name", "voicebots (tenant_id, name)"),
    ("ux_campaigns_tenant_name", "campaigns (tenant_id, name)"),
    ("ux_queues_tenant_name", "queues (tenant_id, name)"),
    ("ux_queues_tenant_extension", "queues (tenant_id, extension)"),
    ("ux_system_settings_tenant", "system_settings (tenant_id)"),
    # El DID sí es único en TODA la plataforma: una llamada entrante solo
    # trae el número marcado para decidir a qué empresa pertenece.
    ("ux_inbound_routes_did", "inbound_routes (did_pattern)"),
]


def _parches_multiempresa() -> list[str]:
    """SQL del paso 1, en un orden que no es negociable.

    Primero la empresa inicial, después la columna admitiendo NULL,
    después el relleno, y recién entonces el NOT NULL. Crear la columna
    como NOT NULL de una vez falla en cualquier base que ya tenga datos,
    porque no habría con qué llenar las filas existentes.
    """
    stmts: list[str] = [
        # La empresa que hereda todo lo que ya existía. Con id fijo en 1
        # para que el relleno de abajo no dependa de ninguna consulta.
        #
        # business_type/modules se listan explícitos (no solo confiar en
        # el DEFAULT de la columna): en una base NUEVA, create_all() ya
        # crea `tenants` con el esquema actual —business_type/modules
        # NOT NULL sin DEFAULT a nivel de Postgres, porque el `default=`
        # de SQLAlchemy es del lado ORM, no un DEFAULT de columna—. El
        # ALTER ADD COLUMN IF NOT EXISTS de más abajo no vuelve a correr
        # sobre una columna que ya existe, así que sin esto el INSERT
        # revienta por NOT NULL en cualquier despliegue desde cero.
        #
        # subdomain también va explícito: el `UPDATE tenants SET subdomain
        # = slug` que lo siembra corre ANTES que este INSERT (va en la
        # lista base, este INSERT se agrega después), así que sobre una
        # base nueva nunca alcanza a ver esta fila.
        "INSERT INTO tenants (id, name, slug, sip_domain, subdomain, business_type, modules, enabled, created_at) "
        "VALUES (1, 'Empresa inicial', 'empresa1', 'empresa1.pbx.local', 'empresa1', 'general', 'voicebot,pbx', true, NOW()) "
        "ON CONFLICT (id) DO NOTHING",
        # Sin esto, la próxima empresa creada desde el panel pediría el id
        # 1 y chocaría con la de arriba.
        "SELECT setval('tenants_id_seq', (SELECT COALESCE(MAX(id), 1) FROM tenants), true)",
    ]

    for tabla in _TABLAS_CON_TENANT:
        stmts += [
            f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS tenant_id INTEGER "
            "REFERENCES tenants(id) ON DELETE CASCADE",
            f"UPDATE {tabla} SET tenant_id = 1 WHERE tenant_id IS NULL",
            f"ALTER TABLE {tabla} ALTER COLUMN tenant_id SET NOT NULL",
            f"CREATE INDEX IF NOT EXISTS ix_{tabla}_tenant_id ON {tabla} (tenant_id)",
        ]

    # users aparte: admite NULL, así que no lleva SET NOT NULL. Los
    # usuarios que ya existían son de la empresa inicial — EXCEPTO los de
    # la PLATAFORMA (rol 'plataforma', sin empresa), que siempre quedan
    # en NULL a propósito: es la señal de "administra todas las empresas".
    # La migración vieja (sin el filtro de rol) los había metido en la
    # empresa 1; este UPDATE también los corrige.
    stmts += [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER "
        "REFERENCES tenants(id) ON DELETE CASCADE",
        "UPDATE users SET tenant_id = 1 WHERE tenant_id IS NULL AND role <> 'plataforma'",
        "UPDATE users SET tenant_id = NULL WHERE role = 'plataforma'",
        "CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)",
    ]

    for tabla, viejo in _UNIQUES_VIEJOS:
        stmts.append(f"ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {viejo}")

    # extensions.number va aparte y NO se resuelve con DROP CONSTRAINT.
    # Declaraba `unique=True, index=True` a la vez, y con esa combinación
    # SQLAlchemy no crea una constraint `extensions_number_key` sino un
    # ÍNDICE ÚNICO llamado `ix_extensions_number`. El DROP CONSTRAINT de
    # arriba no lo encuentra, se ejecuta sin error, y el índice sobrevive
    # prohibiendo que dos empresas usen el mismo número. El fallo aparece
    # recién al dar de alta la segunda empresa, con un "duplicate key"
    # que no menciona nada de todo esto.
    # Se recrea sin UNIQUE: buscar por número sigue siendo útil.
    stmts += [
        "DROP INDEX IF EXISTS ix_extensions_number",
        "CREATE INDEX IF NOT EXISTS ix_extensions_number ON extensions (number)",
    ]
    for nombre, destino in _UNIQUES_NUEVOS:
        stmts.append(f"CREATE UNIQUE INDEX IF NOT EXISTS {nombre} ON {destino}")

    # La última defensa contra la doble reserva también era global: sin
    # tenant_id, una cita a las 9:00 de una empresa impediría que
    # cualquier OTRA agendara a esa misma hora. El síntoma sería un
    # "horario ocupado" en un consultorio con la agenda vacía.
    stmts += [
        "DROP INDEX IF EXISTS ux_appointments_slot",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_appointments_tenant_slot "
        "ON appointments (tenant_id, appointment_date) WHERE status = 'confirmed'",
    ]
    return stmts


_COLUMN_PATCHES += _parches_multiempresa()


# --- Multiempresa: paso 1b, Row-Level Security ----------------------
# Hasta acá el aislamiento dependía de que cada consulta recordara filtrar
# por tenant_id. Estas políticas lo mueven al motor: aunque el filtro
# falte, Postgres no devuelve filas de otra empresa.
#
# `users` también entra: guarda correos y hashes de contraseña, así que
# una consulta sin filtrar ahí es peor que una de negocio.
_TABLAS_CON_RLS = _TABLAS_CON_TENANT + ["users"]

# La empresa activa sale de una variable de sesión que fija la aplicación
# en cada transacción (ver core/database.py).
#
# El segundo argumento `true` de current_setting es "missing_ok": sin él,
# una conexión que todavía no la fijó revienta con un error de Postgres
# en vez de simplemente no ver nada. Con NULLIF, si no está fijada la
# comparación da NULL, que no es verdadero, y no se devuelve ninguna
# fila. Es decir: el modo de falla por omisión es NO MOSTRAR NADA, nunca
# mostrarlo todo — que es la propiedad que hace que esto valga la pena.
_EMPRESA_ACTIVA = "NULLIF(current_setting('app.tenant_id', true), '')::int"


def _parches_rls() -> list[str]:
    """Rol de aplicación, permisos y políticas por tabla."""
    from urllib.parse import urlsplit, unquote

    stmts: list[str] = []

    # El rol y su contraseña se deducen de DATABASE_URL_APP en vez de
    # configurarse aparte: un tercer lugar donde repetir el mismo secreto
    # es un tercer lugar donde puede quedar desincronizado, y el síntoma
    # sería un backend que no arranca por credenciales inválidas.
    if settings.database_url_app:
        partes = urlsplit(settings.database_url_app)
        rol = unquote(partes.username or "")
        clave = unquote(partes.password or "")
        if rol and clave:
            # Comillas dobladas: la contraseña va como literal SQL y no
            # hay forma de parametrizar un CREATE ROLE.
            lit = clave.replace("'", "''")
            stmts += [
                f"""
                DO $$
                BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rol}') THEN
                    CREATE ROLE {rol} LOGIN PASSWORD '{lit}';
                  ELSE
                    ALTER ROLE {rol} LOGIN PASSWORD '{lit}';
                  END IF;
                END $$;
                """,
                # Sin NOSUPERUSER/NOBYPASSRLS explícitos no hay riesgo
                # —CREATE ROLE no los da— pero sí lo hay si alguien los
                # concedió a mano alguna vez para destrabar un permiso.
                f"ALTER ROLE {rol} NOSUPERUSER NOBYPASSRLS",
                f"GRANT USAGE ON SCHEMA public TO {rol}",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {rol}",
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {rol}",
                # Para las tablas que se creen DESPUÉS de esta migración:
                # sin esto, agregar una tabla nueva rompe la aplicación
                # con un "permission denied" que no menciona que el
                # problema es un permiso por omisión que nadie otorgó.
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {rol}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {rol}",
            ]

    for tabla in _TABLAS_CON_RLS:
        stmts += [
            f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY",
            # DROP + CREATE porque Postgres no tiene CREATE POLICY IF NOT
            # EXISTS, y esto tiene que poder correrse en cada arranque.
            f"DROP POLICY IF EXISTS p_tenant ON {tabla}",
            f"CREATE POLICY p_tenant ON {tabla} "
            f"USING (tenant_id = {_EMPRESA_ACTIVA}) "
            # WITH CHECK además de USING: sin él se puede LEER solo lo
            # propio pero ESCRIBIR con el tenant_id de otra empresa —
            # insertar en la central ajena, que es peor que leerla.
            f"WITH CHECK (tenant_id = {_EMPRESA_ACTIVA})",
        ]
    return stmts


_COLUMN_PATCHES += _parches_rls()


async def _asegurar_admin(session) -> None:
    """Crea el primer administrador si la tabla está vacía.

    Sin esto, activar el login dejaría el panel inaccesible: no habría con
    qué entrar a crear el primer usuario. La contraseña sale de
    ADMIN_PASSWORD; si no está, se genera al azar y se escribe en el log
    del contenedor, que es el único sitio donde el dueño del servidor
    puede leerla. Nunca se usa una contraseña fija tipo "admin/admin":
    quedaría igual en toda instalación que no la cambie.

    El admin se crea con la PRIMERA empresa (tenant_id): con Row-Level
    Security, un usuario sin empresa no ve nada en las rutas normales —
    las políticas no devuelven filas sin `app.tenant_id`, y eso hace que
    hasta su propio login responda 401. Si el admin ya existía de un
    arranque anterior sin tenant (creado antes de la migración
    multiempresa), se le asigna la primera empresa también.
    """
    tenante = (
        await session.execute(select(Tenant).order_by(Tenant.id).limit(1))
    ).scalar_one_or_none()
    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one_or_none()
    if admin:
        if admin.tenant_id is None and tenante is not None:
            admin.tenant_id = tenante.id
            await session.commit()
        return

    password = os.getenv("ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(12)
    session.add(
        User(
            username="admin",
            full_name="Administrador",
            tenant_id=tenante.id if tenante else None,
            password_hash=hash_password(password),
            role=permissions.ADMIN,
            enabled=True,
        )
    )
    await session.commit()
    if os.getenv("ADMIN_PASSWORD", "").strip():
        logger.warning("Usuario inicial creado: admin (contraseña tomada de ADMIN_PASSWORD)")
    else:
        logger.warning(
            "=" * 62 + "\n  Usuario inicial creado\n    usuario:    admin\n"
            f"    contraseña: {password}\n"
            "  Cámbiala al entrar. No vuelve a mostrarse.\n" + "=" * 62
        )


async def _asegurar_plataforma(session) -> None:
    """Crea el usuario de la PLATAFORMA (sin empresa) si no existe.

    Es quien da de alta empresas desde el panel. Usa la misma contraseña
    de ADMIN_PASSWORD que el admin inicial (misma clave, distinto rol):
    si alguien entra como `plataforma`, administra empresas; como
    `admin`, administra la empresa inicial.
    """
    existe = (
        await session.execute(select(User).where(User.username == "plataforma"))
    ).scalar_one_or_none()
    if existe:
        # La migración de arranque puede haberle metido tenant_id=1 (el
        # UPDATE de relleno de la empresa inicial). La plataforma NO
        # pertenece a ninguna empresa; se corrige en cada arranque.
        if existe.tenant_id is not None:
            existe.tenant_id = None
            await session.commit()
        return
    password = os.getenv("ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(12)
    session.add(
        User(
            username="plataforma",
            full_name="Operador de plataforma",
            tenant_id=None,  # sin empresa: administra todas
            role=permissions.PLATAFORMA,
            password_hash=hash_password(password),
            enabled=True,
        )
    )
    await session.commit()
    logger.warning("Usuario de plataforma creado: 'plataforma' con la misma contraseña que 'admin'")


async def lifespan(app: FastAPI):
    # Las migraciones van con el motor del DUEÑO, no con el de la
    # aplicación: el rol restringido está sujeto a las políticas que
    # estas mismas sentencias crean, así que un UPDATE de relleno vería
    # cero filas y la migración "terminaría bien" sin haber hecho nada.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _COLUMN_PATCHES:
            await conn.execute(text(stmt))
    # Después de crear el rol y las políticas, comprobar que el rol con
    # el que se va a atender NO puede saltárselas. Va acá y no antes
    # porque el rol se crea recién en la migración de arriba.
    await verificar_rol_sin_privilegios()
    async with async_session() as session:
        # Ajustes y ESL por empresa. Los ajustes se siembran desde cada
        # tenant (fs_domain sale de Tenant.sip_domain) y la config de
        # infraestructura (host/puerto/password de ESL) se vuelca al
        # singleton de proceso: es única por instalación y todas las
        # empresas comparten el mismo FreeSWITCH, así que basta con la de
        # la primera.
        tenantes_rows = (await session.execute(select(Tenant))).scalars().all()
        dominios: dict[int, str] = {}
        slugs: dict[int, str] = {}
        for t in tenantes_rows:
            fila_ajustes = await settings_api.get_or_create_settings(session, t.id)
            dominios[t.id] = fila_ajustes.fs_domain or t.sip_domain
            slugs[t.id] = t.slug
            # Con varias empresas cada una tiene su fila y la última reconfiguraba el
            # Event Socket de todas. Solo con una se aplica (ver core/alcance.py).
            if len(tenantes_rows) == 1:
                settings_api.apply_to_runtime(fila_ajustes)
        trunks_rows = (await session.execute(select(Trunk))).scalars().all()
        sync_gateways(trunks_rows, slugs)
        # mod_callcenter guarda colas/agentes en memoria — se pierden en cada
        # reinicio de FreeSWITCH, así que hay que reescribir su config y
        # recargar el módulo al arrancar el backend.
        queues_rows = (await session.execute(select(Queue))).scalars().all()
        await apply_queues(queues_rows, dominios)
        # Números que quedaron en "dialing" por un reinicio/caída previa del
        # backend nunca vuelven a "pending" solos (las tareas de _dial se
        # cancelan sin llegar a su bloque finally) — quedarían excluidos de
        # por vida del ciclo de marcado. Se recuperan al arrancar.
        await session.execute(
            update(CampaignNumber).where(CampaignNumber.status == "dialing").values(status="pending")
        )
        await session.commit()
        await _asegurar_admin(session)
        await _asegurar_plataforma(session)
        for t in tenantes_rows:
            await voice_prompts.ensure_prompts(session, t.id)
    dialer.start()
    maintenance.start()
    yield
    await dialer.stop()
    await maintenance.stop()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    # Autenticación por defecto en TODA la API. `sesion_obligatoria` deja
    # pasar solo el login y lo que no cuelga de /api/ (los endpoints que
    # consume FreeSWITCH). Así una ruta nueva nace protegida: si esto
    # fuera router por router, el día que alguien agregue un endpoint y
    # olvide el guardia, quedaría abierto sin que nadie lo note.
    dependencies=[Depends(sesion_obligatoria)],
)

# Origen abierto pero SIN credenciales. La sesión viaja en la cabecera
# Authorization (nunca en cookies), así que ninguna web ajena puede usar la
# sesión de nadie por CORS; lo que sí necesita ser abierto es el widget de
# llamada web (/api/webcall), que se incrusta en sitios de los clientes.
# Antes era `allow_credentials=True` junto con "*": Starlette lo resuelve
# devolviendo el origen que pida cada petición con credenciales permitidas,
# que equivale a autorizar a cualquier sitio y es justo lo que hay que evitar
# el día que alguien agregue una cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _con(*permisos: str) -> dict:
    return {"dependencies": [Depends(requiere(*permisos))]}


# Sin guardia de permiso: los usa FreeSWITCH, no una persona con sesión.
# El pipeline de IA en vivo (ai_agent) ya NO se monta acá — corre en su
# propio contenedor "voicebot" (ver app/voicebot_server.py), justamente
# para que reconstruir este backend no le corte el audio a una llamada de
# IA en curso.
app.include_router(xml_endpoints.router)

# Mismo motivo: lo llama FreeSWITCH desde el dialplan (mod_curl), sin
# sesión de usuario — ver services/config_generator.py:_append_mobile_push_hook.
app.include_router(fs_push.router)

# Mismo motivo: un WebSocket de navegador no puede mandar la cabecera
# Authorization, así que este router valida el token a mano (ver
# app/api/logs_ws.py) en vez de con el guardia global de arriba.
app.include_router(logs_ws.router)

# El login y "quién soy" se protegen dentro del propio router: pedir el
# token no puede exigir tener uno.
app.include_router(auth_api.router)
app.include_router(users_api.router)

# Infraestructura telefónica: solo admin. Estas respuestas traen las
# credenciales SIP en claro. Además exigen el módulo "pbx" (modelo de
# packs — ver Tenant.modules) y una licencia operativa.
_TELEFONIA = [
    Depends(requiere(permissions.TELEFONIA_GESTIONAR)),
    Depends(requiere_modulo("pbx")),
    Depends(licencia_operativa()),
]
app.include_router(trunks.router, dependencies=_TELEFONIA)
app.include_router(extensions.router, dependencies=_TELEFONIA)
app.include_router(inbound_routes.router, dependencies=_TELEFONIA)
# Colas: su propio permiso, pero también módulo pbx y licencia.
app.include_router(
    queues_api.router,
    dependencies=[
        Depends(requiere(permissions.COLAS_GESTIONAR)),
        Depends(requiere_modulo("pbx")),
        Depends(licencia_operativa()),
    ],
)

# Módulo voicebot: voizbots, campañas y cobranza. También licencia.
_VOICEBOT = [Depends(requiere_modulo("voicebot")), Depends(licencia_operativa())]

# El coordinador puede mirar los voizbots pero no editarlos ni lanzar
# síntesis de voz (que se paga por carácter).
app.include_router(
    voicebots.router,
    dependencies=[
        Depends(requiere(permissions.VOIZBOTS_VER)),
        Depends(escribir_requiere(permissions.VOIZBOTS_GESTIONAR)),
        *_VOICEBOT,
    ],
)
app.include_router(
    campaigns.router,
    dependencies=[Depends(requiere(permissions.CAMPANAS_GESTIONAR)), *_VOICEBOT],
)
app.include_router(
    cobranza.router,
    dependencies=[Depends(requiere(permissions.CAMPANAS_GESTIONAR)), *_VOICEBOT],
)
app.include_router(
    ai_usage.router,
    dependencies=[Depends(requiere(permissions.CONSUMO_IA_VER)), *_VOICEBOT],
)
# Empresas: SOLO el rol de plataforma (usa la sesión del dueño).
app.include_router(
    tenants_api.router,
    dependencies=[Depends(requiere(permissions.EMPRESAS_GESTIONAR))],
)
app.include_router(appointments_api.router)  # permisos por endpoint: el agente de IA entra acá
app.include_router(calls_api.router)  # permisos por endpoint: /fs/cdr lo llama FreeSWITCH
# La lista de exclusión de app/core/auth.py deja pasar /api/webcall/.
app.include_router(webcall_api.router)
app.include_router(assistant.router)  # solo lectura; recorta por rol dentro

# Ajustes y estado del sistema: API keys de los proveedores y control de
# FreeSWITCH.
app.include_router(system.router, **_con(permissions.AJUSTES_GESTIONAR))
app.include_router(settings_api.router, **_con(permissions.AJUSTES_GESTIONAR))


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
