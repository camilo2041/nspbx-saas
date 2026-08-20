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
from sqlalchemy import func, select, text, update

from app.api import ai_usage, appointments as appointments_api, auth as auth_api, calls as calls_api, campaigns, extensions, inbound_routes, logs_ws, queues as queues_api, settings as settings_api, system, trunks, users as users_api, voicebots
from app.core import permissions
from app.core.auth import escribir_requiere, requiere, sesion_obligatoria
from app.core.config import settings
from app.core.database import Base, async_session, engine
from app.core.security import hash_password
from app.models import CampaignNumber, Queue, Trunk, User

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
        "INSERT INTO tenants (id, name, slug, sip_domain, enabled, created_at) "
        "VALUES (1, 'Empresa inicial', 'empresa1', 'empresa1.pbx.local', true, NOW()) "
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
    # usuarios que ya existían son de la empresa inicial.
    stmts += [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER "
        "REFERENCES tenants(id) ON DELETE CASCADE",
        "UPDATE users SET tenant_id = 1 WHERE tenant_id IS NULL",
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


async def _asegurar_admin(session) -> None:
    """Crea el primer administrador si la tabla está vacía.

    Sin esto, activar el login dejaría el panel inaccesible: no habría con
    qué entrar a crear el primer usuario. La contraseña sale de
    ADMIN_PASSWORD; si no está, se genera al azar y se escribe en el log
    del contenedor, que es el único sitio donde el dueño del servidor
    puede leerla. Nunca se usa una contraseña fija tipo "admin/admin":
    quedaría igual en toda instalación que no la cambie.
    """
    hay = (await session.execute(select(func.count(User.id)))).scalar() or 0
    if hay:
        return

    password = os.getenv("ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(12)
    session.add(
        User(
            username="admin",
            full_name="Administrador",
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


async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _COLUMN_PATCHES:
            await conn.execute(text(stmt))
    async with async_session() as session:
        row = await settings_api.get_or_create_settings(session)
        settings_api.apply_to_runtime(row)
        trunks_rows = (await session.execute(select(Trunk))).scalars().all()
        sync_gateways(trunks_rows)
        # mod_callcenter guarda colas/agentes en memoria — se pierden en cada
        # reinicio de FreeSWITCH, así que hay que reescribir su config y
        # recargar el módulo al arrancar el backend.
        queues_rows = (await session.execute(select(Queue))).scalars().all()
        await apply_queues(queues_rows)
        # Números que quedaron en "dialing" por un reinicio/caída previa del
        # backend nunca vuelven a "pending" solos (las tareas de _dial se
        # cancelan sin llegar a su bloque finally) — quedarían excluidos de
        # por vida del ciclo de marcado. Se recuperan al arrancar.
        await session.execute(
            update(CampaignNumber).where(CampaignNumber.status == "dialing").values(status="pending")
        )
        await session.commit()
        await _asegurar_admin(session)
        await voice_prompts.ensure_prompts(session)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

# Mismo motivo: un WebSocket de navegador no puede mandar la cabecera
# Authorization, así que este router valida el token a mano (ver
# app/api/logs_ws.py) en vez de con el guardia global de arriba.
app.include_router(logs_ws.router)

# El login y "quién soy" se protegen dentro del propio router: pedir el
# token no puede exigir tener uno.
app.include_router(auth_api.router)
app.include_router(users_api.router)

# Infraestructura telefónica: solo admin. Estas respuestas traen las
# credenciales SIP en claro.
app.include_router(trunks.router, **_con(permissions.TELEFONIA_GESTIONAR))
app.include_router(extensions.router, **_con(permissions.TELEFONIA_GESTIONAR))
app.include_router(inbound_routes.router, **_con(permissions.TELEFONIA_GESTIONAR))

# El coordinador puede mirar los voizbots pero no editarlos ni lanzar
# síntesis de voz (que se paga por carácter).
app.include_router(
    voicebots.router,
    dependencies=[
        Depends(requiere(permissions.VOIZBOTS_VER)),
        Depends(escribir_requiere(permissions.VOIZBOTS_GESTIONAR)),
    ],
)
app.include_router(campaigns.router, **_con(permissions.CAMPANAS_GESTIONAR))
app.include_router(queues_api.router, **_con(permissions.COLAS_GESTIONAR))
app.include_router(appointments_api.router)  # permisos por endpoint: el agente de IA entra acá
app.include_router(calls_api.router)  # permisos por endpoint: /fs/cdr lo llama FreeSWITCH
app.include_router(ai_usage.router, **_con(permissions.CONSUMO_IA_VER))

# Ajustes y estado del sistema: API keys de los proveedores y control de
# FreeSWITCH.
app.include_router(system.router, **_con(permissions.AJUSTES_GESTIONAR))
app.include_router(settings_api.router, **_con(permissions.AJUSTES_GESTIONAR))


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
