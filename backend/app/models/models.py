from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.cifrado import TextoCifrado
from app.core.database import Base


def _tenant_fk() -> Mapped[int]:
    """Columna `tenant_id` común a todas las tablas de negocio.

    Va en TODAS y no solo en las "de arriba" —aunque campaign_numbers ya
    llegue a su empresa a través de campaigns— porque las políticas de
    Row-Level Security se evalúan tabla por tabla: una tabla sin la
    columna no puede tener política y queda fuera del aislamiento. Sale
    más barato repetir la columna que razonar cada vez si el JOIN
    protege o no.
    """
    return mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )


class Tenant(Base):
    """Una empresa dentro de la plataforma.

    El aislamiento se apoya en dos identificadores, y conviene entender
    por qué son dos:

    - `slug` es el nombre corto interno. De él salen el contexto del
      dialplan (`ctx_<slug>`) y el prefijo de los gateways
      (`<slug>_troncal`), que son espacios de nombres GLOBALES dentro de
      FreeSWITCH: sin prefijo, dos empresas con una troncal del mismo
      proveedor se pisan el nombre y la segunda no registra.

    - `sip_domain` es lo que ven los teléfonos y lo que FreeSWITCH usa
      para resolver a qué empresa pertenece quien se registra. Se guarda
      explícito en vez de derivarlo del slug para poder darle a un
      cliente su propio dominio más adelante sin migrar nada.
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    sip_domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Subdominio del PANEL de esta empresa (ej. "consultorio-andino" para
    # "consultorio-andino.pbx.example.com"). Es la etiqueta con la que el
    # login sabe en qué empresa estás entrando cuando usás su URL propia.
    # Se siembra igual al slug; se puede editar desde la pantalla Empresas.
    subdomain: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    # Qué tipo de negocio es: general | clinica | cobranza. No cambia el
    # aislamiento (eso lo da tenant_id) pero permite saber de qué se trata
    # cada empresa y ajustar el panel/ajustes en consecuencia (ver
    # get_or_create_settings en app/services/ajustes.py).
    business_type: Mapped[str] = mapped_column(String(30), default="general")
    # Módulos habilitados de la empresa, en CSV: "voicebot,pbx". Es la base
    # del modelo de "packs": una empresa puede ser solo voicebot, solo
    # PBX/call o el pack completo, elegido al crearla y AMPLIABLE después
    # desde la pantalla Empresas. Cada módulo podría vivir como servicio
    # propio más adelante (microservicios); acá se activa/oculta en el
    # panel y en la API por empresa.
    modules: Mapped[str] = mapped_column(String(120), default="voicebot,pbx")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Interruptor de la PLATAFORMA: corta todas las llamadas salientes de la
    # empresa (fraude en curso, falta de pago) sin desactivarla. Solo lo
    # cambia el rol plataforma; la empresa no puede deshacerlo.
    outbound_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Servidor FreeSWITCH de la empresa (docs/escala.md §4). NULL = el
    # principal (el de FS_ESL_HOST / Ajustes), que es lo que había siempre.
    nodo_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodos_freeswitch.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def modules_list(self) -> list[str]:
        return [m.strip() for m in (self.modules or "").split(",") if m.strip()]

    def has_module(self, mod: str) -> bool:
        return mod in self.modules_list

    @property
    def dialplan_context(self) -> str:
        """Contexto del dialplan de esta empresa.

        Existe como propiedad y no como columna para que haya UNA sola
        definición: el generador de configuración y el ruteo de entrantes
        tienen que coincidir carácter por carácter, y dos lugares
        calculándolo por separado es la clase de desajuste que no falla
        —el dialplan simplemente no encuentra el destino— y cuesta horas.
        """
        return f"ctx_{self.slug}"


class Trunk(Base):
    __tablename__ = "trunks"
    # El nombre pasa a ser único POR EMPRESA, no global: dos clientes
    # pueden tener su troncal "principal" sin pisarse.
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="ux_trunks_tenant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    gateway_host: Mapped[str] = mapped_column(String(255))
    gateway_port: Mapped[int] = mapped_column(Integer, default=5060)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    from_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    register_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    caller_id_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    transport: Mapped[str] = mapped_column(String(10), default="udp")  # udp|tcp|tls
    ping: Mapped[int | None] = mapped_column(Integer, nullable=True)  # segundos, qualify/keepalive
    codec_prefs: Mapped[str | None] = mapped_column(String(255), nullable=True)  # ej. "PCMU,PCMA,G729"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="trunk")


class Extension(Base):
    __tablename__ = "extensions"
    # LA restricción que define todo el modelo multiempresa: el número es
    # único por empresa, no en la plataforma. Casi todas van a tener su
    # 1000. Si esto quedara único global, la segunda empresa que lo
    # intente recibe un error de duplicado sin explicación posible para
    # el usuario, y si además el dialplan no separa contextos, sus
    # llamadas terminan en la extensión de la otra.
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="ux_extensions_tenant_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    number: Mapped[str] = mapped_column(String(20), index=True)
    password: Mapped[str] = mapped_column(TextoCifrado())
    caller_id_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voicemail: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Puede llamar afuera fuera del horario laboral de la empresa (guardias).
    # Solo cuenta si la empresa limita las salientes al horario (Ajustes).
    outbound_after_hours: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VoiceBot(Base):
    __tablename__ = "voicebots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="ux_voicebots_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    bot_type: Mapped[str] = mapped_column(String(20), default="ivr")  # "ivr" | "ai"
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {"menu": {"1": "1000"}}
    greeting_audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    flow_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # {"nodes": [...], "edges": [...]}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="voicebot")


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="ux_campaigns_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    trunk_id: Mapped[int | None] = mapped_column(ForeignKey("trunks.id"), nullable=True)
    voicebot_id: Mapped[int | None] = mapped_column(ForeignKey("voicebots.id"), nullable=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=5)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    # Topes diarios (services/tope_campanas.py). NULL = sin tope.
    max_calls_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_minutes_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Llamadas lanzadas en `calls_today_date` (las cuenta el marcador).
    calls_today: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    calls_today_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")  # idle|running|paused|done
    # Qué gestión resuelve el voizbot en las llamadas de esta campaña
    # (confirmar / reagendar / cancelar / agendar / cobranza… — ver
    # app/services/ai_intents.py). Sin esto, toda campaña era una campaña
    # de confirmación de citas aunque el bot fuera de otra cosa.
    ai_intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Mensaje de apertura personalizado, con {variables} que se rellenan por
    # número desde CampaignNumber.extra_data (ej. "Hola {cliente}, te
    # recuerdo tu cita del {fecha}"). Si está vacío, el bot abre con el
    # saludo genérico de la intención (ver ai_intents.py). El resto de la
    # conversación (confirmar/reagendar/cancelar con disponibilidad real)
    # sigue funcionando igual: esto solo reemplaza la primera frase.
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cuánto esperar antes de volver a marcar un número según cómo salió
    # el intento anterior (services/hopper.py): {"busy": 30, "noanswer": 120,
    # "failed": 15}, en minutos. Sin regla, se reintenta en la vuelta
    # siguiente (lo de antes). Cuántas veces sigue siendo `retries`.
    reglas_reciclaje: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Cómo se marca (docs/plan-contact-center.md): "voizbot" = lo de antes
    # (workers/dialer.py); "manual", "vista_previa" y "progresivo" = con
    # agentes humanos (services/agentes.py).
    metodo: Mapped[str] = mapped_column(String(20), default="voizbot", server_default="voizbot")
    # Guion para el agente, con {variables} del número y del contacto.
    guion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Grabar las llamadas de agentes: "todas" o "ninguna".
    grabacion: Mapped[str] = mapped_column(String(10), default="todas", server_default="todas")
    # Proporcional y predictivo (services/predictivo.py). nivel_marcacion:
    # llamadas por agente listo (fijo en proporcional, inicial en
    # predictivo); nivel_actual: el que va ajustando el predictivo.
    nivel_marcacion: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    nivel_max: Mapped[float] = mapped_column(Float, default=3.0, server_default="3.0")
    nivel_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Porcentaje de contestadas que se quedan sin agente (abandono) que no se
    # quiere superar, y cuántos segundos espera un cliente contestado antes
    # de darlo por abandonado.
    abandono_objetivo: Mapped[float] = mapped_column(Float, default=3.0, server_default="3.0")
    temporizador_abandono: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    # Lo que oye el cliente abandonado (quién llamaba y que volverán a llamar)
    # y el audio ya generado para FreeSWITCH.
    mensaje_abandono: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_abandono: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # CRM externo (fase 6): plantilla de URL con {variables} del lead que la
    # consola del agente abre firmada con este secreto (services/integraciones.py).
    crm_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    crm_secreto: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    trunk: Mapped["Trunk | None"] = relationship(back_populates="campaigns")
    voicebot: Mapped["VoiceBot | None"] = relationship(back_populates="campaigns")
    numbers: Mapped[list["CampaignNumber"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    calls: Mapped[list["CallLog"]] = relationship(back_populates="campaign")


class CampaignNumber(Base):
    __tablename__ = "campaign_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    phone: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|dialing|answered|busy|noanswer|failed|done
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Variables propias de este número para rellenar Campaign.message_template
    # (ej. {"cliente": "Camilo Barragán", "fecha": "21 de agosto"}), guardadas
    # como JSON en texto — igual convención que voicebots.flow_json.
    extra_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    # La cita EXACTA que este número sincronizó en la Agenda (ver
    # _sincronizar_agenda en app/api/campaigns.py) — se le pasa al voizbot
    # al marcar (nspbx_appointment_id) para que actúe sobre ESA cita
    # puntual y no adivine por teléfono cuál es, algo que falla de verdad
    # cuando el mismo número tiene más de una cita confirmada.
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    # Este número ES el lead del contact center (docs/plan-contact-center.md):
    # un contacto dentro de una lista de una campaña. Se enriqueció esta
    # tabla en vez de reemplazarla para que el voizbot, la agenda y la
    # cobranza sigan funcionando sin cambios.
    contacto_id: Mapped[int | None] = mapped_column(
        ForeignKey("contactos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lista_id: Mapped[int | None] = mapped_column(
        ForeignKey("listas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prioridad: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # No se marca antes de esta hora (reciclaje; ver services/hopper.py).
    proximo_intento_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_intento_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Dueño del lead: un callback «solo para mí» lo reserva para ese agente
    # (services/hopper.py no se lo da a otro). NULL = cualquiera.
    agente_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    disposicion_id: Mapped[int | None] = mapped_column(
        ForeignKey("disposiciones.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaign: Mapped["Campaign"] = relationship(back_populates="numbers")


class SystemSettings(Base):
    """Ajustes de UNA empresa.

    Deja de ser la fila única `id=1` que se leía en 16 lugares del código
    con `session.get(SystemSettings, 1)`. Ahora hay una fila por empresa y
    el `UNIQUE` de abajo es lo que lo garantiza: sin él, un alta a medias
    puede dejar dos filas para el mismo tenant y el sistema tomaría
    cualquiera de las dos según el orden del índice — un fallo
    intermitente y prácticamente imposible de reproducir.
    """

    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="ux_system_settings_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    app_name: Mapped[str] = mapped_column(String(100), default="NSPBX")
    fs_domain: Mapped[str] = mapped_column(String(255), default="nspbx.local")
    fs_esl_host: Mapped[str] = mapped_column(String(255), default="localhost")
    fs_esl_port: Mapped[int] = mapped_column(Integer, default=8021)
    fs_esl_password: Mapped[str] = mapped_column(TextoCifrado(), default="ClueCon")
    fs_http_base: Mapped[str] = mapped_column(String(255), default="http://localhost:8080")
    sip_ws_url: Mapped[str] = mapped_column(String(255), default="wss://localhost:7443")
    sip_server_ip: Mapped[str] = mapped_column(String(255), default="192.168.100.6")
    sip_server_port: Mapped[int] = mapped_column(Integer, default=5060)
    elevenlabs_api_key: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    agent_webhook_secret: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    # El "cerebro" del voizbot no está atado a un proveedor fijo: cualquiera
    # compatible con la API de chat completions de OpenAI (DeepSeek, OpenAI,
    # Groq, Together AI, un servidor propio) sirve con solo cambiar estos
    # tres campos desde Ajustes — el nombre es nada más para mostrarlo ahí
    # y en Consumo IA. Ver app/services/llm.py.
    ai_llm_provider_name: Mapped[str] = mapped_column(String(60), default="DeepSeek")
    ai_llm_base_url: Mapped[str] = mapped_column(String(255), default="https://api.deepseek.com/v1")
    ai_llm_model: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    ai_llm_api_key: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    record_all_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    # Voz del voizbot con IA. edge-tts es gratis (voces nativas de Colombia);
    # ElevenLabs suena más natural pero cuesta ~15x más por llamada — el TTS
    # es el ~95% del costo de una conversación con IA (medido: 936
    # caracteres por llamada típica).
    deepgram_api_key: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    # Voz y transcripción se eligen POR SEPARADO a propósito: la
    # combinación más barata es voz gratis (edge) con transcripción de
    # Deepgram, y atarlas a un solo campo la haría imposible.
    ai_stt_provider: Mapped[str] = mapped_column(String(20), default="elevenlabs")
    ai_voice_provider: Mapped[str] = mapped_column(String(20), default="elevenlabs")
    ai_voice_id: Mapped[str] = mapped_column(String(100), default="Xb7hH8MSUJpSbSDYk0k2")
    # Tarifas para ESTIMAR el costo del consumo medido. Se guardan acá y no
    # en el código porque cambian con el plan de cada proveedor; lo que se
    # mide (caracteres, tokens) es exacto, el dinero es una estimación.
    # En USD. El valor del TTS está calibrado con el consumo real de la
    # cuenta ($0.15 por 2.290 caracteres facturados = $0.0655 por millar),
    # no con una tarifa de lista: la estimación anterior de $0.30 inflaba
    # el costo 4,6 veces. Ajustables desde Ajustes si cambia el plan.
    rate_tts_per_1k_chars: Mapped[float] = mapped_column(Float, default=0.0655)
    # Transcripción (ElevenLabs Scribe). Se mide desde el principio pero
    # arranca sin tarifa: el panel del proveedor no la desglosa, así que
    # ponerle un número inventado sería peor que dejarla en cero y a la
    # vista. Con el plan a mano se llena desde Ajustes.
    rate_stt_per_minute: Mapped[float] = mapped_column(Float, default=0.0065)
    # Deepgram: $30/1M caracteres de voz y $0,29/hora de transcripción.
    rate_dg_tts_per_1k_chars: Mapped[float] = mapped_column(Float, default=0.030)
    rate_dg_stt_per_minute: Mapped[float] = mapped_column(Float, default=0.00483)
    # Tarifa MEZCLADA del modelo, también sacada del consumo real
    # (248.706 tokens por menos de $0,01). Es mucho más barata que la de
    # lista porque DeepSeek cobra con descuento los tokens que ya tenía en
    # caché, y en este voizbot el prompt del sistema —guion + calendario—
    # se repite idéntico en cada turno. Del panel no se puede separar
    # entrada de salida, y a esta escala da igual: el modelo es menos del
    # 1% de la factura frente a la voz.
    rate_llm_in_per_1m: Mapped[float] = mapped_column(Float, default=0.04)
    rate_llm_out_per_1m: Mapped[float] = mapped_column(Float, default=0.04)

    # Respaldo automático de la base y retención de grabaciones — ver
    # app/workers/maintenance.py. Antes no existía ninguno de los dos: la
    # base no tenía copia fuera del propio volumen, y las grabaciones se
    # acumulaban sin límite hasta llenar el disco (lo que tumba a
    # FreeSWITCH y a Postgres a la vez).
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Conector Issabel (ARI) --------------------------------------
    # Issabel como motor telefónico externo: NSPBX se conecta como una app
    # Stasis de Asterisk para recibir/originar llamadas y streamear el
    # audio por WebSocket (ver app/services/ari.py). Vacío = desactivado
    # (NSPBX sigue usando su propio FreeSWITCH).
    ari_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ari_user: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ari_password: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    ari_app: Mapped[str] = mapped_column(String(80), default="nspbx")
    backup_retention_days: Mapped[int] = mapped_column(Integer, default=14)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_backup_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_backup_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recordings_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    # Válvula de seguridad además de la retención por días: si algo hace
    # que se graben más llamadas de lo esperado, esto frena el crecimiento
    # del disco aunque las grabaciones individualmente sean "recientes".
    recordings_max_gb: Mapped[float] = mapped_column(Float, default=20.0)
    # Misma válvula que recordings_max_gb, pero para /backups: antes solo
    # tenía límite por días, así que una racha de respaldos manuales
    # ("Respaldar ahora" repetido) podía acumular más de la cuenta sin que
    # nada la frenara hasta la siguiente purga por antigüedad.
    backups_max_gb: Mapped[float] = mapped_column(Float, default=5.0)

    # Protección contra fraude telefónico: sin esto, una extensión
    # comprometida (o un bug) puede dejar una llamada saliente corriendo
    # horas hacia un número caro sin que nadie se entere hasta la factura.
    # Se aplica a TODA llamada (entrante, saliente, interna) — ver
    # _append_recording_hook en config_generator.py, que ya corre en cada
    # una. 0 = sin tope (para quien de verdad necesite llamadas largas).
    max_call_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    # Tope de canales simultáneos en TODA la central, no solo por
    # campaña — antes cada campaña respetaba su propio max_concurrency,
    # pero nada impedía que dos campañas a la vez (o una campaña más
    # tráfico entrante) superaran lo que la troncal real soporta, y el
    # proveedor empieza a rechazar TODO, entrantes incluidas.
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=20)
    # Llamadas internacionales (prefijos 00/011/+). Apagado por defecto: es
    # el destino habitual del fraude telefónico. Activarlo no alcanza: hay
    # que elegir además los países (ver services/salientes.py).
    allow_international: Mapped[bool] = mapped_column(Boolean, default=False)
    # Códigos de país permitidos con internacional activado, separados por
    # coma ("57,1,34"). Vacío = ninguno.
    international_countries: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Interruptor de la EMPRESA: su administrador pausa las salientes (y lo
    # deshace) sin depender de la plataforma. Ver services/salientes.py.
    outbound_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Franja en la que pueden marcar las campañas (services/horario_marcacion.py).
    # Por defecto la de la Ley 2300 de 2023; las de cobranza nunca salen de ella.
    campaign_hours_weekdays: Mapped[str] = mapped_column(String(11), default="07:00-19:00", server_default="07:00-19:00")
    campaign_hours_saturday: Mapped[str] = mapped_column(String(11), default="08:00-15:00", server_default="08:00-15:00")
    campaign_sundays_holidays: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Salientes de los teléfonos solo en horario laboral (opcional). Fuera de
    # él, solo las extensiones con `outbound_after_hours` (ver salientes.py).
    outbound_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    outbound_hours_weekdays: Mapped[str] = mapped_column(String(11), default="07:00-19:00", server_default="07:00-19:00")
    outbound_hours_saturday: Mapped[str] = mapped_column(String(11), default="08:00-13:00", server_default="08:00-13:00")
    outbound_hours_sundays_holidays: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # Widget de "llamar a un agente" embebible en sitios web públicos (ver
    # app/api/webcall.py y app/services/webcall.py). Un visitante anónimo
    # obtiene una credencial SIP temporal y entra a UNA cola. Apagado por
    # defecto: es una superficie expuesta a internet. Por ahora está
    # cableado a tenant_id=1 (ver docstring de app/api/webcall.py); el
    # campo ya vive por empresa para no tener que migrar nada cuando se
    # generalice.
    webcall_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webcall_queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("queues.id", ondelete="SET NULL"), nullable=True
    )
    webcall_max_concurrent: Mapped[int] = mapped_column(Integer, default=5)
    webcall_turnstile_site_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webcall_turnstile_secret: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    # JSON semanal {"mon": ["08:00","18:00"], ...}. Día ausente = cerrado;
    # NULL/vacío = 24/7. Se evalúa en hora local del negocio (core/clock.py).
    webcall_schedule: Mapped[str | None] = mapped_column(Text, nullable=True)
    webcall_greeting: Mapped[str | None] = mapped_column(
        String(255), default="Presione para hablar con un agente"
    )
    webcall_button_text: Mapped[str | None] = mapped_column(
        String(120), default="Hablar con un agente"
    )
    webcall_offline_text: Mapped[str | None] = mapped_column(
        String(255), default="Estamos fuera de horario de atención"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CallLog(Base):
    __tablename__ = "call_logs"
    # Reportes por campaña y rango (services/reportes.py). El de empresa y
    # fecha lo crea main._COLUMN_PATCHES desde antes.
    __table_args__ = (Index("ix_call_logs_campana_inicio", "campaign_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    extension_id: Mapped[int | None] = mapped_column(ForeignKey("extensions.id"), nullable=True)
    # El uuid sigue siendo único GLOBAL, no por empresa: lo genera
    # FreeSWITCH y ya es único en toda la instalación. Además el CDR
    # llega por webhook sin contexto de empresa y se busca solo por uuid,
    # así que hacerlo único por tenant no aportaría nada y abriría la
    # puerta a dos llamadas distintas con el mismo identificador.
    uuid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    caller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    callee_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    direction: Mapped[str] = mapped_column(String(10))  # inbound|outbound
    status: Mapped[str] = mapped_column(String(20))  # answered|no_answer|busy|failed|cancelled
    duration: Mapped[int] = mapped_column(Integer, default=0)  # total, incluye timbrado
    billsec: Mapped[int] = mapped_column(Integer, default=0)  # solo tiempo hablado
    hangup_cause: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Pata que salió por una troncal hacia el proveedor (lo que se factura).
    # `direction` no alcanza: FreeSWITCH marca "outbound" también las
    # llamadas entre extensiones. Es lo que suma el cupo diario de minutos.
    # NULL en filas anteriores a la columna.
    via_trunk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recording_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Resumen de lo que pasó, generado al pedirlo y guardado acá para no
    # volver a pagar transcripción cada vez que alguien lo abre. Va en
    # CallLog y no en el consumo de IA porque el resumen se arma desde la
    # grabación: aplica también a llamadas que nunca tocaron el voizbot.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Tiempos separados, en milisegundos (ver services/tiempos_llamada.py).
    # `duration` mezcla timbre y conversación; para medir troncales, el
    # marcador y a los agentes cada tramo va en su columna. NULL = no aplica
    # o la llamada es anterior a estas columnas.
    progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # empezó a timbrar
    setup_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # inicio → timbre (red/troncal)
    ring_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # timbre → contesta (o → cuelga)
    espera_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # en espera (hold)
    colgo: Mapped[str | None] = mapped_column(String(10), nullable=True)  # llamante|llamado
    # Llamadas de agentes (services/agentes.py): quién atendió, qué lead y
    # cómo la dispuso.
    agente_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disposicion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # El cliente contestó y no hubo agente a tiempo (predictivo).
    abandonada: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    campaign: Mapped["Campaign | None"] = relationship(back_populates="calls")


class AiCallUsage(Base):
    """Consumo de una conversación del voizbot con IA.

    Se guardan UNIDADES MEDIDAS (caracteres, tokens, segundos), no dinero:
    los precios de los proveedores cambian y se configuran aparte, así que
    el costo se calcula al consultar. Sin esta tabla no había forma de
    saber cuánto cuesta una llamada ni por qué se dispara el gasto."""

    __tablename__ = "ai_call_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    # Único global por el mismo motivo que CallLog.uuid: lo genera
    # FreeSWITCH y el consumo se registra desde el voizbot, que conoce la
    # llamada pero no necesariamente la empresa.
    call_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    turns: Mapped[int] = mapped_column(Integer, default=0)
    # Texto a voz: lo que más pesa en la factura de una llamada con IA.
    tts_chars: Mapped[int] = mapped_column(Integer, default=0)
    tts_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stt_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Voz a texto: segundos de audio enviados al STT en streaming.
    stt_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Modelo de lenguaje: se separan entrada y salida porque cuestan distinto.
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # completed | no_speech | max_turns | hangup | error
    outcome: Mapped[str] = mapped_column(String(20), default="completed")
    # Si la conversación terminó con una gestión hecha sobre la agenda:
    # es el numerador de la tasa de contención.
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Qué hizo la llamada sobre la agenda, no solo SI hizo algo — antes
    # "resolved" era un booleano ciego: no quedaba registro de si
    # confirmó, canceló o reagendó, ni para cuándo. `appointment_id`
    # apunta a la cita en el momento de la acción; se guarda ADEMÁS
    # `action_appointment_date`/`action_patient_name` como fotografía de
    # ese instante, porque la cita puede reagendarse de nuevo después y
    # perder el dato que importaba en esta llamada.
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)  # confirmada|cancelada|reagendada|agendada
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    action_appointment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action_patient_name: Mapped[str | None] = mapped_column(String(150), nullable=True)

    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Debt(Base):
    """Deuda de cobranza — una por teléfono de deudor.

    La crea la campaña de cobranza al cargar los números (ver
    `_sincronizar_deuda` en app/api/campaigns.py) o se da de alta a mano
    desde la página de Cobranza. El voizbot la consulta por teléfono
    (app/services/ai_agent.py) para saber de cuánto es la deuda y con
    quién habla, sin depender de variables que viajen en la llamada."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    phone: Mapped[str] = mapped_column(String(30), index=True)
    debtor_name: Mapped[str] = mapped_column(String(150))
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open | promised | paid | overdue
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    promises: Mapped[list["PaymentPromise"]] = relationship(back_populates="debt")


class PaymentPromise(Base):
    """Promesa de pago registrada por el voizbot de cobranza.

    Es el resultado concreto de una llamada de cobranza: la persona se
    comprometió a pagar X el día Y, en total, como abono o en un plan de
    cuotas. Sin esta tabla, "el bot llamó" no decía nada de si la cobranza
    avanzó o no."""

    __tablename__ = "payment_promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    debt_id: Mapped[int | None] = mapped_column(
        ForeignKey("debts.id", ondelete="SET NULL"), nullable=True
    )
    phone: Mapped[str] = mapped_column(String(30), index=True)
    debtor_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Monto que la persona se compromete a pagar.
    amount_promised: Mapped[float] = mapped_column(Float, default=0)
    # Fecha para la que se compromete el pago.
    promise_date: Mapped[datetime] = mapped_column(DateTime)
    # completo | abono | cuotas
    plan: Mapped[str] = mapped_column(String(20), default="completo")
    installments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | completed | missed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Llamada del voizbot que la registró (para cruzar con Consumo IA).
    call_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    debt: Mapped["Debt | None"] = relationship(back_populates="promises")


class License(Base):
    """Licencia de UNA empresa: plan, estado, vencimiento y límites.

    Es el modelo de monetización por empresa (ver app/services/licensing.py
    para los presets de cada plan). Los límites se enforcean al crear
    recursos y al originar llamadas; cuando la licencia está vencida o
    suspendida, la empresa no puede operar (solo ver su estado).

    El estado se guarda explícito (`trial | active | suspended`) pero el
    vencimiento se evalúa en caliente: una licencia `trial` o `active`
    cuya fecha ya pasó se comporta como vencida sin migrar nada."""

    __tablename__ = "licenses"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="ux_licenses_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    # free | pro | enterprise | custom
    plan: Mapped[str] = mapped_column(String(30), default="free")
    # trial | active | suspended
    status: Mapped[str] = mapped_column(String(20), default="trial")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Límites (None = sin límite). Se toman del plan si no se sobreescriben.
    max_extensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_trunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrent_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_campaigns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Minutos salientes (por troncal) por día. Al llegar, se cortan las
    # salientes hasta el día siguiente: un tope que solo avisa no frena un
    # fraude de madrugada.
    max_outbound_minutes_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Llamadas salientes nuevas por segundo (ver services/salientes.py). NULL
    # = la del plan.
    max_outbound_cps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Queue(Base):
    """Cola de llamadas entrantes (call center), estilo Issabel/FreePBX,
    sobre mod_callcenter de FreeSWITCH."""

    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="ux_queues_tenant_name"),
        UniqueConstraint("tenant_id", "extension", name="ux_queues_tenant_extension"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    extension: Mapped[str] = mapped_column(String(30))  # número que marcan para entrar a la cola
    strategy: Mapped[str] = mapped_column(String(40), default="ring-all")
    moh_sound: Mapped[str] = mapped_column(String(255), default="$${hold_music}")
    agents: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: ["1000", "1001"]
    max_wait_time: Mapped[int] = mapped_column(Integer, default=0)  # 0 = sin límite
    max_wait_time_with_no_agent: Mapped[int] = mapped_column(Integer, default=0)
    agent_ring_timeout: Mapped[int] = mapped_column(Integer, default=20)  # timbrado por agente antes de saltar
    max_no_answer: Mapped[int] = mapped_column(Integer, default=3)  # inactivar agente tras N no-contesta
    wrap_up_time: Mapped[int] = mapped_column(Integer, default=10)  # pausa del agente tras colgar
    record: Mapped[bool] = mapped_column(Boolean, default=False)
    failover_extension: Mapped[str | None] = mapped_column(String(30), nullable=True)
    announce_position: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InboundRoute(Base):
    """Ruta de entrada por DID: a qué número le llega una llamada externa y
    a dónde se enruta (extensión, cola o voizbot) — estilo Issabel."""

    __tablename__ = "inbound_routes"
    # El DID es único en TODA la plataforma, no por empresa — la única
    # tabla donde la restricción cruza tenants, y a propósito.
    #
    # Una llamada entrante llega al contexto `public` sin ninguna pista
    # de a qué empresa pertenece: lo único que trae es el número marcado.
    # Ese número es la clave que decide a qué contexto se transfiere. Si
    # dos empresas pudieran declarar el mismo DID, el ruteo dependería
    # del orden de las filas y las llamadas de un cliente entrarían a la
    # central de otro — sin error, atendidas por gente equivocada.
    #
    # Vale también para el comodín "any": solo una empresa puede quedarse
    # con lo que no coincida con nada.
    __table_args__ = (
        UniqueConstraint("did_pattern", name="ux_inbound_routes_did"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    did_pattern: Mapped[str] = mapped_column(String(100))  # dígitos exactos, o "any" para comodín
    destination_type: Mapped[str] = mapped_column(String(20))  # extension|queue|voicebot|hangup
    destination_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Horario de atención (JSON {"mon": ["08:00", "18:00"], ...}, mismo
    # formato que el widget web; ver services/webcall.parse_schedule). Vacío
    # = siempre. Fuera de él la llamada va a fuera_horario_* (vacío = colgar).
    horario: Mapped[str | None] = mapped_column(Text, nullable=True)
    fuera_horario_tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fuera_horario_valor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RolePermission(Base):
    """Diferencia respecto de lo que el rol trae de fábrica.

    La matriz de `core/permissions.py` sigue siendo el valor POR DEFECTO;
    acá solo se guarda lo que una empresa cambió. Se hizo así y no
    copiando la matriz entera a la base por dos motivos: una instalación
    nueva no necesita ninguna fila para funcionar, y cuando se agregue un
    permiso al producto lo heredan todas las empresas sin migración.

    `permitido` es explícito —no basta con "existe la fila"— porque hay
    que poder tanto AGREGAR un permiso que el rol no trae como QUITAR uno
    que sí trae, y ambas cosas son diferencias respecto del valor de
    fábrica.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", "permission", name="ux_role_permissions"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    role: Mapped[str] = mapped_column(String(20))
    permission: Mapped[str] = mapped_column(String(50))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutboundRoute(Base):
    """Regla de salida: qué troncal usa cada destino marcado.

    Antes había UNA sola ruta fija que mandaba todo por la cadena de
    troncales habilitadas (ver config_generator._append_outbound_route).
    Alcanzaba con una troncal, pero no deja hacer lo básico de cualquier
    central: celulares por un proveedor y fijos por otro, normalizar el
    marcado, o abrir internacional solo en una ruta.

    El patrón se escribe en la notación de FreePBX/Issabel y NO en regex,
    porque es la que conoce quien instala centrales y porque un regex mal
    puesto acá no da un error visible: abre un destino caro y se paga en
    la factura. `config_generator` lo traduce a la expresión que entiende
    FreeSWITCH.

        X  un dígito 0-9        N  un dígito 2-9
        Z  un dígito 1-9        .  uno o más caracteres
        [1-5]  un dígito del rango

    El orden importa: gana la PRIMERA regla que coincide, de menor a
    mayor `priority`. Una regla con patrón "." al final actúa de comodín.
    """

    __tablename__ = "outbound_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100))
    pattern: Mapped[str] = mapped_column(String(100))
    # Dígitos que se quitan por la izquierda antes de marcar, y texto que
    # se antepone después. En ese orden: con strip=1 y prepend="57", el
    # 03001234567 sale como 573001234567.
    strip_digits: Mapped[int] = mapped_column(Integer, default=0)
    prepend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Troncales en orden, separadas por coma (misma convención que
    # Tenant.modules). FreeSWITCH prueba la siguiente si la anterior
    # rechaza o no contesta. Vacío = todas las habilitadas, como antes.
    trunk_ids: Mapped[str] = mapped_column(String(120), default="")
    # Puerta antifraude POR RUTA. El fraude telefónico vive en destinos
    # internacionales y de tarificación especial, así que se abre solo
    # donde hace falta en vez de para toda la empresa.
    allow_international: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def trunk_id_list(self) -> list[int]:
        return [int(t) for t in (self.trunk_ids or "").split(",") if t.strip().isdigit()]


class Appointment(Base):
    """Cita agendada — pensada para que un agente de IA (ej. ElevenLabs
    Conversational AI) la consulte/gestione vía los endpoints de
    /api/appointments/agent/*, además de administrarse a mano en la app."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    patient_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(30))
    appointment_date: Mapped[datetime] = mapped_column(DateTime)  # fecha+hora de inicio
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed|cancelled|completed
    # Cuándo el PACIENTE confirmó que va a asistir. Distinto de status:
    # una cita nace "confirmed" porque está agendada, pero eso no dice
    # nada de si la persona la ratificó. Antes marcar 1 solo reproducía un
    # audio y no dejaba rastro de quién confirmó ni cuándo.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    """Persona que entra al panel.

    `extension_id` ata al usuario con una extensión SIP. Es obligatorio
    para los asesores —sin extensión no pueden atender ni ver "sus"
    llamadas— y opcional para el resto: un supervisor puede tener línea
    para escuchar o apoyar, o no tenerla.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable, a diferencia del resto de las tablas: NULL identifica a un
    # usuario DE LA PLATAFORMA, el que da de alta empresas y puede entrar
    # a cualquiera. Si se lo obligara a pertenecer a un tenant, borrar esa
    # empresa dejaría a la plataforma sin administrador.
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Único GLOBAL y no por empresa, por una razón concreta: al iniciar
    # sesión todavía no se sabe a qué empresa pertenece quien escribe el
    # usuario — precisamente esa fila es la que lo dice. Con usuarios
    # repetidos entre empresas habría que pedir además la empresa en el
    # login. Es una decisión de producto que conviene tomar aparte; hasta
    # entonces, un usuario pertenece a una sola.
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="asesor")
    extension_id: Mapped[int | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Para saber quién dejó de usar el sistema antes de borrarle la cuenta.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Todo JWT emitido antes de este instante ya no sirve (cambio de contraseña,
    # cuenta desactivada, refresh token reutilizado). Ver services/sesiones.py.
    sesiones_desde: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Verificación en dos pasos (ver core/mfa.py). El secreto se guarda al
    # empezar la activación y `mfa_enabled` pasa a true al confirmar con un
    # código: hasta entonces no se exige.
    mfa_secret: Mapped[str | None] = mapped_column(TextoCifrado(), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Último paso TOTP aceptado: un código ya usado no vuelve a servir.
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Hashes de los códigos de recuperación que quedan sin usar.
    mfa_recovery: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    extension: Mapped["Extension | None"] = relationship(lazy="joined")


class RefreshToken(Base):
    """Sesión larga de la app móvil.

    Vive fuera del JWT (que solo dura 8h, ver core/security.py) porque un
    JWT no se puede revocar sin esta tabla: sin ella, cerrar sesión desde
    la app o desactivar un usuario no tendría forma de invalidar un
    refresh que ya está en el teléfono. Se guarda el HASH, nunca el token
    en claro, mismo criterio que `password_hash`.

    Sin `tenant_id`, igual que `users`: se consulta con la sesión del
    dueño porque hace falta ANTES de saber a qué empresa pertenece la
    sesión que se está renovando (la fila de `users` es la que lo dice).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeviceToken(Base):
    """Dispositivo móvil de un usuario, para poder despertarlo con un push
    cuando le entra una llamada a su extensión (ver services/push.py y el
    hook `nspbx_mobile_push` del dialplan en services/config_generator.py).

    Un solo `token` por fila, no uno de VoIP y otro "normal" separados:
    `expo-callkit-telecom` (la librería que usa la app, ver mobile/) expone
    un único token de llamada por plataforma —el de PushKit en iOS
    (`APNS_VOIP`), el de FCM en Android (`FCM`)— y es el único que este
    sistema necesita, porque el único push que se manda es "te está
    entrando una llamada".

    Una fila por usuario y plataforma: alguien puede tener un iPhone y un
    Android a la vez, pero no dos iPhones registrados —el último que
    inicia sesión reemplaza el token del anterior, igual que hacen la
    mayoría de apps de mensajería.
    """

    __tablename__ = "device_tokens"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "platform", name="ux_device_tokens_tenant_user_platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    extension_id: Mapped[int | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(20))  # ios | android
    # "APNS_VOIP" (iOS/PushKit) o "FCM" (Android) — tal cual lo reporta
    # `useVoIPPushToken()` del lado de la app.
    token_type: Mapped[str] = mapped_column(String(20))
    token: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PlatformState(Base):
    """Estado de toda la plataforma (una sola fila, id=1).

    Sin `tenant_id` a propósito: no es de ninguna empresa. Solo lo cambia
    el rol plataforma (ver app/api/plataforma.py)."""

    __tablename__ = "platform_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Interruptor global: corta TODAS las salientes de TODAS las empresas.
    outbound_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Códigos internacionales (país o prefijo, sin el +) bloqueados para
    # todas las empresas, además de los fijos de salientes.CODIGOS_BLOQUEADOS.
    # "53,7,2346": se guarda normalizado.
    blocked_prefixes: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SecurityAlert(Base):
    """Algo raro en el tráfico de una empresa (ver services/alertas.py).

    Avisa, no corta: el corte automático lo da el cupo diario de minutos.
    Una campaña nueva también es un pico, y cortarla por una sospecha
    pararía una operación legítima."""

    __tablename__ = "security_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    # pico | madrugada | destino_nuevo | cupo
    kind: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    """Quién hizo qué, cuándo, desde dónde y con qué resultado (ver
    core/auditoria.py). Solo se agrega: la aplicación no puede modificar ni
    borrar filas.

    `tenant_id` admite NULL, como `users`: las acciones de la plataforma y
    los intentos de login de usuarios inexistentes no son de ninguna
    empresa. Con RLS, una empresa ve solo las suyas.

    Sin clave foránea a `tenants` a propósito: con ON DELETE SET NULL,
    borrar una empresa intentaba modificar sus registros, el disparador de
    solo agregar lo rechazaba y la empresa no se podía borrar. Además el
    registro tiene que seguir diciendo de qué empresa era después de que
    se borre; lo elimina la retención (AUDITORIA_RETENCION_DIAS)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "usuario (rol)" al momento de la acción: si el usuario se borra o
    # cambia de rol, el registro sigue diciendo quién fue.
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # "PUT /api/trunks/{trunk_id}"
    action: Mapped[str] = mapped_column(String(120), index=True)
    # "trunk_id=7"
    resource: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Campos enviados, con los secretos ocultos.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ok | denegado | rechazado | error
    result: Mapped[str] = mapped_column(String(12))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class VoiceBotVersion(Base):
    """Foto de un voizbot cada vez que se guarda (flujo, saludo, config).

    Un cambio en el flujo se aplica a las llamadas siguientes al instante:
    si rompe el bot, la forma de volver atrás es restaurar una versión
    anterior, no reconstruir el flujo de memoria."""

    __tablename__ = "voicebot_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    voicebot_id: Mapped[int] = mapped_column(ForeignKey("voicebots.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    bot_type: Mapped[str] = mapped_column(String(20))
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    flow_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quién la guardó ("usuario (rol)") y por qué ("flujo", "ajustes",
    # "restaurada v3").
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    """Clave de la API pública (/api/v1) de una empresa, con permisos
    limitados (ver core/claves_api.py).

    Se guarda solo el SHA-256 de la clave: quien lea la base no puede usarla.
    `prefix` es la parte visible que identifica la clave sin revelarla (y la
    que se busca al autenticar). Revocar no borra la fila: la auditoría
    sigue pudiendo decir qué clave hizo qué."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    # Separados por coma: "llamadas:leer,citas:leer".
    scopes: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def scope_list(self) -> list[str]:
        return [s for s in (self.scopes or "").split(",") if s]


# --- CRM (docs/plan-contact-center.md, fase 2) ---------------------------


class Contacto(Base):
    """Cliente de una empresa: uno solo aunque esté en varias campañas.

    `telefono_clave` es el teléfono principal reducido a sus últimos 10
    dígitos (services/crm.py:clave_telefono): "+57 300-123 4567",
    "573001234567" y "3001234567" son el mismo cliente. Por esa clave se
    deduplica al importar y se cruza el historial de llamadas."""

    __tablename__ = "contactos"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    nombre: Mapped[str] = mapped_column(String(150), default="")
    documento: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    telefono: Mapped[str] = mapped_column(String(40))
    telefono_clave: Mapped[str] = mapped_column(String(20), index=True)
    # Teléfonos adicionales, en orden: [{"numero": "...", "tipo": "movil"}].
    telefonos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Campos propios de la empresa, validados contra CampoContacto.
    campos: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fuente: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CampoContacto(Base):
    """Definición de un campo propio de la empresa (plan, saldo, sede…)."""

    __tablename__ = "campos_contacto"
    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="ux_campos_contacto_tenant_clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    clave: Mapped[str] = mapped_column(String(40))
    nombre: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(15), default="texto")  # texto|numero|fecha|opciones|si_no
    opciones: Mapped[list | None] = mapped_column(JSON, nullable=True)
    obligatorio: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    visible_agente: Mapped[bool] = mapped_column(Boolean, default=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Lista(Base):
    """Una carga de números en una campaña. Se puede pausar o priorizar
    sin tocar los números (services/hopper.py)."""

    __tablename__ = "listas"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    prioridad: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    origen: Mapped[str] = mapped_column(String(20), default="manual")  # manual|csv|api
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Nota(Base):
    """Nota sobre un contacto. No se editan: son el registro de lo que se
    habló, como una bitácora."""

    __tablename__ = "notas"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    contacto_id: Mapped[int] = mapped_column(ForeignKey("contactos.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    autor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    texto: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NoLlamar(Base):
    """Lista de no llamar de la empresa. El marcador nunca marca un número
    que esté acá (vigente), en ninguna campaña."""

    __tablename__ = "no_llamar"
    __table_args__ = (UniqueConstraint("tenant_id", "telefono_clave", name="ux_no_llamar_tenant_clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    telefono: Mapped[str] = mapped_column(String(40))
    telefono_clave: Mapped[str] = mapped_column(String(20))
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hasta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # NULL = para siempre
    creado_por: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# --- Agentes (docs/plan-contact-center.md, fase 3) ---------------------------


class CodigoPausa(Base):
    """Motivo de pausa del agente (almuerzo, capacitación…)."""

    __tablename__ = "codigos_pausa"
    __table_args__ = (UniqueConstraint("tenant_id", "codigo", name="ux_codigos_pausa_tenant_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    codigo: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(60))
    pagada: Mapped[bool] = mapped_column(Boolean, default=True)
    # Pasado este tiempo el supervisor lo ve en rojo (fase 5). NULL = sin tope.
    max_minutos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Disposicion(Base):
    """Resultado de una llamada que elige el agente al terminarla.

    La categoría decide qué pasa con el lead (services/agentes.py:disponer):
    `venta`, `contacto` y `promesa` lo cierran; `no_contacto` lo recicla;
    `callback` lo agenda; `no_llamar` lo pasa a la lista de no llamar."""

    __tablename__ = "disposiciones"
    __table_args__ = (UniqueConstraint("tenant_id", "codigo", name="ux_disposiciones_tenant_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    codigo: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(60))
    categoria: Mapped[str] = mapped_column(String(15))  # venta|contacto|no_contacto|callback|promesa|no_llamar
    # Cuenta como conversación con una persona (tasa de contacto).
    contacto_humano: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(10), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CampanaAgente(Base):
    """Qué agentes trabajan en qué campaña."""

    __tablename__ = "campana_agentes"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="ux_campana_agentes"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class SesionAgente(Base):
    """Una jornada del agente: desde que entra hasta que sale."""

    __tablename__ = "sesiones_agente"
    __table_args__ = (Index("ix_sesiones_agente_tenant_inicio", "tenant_id", "inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campanas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    motivo_fin: Mapped[str | None] = mapped_column(String(20), nullable=True)  # normal|forzada|reinicio


class EstadoAgente(Base):
    """Bitácora de estados: una fila por tramo. Todos los tiempos del agente
    (listo, pausa por código, en llamada, disposición) salen de acá."""

    __tablename__ = "estados_agente"
    __table_args__ = (Index("ix_estados_agente_tenant_inicio", "tenant_id", "inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sesion_id: Mapped[int] = mapped_column(ForeignKey("sesiones_agente.id", ondelete="CASCADE"), index=True)
    estado: Mapped[str] = mapped_column(String(15))
    codigo_pausa_id: Mapped[int | None] = mapped_column(
        ForeignKey("codigos_pausa.id", ondelete="SET NULL"), nullable=True
    )
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    disposicion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgenteVivo(Base):
    """Estado actual de un agente conectado (una fila por agente). La lee
    la consola del agente y, en la fase 5, el supervisor."""

    __tablename__ = "agentes_vivo"
    __table_args__ = (UniqueConstraint("user_id", name="ux_agentes_vivo_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sesion_id: Mapped[int] = mapped_column(ForeignKey("sesiones_agente.id", ondelete="CASCADE"))
    estado: Mapped[str] = mapped_column(String(15))
    desde: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    codigo_pausa_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campanas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Pata de audio del agente en su conferencia ("sesión clavada").
    audio_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio: Mapped[bool] = mapped_column(Boolean, default=False)
    # Lo que el softphone del agente exige para contestar solo esa llamada.
    token_audio: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Llamada y lead en curso.
    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contestada_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Pausa pedida en medio de una llamada: se aplica al disponer.
    pausa_pendiente_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Antes de marcar a mano desde la pausa: a qué vuelve después.
    volver_a_pausa_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Callback(Base):
    """Volver a llamar a un lead en una fecha, para un agente o para
    cualquiera de la campaña."""

    __tablename__ = "callbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    lead_id: Mapped[int] = mapped_column(ForeignKey("campaign_numbers.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    contacto_id: Mapped[int | None] = mapped_column(ForeignKey("contactos.id", ondelete="SET NULL"), nullable=True)
    agente_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cuando: Mapped[datetime] = mapped_column(DateTime, index=True)
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")  # pendiente|hecho|cancelado
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MetricaCampana(Base):
    """Contadores del día de una campaña con marcación automática a agentes.
    El abandono del día (abandonadas / contestadas) es la cifra de
    cumplimiento: se guarda en la base para que sobreviva a un reinicio."""

    __tablename__ = "metricas_campana"
    __table_args__ = (UniqueConstraint("campaign_id", "fecha", name="ux_metricas_campana_dia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    fecha: Mapped[date] = mapped_column(Date)
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    contestadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    asignadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    abandonadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class TokenWallboard(Base):
    """Acceso de solo lectura al wallboard para una pantalla sin sesión de
    usuario (la TV de la sala de operaciones). Se guarda solo el hash: el
    token se muestra una vez al crearlo. Vence y se puede revocar."""

    __tablename__ = "tokens_wallboard"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    nombre: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vence: Mapped[datetime] = mapped_column(DateTime)
    revocado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Webhook(Base):
    """Aviso a un sistema de la empresa (su CRM) cuando pasa algo: se le
    hace POST con el evento firmado con HMAC (services/integraciones.py)."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    nombre: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(500))
    secreto: Mapped[str] = mapped_column(TextoCifrado())
    eventos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    fallos_seguidos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ultimo_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EntregaWebhook(Base):
    """Bitácora y cola de envíos (se escribe en la misma transacción que el
    cambio que la origina: si el cambio no se guarda, no se avisa)."""

    __tablename__ = "entregas_webhook"
    __table_args__ = (Index("ix_entregas_webhook_cola", "estado", "proximo_intento_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    webhook_id: Mapped[int] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    evento: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")  # pendiente|ok|fallida
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    proximo_intento_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    entregado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReporteProgramado(Base):
    """Un reporte que sale solo por correo (CSV adjunto) cada día, semana o mes."""

    __tablename__ = "reportes_programados"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    nombre: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(20))  # agentes|campanas|disposiciones|cumplimiento
    frecuencia: Mapped[str] = mapped_column(String(10))  # diaria|semanal|mensual
    hora: Mapped[int] = mapped_column(Integer, default=7, server_default="7")  # hora local de envío
    destinatarios: Mapped[str] = mapped_column(Text)
    filtros: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ultimo_envio_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_intento_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_periodo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonitoreoVivo(Base):
    """Un supervisor escuchando, susurrando o interviniendo a un agente
    (services/supervision.py). En la base y no en memoria: la petición la
    puede atender cualquier réplica y los eventos los procesa la líder."""

    __tablename__ = "monitoreos"
    __table_args__ = (
        UniqueConstraint("agente_id", name="ux_monitoreos_agente"),
        UniqueConstraint("supervisor_id", name="ux_monitoreos_supervisor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    uuid: Mapped[str] = mapped_column(String(64), unique=True)
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agente_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    modo: Mapped[str] = mapped_column(String(12))
    token: Mapped[str] = mapped_column(String(64))
    contestado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NodoFreeswitch(Base):
    """Un FreeSWITCH adicional al principal (opción A de docs/escala.md: las
    empresas se reparten entre servidores). Es de la PLATAFORMA, no de una
    empresa: no lleva tenant_id y solo lo administra el rol plataforma."""

    __tablename__ = "nodos_freeswitch"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40), unique=True)
    esl_host: Mapped[str] = mapped_column(String(255))
    esl_port: Mapped[int] = mapped_column(Integer, default=8021, server_default="8021")
    esl_password: Mapped[str] = mapped_column(TextoCifrado())
    # Dónde se registran los teléfonos de sus empresas (DNS o IP pública).
    sip_host: Mapped[str] = mapped_column(String(255))
    # Agentes simultáneos que se le planifican (para repartir empresas).
    capacidad_agentes: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MensajeBuzon(Base):
    """Un mensaje de buzón de voz: alguien llamó a una extensión, nadie
    contestó (o estaba en «no molestar») y dejó un mensaje grabado.

    Lo crea el CDR de esa llamada (api/calls.py:receive_cdr) cuando trae
    `nspbx_buzon_ext`, que fija el dialplan al mandar la llamada al buzón
    (services/config_generator.py:_acciones_buzon). El audio vive en la
    carpeta de grabaciones de la empresa (t<id>/buzon/<ext>/...)."""

    __tablename__ = "buzon_mensajes"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    extension: Mapped[str] = mapped_column(String(20), index=True)
    call_uuid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    caller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ruta: Mapped[str] = mapped_column(String(500))
    duracion: Mapped[int] = mapped_column(Integer, default=0)  # segundos de mensaje
    escuchado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
