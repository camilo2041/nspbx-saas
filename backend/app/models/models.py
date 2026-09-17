from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    password: Mapped[str] = mapped_column(String(255))
    caller_id_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voicemail: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
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
    fs_esl_password: Mapped[str] = mapped_column(String(255), default="ClueCon")
    fs_http_base: Mapped[str] = mapped_column(String(255), default="http://localhost:8080")
    sip_ws_url: Mapped[str] = mapped_column(String(255), default="wss://localhost:7443")
    sip_server_ip: Mapped[str] = mapped_column(String(255), default="192.168.100.6")
    sip_server_port: Mapped[int] = mapped_column(Integer, default=5060)
    elevenlabs_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # El "cerebro" del voizbot no está atado a un proveedor fijo: cualquiera
    # compatible con la API de chat completions de OpenAI (DeepSeek, OpenAI,
    # Groq, Together AI, un servidor propio) sirve con solo cambiar estos
    # tres campos desde Ajustes — el nombre es nada más para mostrarlo ahí
    # y en Consumo IA. Ver app/services/llm.py.
    ai_llm_provider_name: Mapped[str] = mapped_column(String(60), default="DeepSeek")
    ai_llm_base_url: Mapped[str] = mapped_column(String(255), default="https://api.deepseek.com/v1")
    ai_llm_model: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    ai_llm_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    record_all_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    # Voz del voizbot con IA. edge-tts es gratis (voces nativas de Colombia);
    # ElevenLabs suena más natural pero cuesta ~15x más por llamada — el TTS
    # es el ~95% del costo de una conversación con IA (medido: 936
    # caracteres por llamada típica).
    deepgram_api_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
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
    ari_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    webcall_turnstile_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    recording_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Resumen de lo que pasó, generado al pedirlo y guardado acá para no
    # volver a pagar transcripción cada vez que alguien lo abre. Va en
    # CallLog y no en el consumo de IA porque el resumen se arma desde la
    # grabación: aplica también a llamadas que nunca tocaron el voizbot.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
