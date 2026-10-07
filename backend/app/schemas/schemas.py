import re
from datetime import datetime
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.core import urls, validacion as val
from app.core.cifrado import enmascarar
from app.core.clock import a_hora_local


def _telefono(v: str) -> str:
    # Se aceptan los separadores habituales al escribir un número a mano
    # (espacios, guiones, paréntesis, puntos) y se quitan; lo que quede
    # tiene que ser solo teclado telefónico. Un salto de línea o una
    # comilla aquí terminaba dentro de un comando de FreeSWITCH.
    limpio = re.sub(r"[ \-().]", "", v.strip())
    if not val.TELEFONO_RE.fullmatch(limpio):
        raise ValueError('Número inválido: solo dígitos, +, * y #')
    return limpio


def _extension(v: str) -> str:
    if not val.EXTENSION_RE.fullmatch(v):
        raise ValueError('La extensión solo puede tener dígitos (hasta 20)')
    return v


def _nombre(v: str) -> str:
    if not val.NOMBRE_RE.fullmatch(v):
        raise ValueError('Solo letras, números, punto, guion y guion bajo (sin espacios)')
    return v


def _host(v: str) -> str:
    if not val.HOST_RE.fullmatch(v):
        raise ValueError('Host o dominio inválido')
    return v


def _codecs(v: str) -> str:
    if not val.CODECS_RE.fullmatch(v):
        raise ValueError('Lista de códecs inválida (ej. PCMU,PCMA)')
    return v


def _nombre_visible(v: str) -> str:
    if not val.NOMBRE_VISIBLE_RE.fullmatch(v):
        raise ValueError('Nombre con caracteres no permitidos')
    return v


def _moh(v: str) -> str:
    if not val.moh_valido(v):
        raise ValueError("Música en espera no válida: usa la de fábrica, local_stream://nombre o un archivo de sonidos")
    return v


def _sin_control(v: str) -> str:
    if re.search(r"[\x00-\x1f\x7f\ud800-\udfff\ufffe\uffff]", v):
        raise ValueError('No se permiten caracteres de control')
    return v


def _desborde(v: str) -> str:
    """A dónde va el grupo si nadie contesta: un número (extensión, otro
    grupo, *99<ext> del buzón) o un voizbot de la empresa (bot_<id>)."""
    return v if val.BOT_RE.fullmatch(v) else _telefono(v)


Telefono = Annotated[str, Field(min_length=1, max_length=40), AfterValidator(_telefono)]
DestinoDesborde = Annotated[str, Field(min_length=1, max_length=40), AfterValidator(_desborde)]
Extension = Annotated[str, Field(min_length=1, max_length=20), AfterValidator(_extension)]
NombreTecnico = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_nombre)]
HostSip = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_host)]
Codecs = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_codecs)]
NombreVisible = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_nombre_visible)]
TextoSinControl = Annotated[str, Field(max_length=255), AfterValidator(_sin_control)]
MusicaEspera = Annotated[str, Field(max_length=200), AfterValidator(_moh)]


class TrunkBase(BaseModel):
    name: NombreTecnico
    gateway_host: HostSip
    gateway_port: int = Field(default=5060, ge=1, le=65535)
    username: Optional[TextoSinControl] = None
    password: Optional[TextoSinControl] = None
    from_domain: Optional[HostSip] = None
    register_enabled: bool = True
    caller_id_number: Optional[Telefono] = None
    transport: str = Field(default="udp", pattern="^(udp|tcp|tls)$")
    ping: Optional[int] = Field(default=None, ge=5, le=300)
    codec_prefs: Optional[Codecs] = None
    enabled: bool = True


class TrunkCreate(TrunkBase):
    pass


class TrunkUpdate(BaseModel):
    name: Optional[NombreTecnico] = None
    gateway_host: Optional[HostSip] = None
    gateway_port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[TextoSinControl] = None
    password: Optional[TextoSinControl] = None
    from_domain: Optional[HostSip] = None
    register_enabled: Optional[bool] = None
    caller_id_number: Optional[Telefono] = None
    transport: Optional[str] = Field(default=None, pattern="^(udp|tcp|tls)$")
    ping: Optional[int] = Field(default=None, ge=5, le=300)
    codec_prefs: Optional[Codecs] = None
    enabled: Optional[bool] = None


# La salida usa tipos simples a propósito: las reglas estrictas de TrunkBase
# son para lo que ENTRA. Si la salida las heredara, una troncal guardada
# antes de existir la validación (ej. con espacios en el nombre) haría
# fallar el listado completo en vez de mostrarse para poder corregirla.
class TrunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    gateway_host: str
    gateway_port: int = 5060
    username: Optional[str] = None
    password: Optional[str] = None
    from_domain: Optional[str] = None
    register_enabled: bool = True
    caller_id_number: Optional[str] = None
    transport: str = "udp"
    ping: Optional[int] = None
    codec_prefs: Optional[str] = None
    enabled: bool = True
    created_at: datetime

    # La contraseña del proveedor no sale completa (ver core/cifrado.py): con
    # ella se hacen llamadas facturadas a la empresa. Si el panel reenvía la
    # máscara al guardar, no se cambia.
    @field_serializer("password")
    def _ocultar_password(self, v: Optional[str]) -> Optional[str]:
        return enmascarar(v)


class ExtensionBase(BaseModel):
    number: Extension
    # Vacía o ausente = la genera el sistema (ver validacion.generar_clave_sip).
    password: Optional[TextoSinControl] = None
    caller_id_name: Optional[NombreVisible] = None
    voicemail: bool = True
    enabled: bool = True
    outbound_after_hours: bool = False


class ExtensionCreate(ExtensionBase):
    pass


class ExtensionUpdate(BaseModel):
    number: Optional[Extension] = None
    password: Optional[TextoSinControl] = None
    caller_id_name: Optional[NombreVisible] = None
    voicemail: Optional[bool] = None
    enabled: Optional[bool] = None
    outbound_after_hours: Optional[bool] = None


class ExtensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    password: str
    caller_id_name: Optional[str] = None
    voicemail: bool = True
    enabled: bool = True
    outbound_after_hours: bool = False
    created_at: datetime


class VoiceBotTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(default="edge", pattern="^(edge|elevenlabs|deepgram)$")


class VoiceBotNodeTtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(default="audio", pattern="^(audio|whisper)$")
    provider: str = Field(default="edge", pattern="^(edge|elevenlabs|deepgram)$")


class VoiceBotFlowUpdate(BaseModel):
    # Topes: un flujo real tiene decenas de nodos; sin límite, un solo PUT
    # podía generar un dialplan gigante para todas las empresas.
    nodes: list[dict] = Field(default_factory=list, max_length=200)
    edges: list[dict] = Field(default_factory=list, max_length=600)

    @model_validator(mode="after")
    def _flujo_seguro(self):
        # Los textos hablados NO se rechazan aquí (se limpian al generar el
        # dialplan, ver validacion.texto_hablado); sí la estructura, porque
        # los ids y las rutas de audio terminan en nombres y comandos.
        for n in self.nodes:
            if not val.id_nodo_valido(n.get("id", "")):
                raise ValueError("Cada nodo necesita un id de letras, números, guion o guion bajo (máx. 40)")
            datos = n.get("data")
            if datos is None:
                continue
            if not isinstance(datos, dict):
                raise ValueError("El contenido de un nodo debe ser un objeto")
            for clave in ("audio_path", "whisper_audio_path"):
                ruta = datos.get(clave)
                if ruta and not val.ruta_audio_segura(ruta):
                    raise ValueError("Ruta de audio no permitida: solo archivos generados por el editor")
        return self


class CallRequest(BaseModel):
    destination: Telefono
    trunk_id: Optional[int] = None


class VoiceBotBase(BaseModel):
    name: str
    bot_type: str = "ivr"
    welcome_message: Optional[str] = None
    config: Optional[str] = None
    enabled: bool = True


class VoiceBotCreate(VoiceBotBase):
    pass


class VoiceBotUpdate(BaseModel):
    name: Optional[str] = None
    bot_type: Optional[str] = None
    welcome_message: Optional[str] = None
    config: Optional[str] = None
    enabled: Optional[bool] = None


class VoiceBotOut(VoiceBotBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    greeting_audio_path: Optional[str] = None
    flow_json: Optional[str] = None


def _plantilla_crm(v):
    if v is None or not str(v).strip():
        return None
    from app.core import urls
    from app.services.integraciones import validar_plantilla_crm

    try:
        return validar_plantilla_crm(v)
    except urls.UrlNoPermitida as exc:
        raise ValueError(str(exc))


class CampaignBase(BaseModel):
    name: str
    trunk_id: Optional[int] = None
    voicebot_id: Optional[int] = None
    max_concurrency: int = Field(default=5, ge=1, le=100)
    retries: int = Field(default=0, ge=0, le=10)
    # Topes diarios: llamadas lanzadas y minutos por troncal. Vacío = sin tope.
    max_calls_per_day: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    max_minutes_per_day: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    message_template: Optional[str] = None
    # Intención del voizbot para las llamadas de esta campaña (ver
    # app/services/ai_intents.py). Vacío/None = "confirmar" (compatibilidad
    # con las campañas viejas, que eran todas de confirmación).
    ai_intent: Optional[str] = None
    # Minutos de espera antes de volver a marcar según el resultado anterior
    # (busy, noanswer, failed). Ver services/hopper.py.
    reglas_reciclaje: Optional[dict[str, int]] = None
    # Con agentes (services/agentes.py) o con el voizbot (lo de antes).
    metodo: str = Field(default="voizbot", pattern="^(voizbot|manual|vista_previa|progresivo|proporcional|predictivo)$")
    guion: Optional[str] = Field(default=None, max_length=10000)
    grabacion: str = Field(default="todas", pattern="^(todas|ninguna)$")
    # Proporcional y predictivo (services/predictivo.py).
    nivel_marcacion: float = Field(default=1.0, ge=1.0, le=5.0)
    nivel_max: float = Field(default=3.0, ge=1.0, le=5.0)
    abandono_objetivo: float = Field(default=3.0, ge=0.5, le=10.0)
    temporizador_abandono: int = Field(default=2, ge=1, le=10)
    mensaje_abandono: Optional[str] = Field(default=None, max_length=500)
    # CRM externo: la consola del agente abre esta URL con las {variables}
    # del lead, firmada (services/integraciones.py).
    crm_url: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("reglas_reciclaje")
    @classmethod
    def _reglas(cls, v):
        from app.services.hopper import validar_reglas

        return validar_reglas(v)

    @field_validator("crm_url")
    @classmethod
    def _crm(cls, v):
        return _plantilla_crm(v)


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    trunk_id: Optional[int] = None
    voicebot_id: Optional[int] = None
    max_concurrency: Optional[int] = Field(default=None, ge=1, le=100)
    retries: Optional[int] = Field(default=None, ge=0, le=10)
    max_calls_per_day: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    max_minutes_per_day: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    message_template: Optional[str] = None
    ai_intent: Optional[str] = None
    reglas_reciclaje: Optional[dict[str, int]] = None
    metodo: Optional[str] = Field(default=None, pattern="^(voizbot|manual|vista_previa|progresivo|proporcional|predictivo)$")
    guion: Optional[str] = Field(default=None, max_length=10000)
    grabacion: Optional[str] = Field(default=None, pattern="^(todas|ninguna)$")
    nivel_marcacion: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    nivel_max: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    abandono_objetivo: Optional[float] = Field(default=None, ge=0.5, le=10.0)
    temporizador_abandono: Optional[int] = Field(default=None, ge=1, le=10)
    mensaje_abandono: Optional[str] = Field(default=None, max_length=500)
    crm_url: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("reglas_reciclaje")
    @classmethod
    def _reglas(cls, v):
        from app.services.hopper import validar_reglas

        return validar_reglas(v)

    @field_validator("crm_url")
    @classmethod
    def _crm(cls, v):
        return _plantilla_crm(v)


class CampaignOut(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    nivel_actual: Optional[float] = None
    # Si ya hay audio para el mensaje de abandono.
    audio_abandono: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SystemSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_name: str
    fs_domain: str
    fs_esl_host: str
    fs_esl_port: int
    fs_esl_password: str
    fs_http_base: str
    sip_ws_url: str
    sip_server_ip: str
    sip_server_port: int
    elevenlabs_api_key: Optional[str] = None
    agent_webhook_secret: Optional[str] = None
    ai_llm_provider_name: str = "DeepSeek"
    ai_llm_base_url: str = "https://api.deepseek.com/v1"
    ai_llm_model: str = "deepseek-chat"
    ai_llm_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    record_all_calls: bool = False
    allow_international: bool = False
    international_countries: str = ""
    outbound_paused: bool = False
    campaign_hours_weekdays: str = "07:00-19:00"
    campaign_hours_saturday: str = "08:00-15:00"
    campaign_sundays_holidays: bool = False
    outbound_hours_enabled: bool = False
    outbound_hours_weekdays: str = "07:00-19:00"
    outbound_hours_saturday: str = "08:00-13:00"
    outbound_hours_sundays_holidays: bool = False
    ai_stt_provider: str = "elevenlabs"
    ai_voice_provider: str = "elevenlabs"
    ai_voice_id: str = "Xb7hH8MSUJpSbSDYk0k2"
    rate_tts_per_1k_chars: float = 0.0655
    rate_stt_per_minute: float = 0.0065
    rate_dg_tts_per_1k_chars: float = 0.030
    rate_dg_stt_per_minute: float = 0.00483
    rate_llm_in_per_1m: float = 0.04
    rate_llm_out_per_1m: float = 0.04
    backup_enabled: bool = True
    backup_retention_days: int = 14
    last_backup_at: Optional[datetime] = None
    last_backup_ok: Optional[bool] = None
    last_backup_error: Optional[str] = None
    recordings_retention_days: int = 90
    recordings_max_gb: float = 20.0
    backups_max_gb: float = 5.0
    max_call_duration_minutes: int = 60
    max_concurrent_calls: int = 20
    # Conector Issabel (ARI). Vacíos = desactivado (NSPBX usa su FreeSWITCH).
    ari_base_url: Optional[str] = None
    ari_user: Optional[str] = None
    ari_password: Optional[str] = None
    ari_app: str = "nspbx"

    # False cuando la instalación tiene varias empresas: el panel oculta los
    # ajustes globales (Event Socket, disco, respaldos) que no son de una empresa.
    puede_infraestructura: bool = True
    # Identificador de la empresa para el snippet de la burbuja web
    # (`data-empresa`, ver app/api/webcall.py). Solo lectura.
    webcall_empresa: str = ""

    webcall_enabled: bool = False
    webcall_queue_id: Optional[int] = None
    webcall_max_concurrent: int = 5
    webcall_turnstile_site_key: Optional[str] = None
    webcall_turnstile_secret: Optional[str] = None
    webcall_schedule: Optional[str] = None
    webcall_greeting: Optional[str] = None
    webcall_button_text: Optional[str] = None
    webcall_offline_text: Optional[str] = None


class SystemSettingsUpdate(BaseModel):
    app_name: Optional[str] = None
    fs_domain: Optional[str] = None
    fs_esl_host: Optional[str] = None
    fs_esl_port: Optional[int] = None
    fs_esl_password: Optional[str] = None
    fs_http_base: Optional[str] = None
    sip_ws_url: Optional[str] = None
    sip_server_ip: Optional[str] = None
    sip_server_port: Optional[int] = None
    elevenlabs_api_key: Optional[str] = None
    agent_webhook_secret: Optional[str] = None
    ai_llm_provider_name: Optional[str] = None
    ai_llm_base_url: Optional[str] = None
    ai_llm_model: Optional[str] = None
    ai_llm_api_key: Optional[str] = None

    @field_validator("ai_llm_base_url")
    @classmethod
    def _llm_url_publica(cls, v):
        # Evita que una empresa apunte el servidor a la red interna (SSRF).
        if v in (None, ""):
            return v
        try:
            return urls.validar_url_https(v)
        except urls.UrlNoPermitida as exc:
            raise ValueError(str(exc))

    deepgram_api_key: Optional[str] = None

    record_all_calls: Optional[bool] = None
    allow_international: Optional[bool] = None
    outbound_paused: Optional[bool] = None
    # "HH:MM-HH:MM"; vacío o "-" = ese día no se marca.
    campaign_hours_weekdays: Optional[str] = Field(default=None, max_length=11)
    campaign_hours_saturday: Optional[str] = Field(default=None, max_length=11)
    campaign_sundays_holidays: Optional[bool] = None
    outbound_hours_enabled: Optional[bool] = None
    outbound_hours_weekdays: Optional[str] = Field(default=None, max_length=11)
    outbound_hours_saturday: Optional[str] = Field(default=None, max_length=11)
    outbound_hours_sundays_holidays: Optional[bool] = None

    @field_validator("campaign_hours_weekdays", "campaign_hours_saturday", "outbound_hours_weekdays", "outbound_hours_saturday")
    @classmethod
    def _franja_valida(cls, v):
        if v is None:
            return v
        from app.services.horario_marcacion import leer_franja

        leer_franja(v)  # lanza ValueError con el motivo
        return v.strip() or "-"
    # Códigos de país separados por coma ("57, 1, 34"); se guardan normalizados.
    international_countries: Optional[str] = Field(
        default=None, max_length=200, pattern=r"^[0-9+,;\s]*$"
    )
    ai_stt_provider: Optional[str] = Field(default=None, pattern="^(elevenlabs|deepgram)$")
    ai_voice_provider: Optional[str] = Field(default=None, pattern="^(edge|elevenlabs|deepgram)$")
    ai_voice_id: Optional[str] = None

    # Tarifas para estimar el costo del consumo medido. Se ajustan al plan
    # real de cada proveedor: el valor por defecto del TTS sale del panel
    # de ElevenLabs del usuario ($0.15 por 2.290 caracteres).
    rate_tts_per_1k_chars: Optional[float] = Field(default=None, ge=0)
    rate_stt_per_minute: Optional[float] = Field(default=None, ge=0)
    rate_dg_tts_per_1k_chars: Optional[float] = Field(default=None, ge=0)
    rate_dg_stt_per_minute: Optional[float] = Field(default=None, ge=0)
    rate_llm_in_per_1m: Optional[float] = Field(default=None, ge=0)
    rate_llm_out_per_1m: Optional[float] = Field(default=None, ge=0)

    backup_enabled: Optional[bool] = None
    backup_retention_days: Optional[int] = Field(default=None, ge=1, le=365)
    recordings_retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    recordings_max_gb: Optional[float] = Field(default=None, ge=0.5)
    backups_max_gb: Optional[float] = Field(default=None, ge=0.5)
    # 0 = sin tope. El resto de los campos de esta clase no admite 0 (no
    # tendría sentido "cero días de retención"), pero acá sí es un valor
    # legítimo para quien de verdad necesita llamadas sin límite de tiempo.
    max_call_duration_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    max_concurrent_calls: Optional[int] = Field(default=None, ge=1, le=500)

    ari_base_url: Optional[str] = Field(default=None, max_length=255)
    ari_user: Optional[str] = Field(default=None, max_length=80)
    ari_password: Optional[str] = Field(default=None, max_length=255)
    ari_app: Optional[str] = Field(default=None, max_length=80)

    webcall_enabled: Optional[bool] = None
    # 0 = usar el tope de webcall_max_concurrent deshabilitado no aplica:
    # este control siempre debe tener un número (0 sería "nadie puede llamar").
    webcall_queue_id: Optional[int] = None
    webcall_max_concurrent: Optional[int] = Field(default=None, ge=1, le=200)
    webcall_turnstile_site_key: Optional[str] = None
    webcall_turnstile_secret: Optional[str] = None
    webcall_schedule: Optional[str] = None
    webcall_greeting: Optional[str] = Field(default=None, max_length=255)
    webcall_button_text: Optional[str] = Field(default=None, max_length=120)
    webcall_offline_text: Optional[str] = Field(default=None, max_length=255)


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: Optional[str] = None
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    callee_number: Optional[str] = None
    direction: str
    status: str
    duration: int
    billsec: int
    hangup_cause: Optional[str] = None
    recording_path: Optional[str] = None
    has_recording: bool = False
    started_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    setup_ms: Optional[int] = None
    ring_ms: Optional[int] = None
    espera_ms: Optional[int] = None
    colgo: Optional[str] = None


class CampaignNumberRow(BaseModel):
    phone: Telefono
    # Variables para esta llamada puntual (ej. {"cliente": "...", "fecha":
    # "2026-08-21 09:00"}) — rellenan Campaign.message_template. Si trae
    # "cliente" y "fecha", además se usa para cargar/actualizar la cita en
    # la Agenda (ver add_numbers en app/api/campaigns.py).
    vars: dict[str, str] = Field(default_factory=dict)


class CampaignNumberIn(BaseModel):
    numbers: list[CampaignNumberRow] = Field(..., min_length=1, max_length=10000)


class CampaignNumberUpdate(BaseModel):
    phone: Telefono
    vars: Optional[dict[str, str]] = None


def _did(v: str) -> str:
    # El DID va dentro de una expresión regular del dialplan: solo se
    # aceptan dígitos exactos (o el comodín "any"), nunca un patrón propio.
    # Un ".*" o "5.*" con prioridad baja capturaba las llamadas de OTRAS
    # empresas, porque el contexto de entrada `public` es compartido.
    v = v.strip()
    if v.lower() == "any":
        return "any"
    # Sin espacios ni guiones, y sin el +57 de adelante (ver did_canonico):
    # da igual cómo lo escriba la persona o lo mande el proveedor.
    v = val.did_canonico(v)
    if not val.DID_RE.fullmatch(v):
        raise ValueError('El número entrante debe tener solo dígitos, +, * o # (o "any")')
    return v


def _destino(v: str) -> str:
    if not val.DESTINO_RE.fullmatch(v):
        raise ValueError("Destino con caracteres no permitidos")
    return v


DidEntrante = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_did)]
DestinoRuta = Annotated[str, Field(min_length=1, max_length=50), AfterValidator(_destino)]


def _horario_atencion(v: str | None) -> str | None:
    """JSON {"mon": ["08:00", "18:00"], ...} (días mon..sun, horas HH:MM, la
    de inicio antes que la de fin). Vacío = siempre abierto."""
    if v is None or not v.strip():
        return None
    import json
    import re as _re

    try:
        datos = json.loads(v)
    except ValueError:
        raise ValueError("Horario no válido") from None
    dias = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    if not isinstance(datos, dict) or not set(datos) <= dias:
        raise ValueError("Horario no válido: días mon a sun")
    for franja in datos.values():
        if (
            not isinstance(franja, list) or len(franja) != 2
            or not all(isinstance(h, str) and _re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h) for h in franja)
            or franja[0] >= franja[1]
        ):
            raise ValueError("Horario no válido: cada día va de HH:MM a HH:MM, con el inicio antes del fin")
    return json.dumps(datos, sort_keys=True)


HorarioAtencion = Annotated[Optional[str], Field(default=None, max_length=500), AfterValidator(_horario_atencion)]


class InboundRouteBase(BaseModel):
    name: NombreVisible
    did_pattern: DidEntrante
    destination_type: str = Field(..., pattern="^(extension|voicemail|queue|voicebot|hangup)$")
    destination_value: Optional[DestinoRuta] = None
    priority: int = Field(default=10, ge=0, le=1000)
    enabled: bool = True
    horario: HorarioAtencion = None
    fuera_horario_tipo: Optional[str] = Field(default=None, pattern="^(extension|voicemail|queue|voicebot|hangup)$")
    fuera_horario_valor: Optional[DestinoRuta] = None

    @model_validator(mode="after")
    def _destino_coherente(self):
        if not val.destino_valido(self.destination_type, self.destination_value):
            raise ValueError(
                "El destino no corresponde al tipo: extensión o buzón (dígitos), cola (número) "
                "o voizbot (bot_N)"
            )
        return self


class InboundRouteCreate(InboundRouteBase):
    pass


class InboundRouteUpdate(BaseModel):
    name: Optional[NombreVisible] = None
    did_pattern: Optional[DidEntrante] = None
    destination_type: Optional[str] = Field(default=None, pattern="^(extension|voicemail|queue|voicebot|hangup)$")
    destination_value: Optional[DestinoRuta] = None
    priority: Optional[int] = Field(default=None, ge=0, le=1000)
    enabled: Optional[bool] = None
    horario: HorarioAtencion = None
    fuera_horario_tipo: Optional[str] = Field(default=None, pattern="^(extension|voicemail|queue|voicebot|hangup)$")
    fuera_horario_valor: Optional[DestinoRuta] = None


class InboundRouteOut(BaseModel):
    # Sin las reglas estrictas de la entrada: una ruta guardada antes de que
    # existieran no debe romper el listado (ver TrunkOut).
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    did_pattern: str
    destination_type: str
    destination_value: Optional[str] = None
    priority: int = 10
    enabled: bool = True
    horario: Optional[str] = None
    fuera_horario_tipo: Optional[str] = None
    fuera_horario_valor: Optional[str] = None
    created_at: datetime


class OutboundRouteBase(BaseModel):
    name: NombreVisible
    pattern: str = Field(..., min_length=1, max_length=40)
    strip_digits: int = Field(default=0, ge=0, le=20)
    prepend: Optional[str] = Field(default=None, max_length=20, pattern=val.PATRON_TELEFONO)
    # Ids de troncal separados por coma, en orden de preferencia. Vacío =
    # todas las habilitadas de la empresa.
    trunk_ids: str = Field(default="", max_length=120, pattern=r"^$|^[0-9]+(,[0-9]+)*$")
    allow_international: bool = False
    priority: int = Field(default=10, ge=0, le=1000)
    enabled: bool = True

    @model_validator(mode="after")
    def _patron_traducible(self):
        # Se valida acá y no solo al generar el dialplan porque un patrón
        # inválido guardado se convierte en una ruta que desaparece en
        # silencio: la llamada cae en la siguiente regla o no sale, y
        # nadie relaciona el síntoma con lo que escribió.
        val.patron_marcado_a_regex(self.pattern, self.strip_digits)
        return self


class OutboundRouteCreate(OutboundRouteBase):
    pass


class OutboundRouteUpdate(BaseModel):
    name: Optional[NombreVisible] = None
    pattern: Optional[str] = Field(default=None, min_length=1, max_length=40)
    strip_digits: Optional[int] = Field(default=None, ge=0, le=20)
    prepend: Optional[str] = Field(default=None, max_length=20, pattern=val.PATRON_TELEFONO)
    trunk_ids: Optional[str] = Field(default=None, max_length=120, pattern=r"^$|^[0-9]+(,[0-9]+)*$")
    allow_international: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0, le=1000)
    enabled: Optional[bool] = None


class OutboundRouteOut(BaseModel):
    # Sin las reglas estrictas de la entrada, igual que InboundRouteOut.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern: str
    strip_digits: int = 0
    prepend: Optional[str] = None
    trunk_ids: str = ""
    allow_international: bool = False
    priority: int = 10
    enabled: bool = True
    created_at: datetime


class AppointmentBase(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=150)
    phone: str = Field(..., min_length=1, max_length=30)
    appointment_date: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    status: str = Field(default="confirmed", pattern="^(confirmed|cancelled|completed)$")
    notes: Optional[str] = None

    # El navegador manda la fecha en UTC con sufijo Z. Sin normalizarla acá
    # entraba con zona a la capa de agenda y reventaba al compararla contra
    # las fechas naive de la base (500 al crear una cita en un día que ya
    # tuviera otra), además de correr la hora 5 puestos.
    @field_validator("appointment_date")
    @classmethod
    def _normalizar_fecha(cls, v: datetime) -> datetime:
        return a_hora_local(v)


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    patient_name: Optional[str] = None
    phone: Optional[str] = None
    appointment_date: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    status: Optional[str] = Field(default=None, pattern="^(confirmed|cancelled|completed)$")
    notes: Optional[str] = None

    @field_validator("appointment_date")
    @classmethod
    def _normalizar_fecha(cls, v: datetime | None) -> datetime | None:
        return a_hora_local(v) if v else v


class AppointmentOut(AppointmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class AgentBookRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=150)
    phone: str = Field(..., min_length=1, max_length=30)
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM, 24h")
    duration_minutes: int = Field(default=30, ge=5, le=480)
    notes: Optional[str] = None


class AgentCancelRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD; si se omite, cancela la próxima cita de ese teléfono")


class AgentRescheduleRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    old_date: Optional[str] = Field(default=None, description="YYYY-MM-DD de la cita a mover; si se omite, se toma la próxima")
    new_date: str = Field(..., description="YYYY-MM-DD")
    new_time: str = Field(..., description="HH:MM, 24h")


class QueueBase(BaseModel):
    name: NombreTecnico
    extension: Telefono
    strategy: str = Field(
        default="ring-all",
        pattern="^(ring-all|round-robin|top-down|longest-idle-agent|agent-with-least-talk-time|agent-with-fewest-calls|sequentially-by-agent-order|random)$",
    )
    moh_sound: MusicaEspera = "$${hold_music}"
    agents: list[Extension] = Field(default_factory=list)
    max_wait_time: int = Field(default=0, ge=0)
    max_wait_time_with_no_agent: int = Field(default=0, ge=0)
    agent_ring_timeout: int = Field(default=20, ge=3, le=120)
    max_no_answer: int = Field(default=3, ge=0, le=20)
    wrap_up_time: int = Field(default=10, ge=0, le=600)
    record: bool = False
    failover_extension: Optional[DestinoDesborde] = None
    announce_position: bool = False
    devolucion: bool = False
    enabled: bool = True


class QueueCreate(QueueBase):
    pass


class QueueUpdate(BaseModel):
    name: Optional[NombreTecnico] = None
    extension: Optional[Telefono] = None
    strategy: Optional[str] = Field(default=None, pattern="^(ring-all|round-robin|top-down|longest-idle-agent|agent-with-least-talk-time|agent-with-fewest-calls|sequentially-by-agent-order|random)$")
    moh_sound: Optional[MusicaEspera] = None
    agents: Optional[list[Extension]] = None
    max_wait_time: Optional[int] = Field(default=None, ge=0)
    max_wait_time_with_no_agent: Optional[int] = Field(default=None, ge=0)
    agent_ring_timeout: Optional[int] = Field(default=None, ge=3, le=120)
    max_no_answer: Optional[int] = Field(default=None, ge=0, le=20)
    wrap_up_time: Optional[int] = Field(default=None, ge=0, le=600)
    record: Optional[bool] = None
    failover_extension: Optional[DestinoDesborde] = None
    announce_position: Optional[bool] = None
    devolucion: Optional[bool] = None
    enabled: Optional[bool] = None


class QueueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    extension: str
    strategy: str
    moh_sound: str
    agents: list[str]
    max_wait_time: int
    max_wait_time_with_no_agent: int
    agent_ring_timeout: int
    max_no_answer: int
    wrap_up_time: int
    record: bool
    failover_extension: Optional[str] = None
    announce_position: bool
    devolucion: bool = False
    enabled: bool
    created_at: datetime


class AgentesCampanaIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=500)


class ListaUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=120)
    activa: Optional[bool] = None
    prioridad: Optional[int] = Field(default=None, ge=-100, le=100)


class CampaignStats(BaseModel):
    total: int = 0
    pending: int = 0
    dialing: int = 0
    answered: int = 0
    busy: int = 0
    noanswer: int = 0
    failed: int = 0
    done: int = 0
    # En la lista de no llamar: no se marcan.
    no_llamar: int = 0
    # Pendientes que esperan su próximo intento (reciclaje) o cuya lista
    # está pausada: todavía no se pueden marcar.
    en_espera: int = 0
    active_calls: int = 0
    # Consumo de hoy contra los topes diarios de la campaña.
    llamadas_hoy: int = 0
    minutos_hoy: float = 0
    tope_alcanzado: Optional[str] = None
    # Proporcional y predictivo: lo de hoy y el nivel que lleva.
    predictivo: Optional[dict] = None


# ---------- Empresas (tenants) ----------


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    slug: str = Field(
        ...,
        min_length=3,
        max_length=40,
        pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Identificador corto interno (minúsculas, guiones). De él salen el contexto del dialplan y el prefijo de troncales.",
    )
    sip_domain: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Dominio SIP con el que se registran los teléfonos de la empresa.",
    )
    # Subdominio del panel. Vacío = se usa el slug. Debe ser un label de
    # host válido (sin puntos): "consultorio-andino", no
    # "consultorio-andino.ejemplo.com".
    subdomain: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=80,
        pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Subdominio del panel (sin el dominio base). Vacío = se usa el slug.",
    )
    # general | clinica | cobranza
    business_type: str = Field(
        default="general",
        pattern="^(general|clinica|cobranza)$",
        description="Tipo de negocio de la empresa.",
    )
    # Módulos habilitados (pack): voicebot y/o pbx. Se puede ampliar después.
    modules: list[str] = Field(
        default_factory=lambda: ["voicebot", "pbx"],
        description="Módulos: 'voicebot' (bot de IA), 'pbx' (telefonía/llamadas).",
    )

    @field_validator("modules")
    @classmethod
    def _validar_modulos(cls, v: list[str]) -> list[str]:
        permitidos = {"voicebot", "pbx"}
        limpios = sorted({str(m).strip().lower() for m in v} & permitidos)
        if not limpios:
            raise ValueError("Seleccioná al menos un módulo (voicebot o pbx)")
        return limpios


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    sip_domain: Optional[str] = Field(default=None, min_length=3, max_length=255)
    subdomain: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=80,
        pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    business_type: Optional[str] = Field(default=None, pattern="^(general|clinica|cobranza)$")
    modules: Optional[list[str]] = None
    enabled: Optional[bool] = None
    outbound_blocked: Optional[bool] = None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    sip_domain: str
    subdomain: Optional[str] = None
    business_type: str = "general"
    modules: list[str] = Field(default_factory=lambda: ["voicebot", "pbx"])
    enabled: bool
    outbound_blocked: bool = False
    # Servidor FreeSWITCH donde vive (None = el principal).
    nodo_id: Optional[int] = None
    created_at: datetime
    users_count: int = 0
    extensions_count: int = 0
    licencia: Optional["LicenseOut"] = None


class LicenseOut(BaseModel):
    plan: str
    status: str
    # ok | vencida | suspendida (computado en caliente)
    estado: str
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    max_extensions: Optional[int] = None
    max_trunks: Optional[int] = None
    max_concurrent_calls: Optional[int] = None
    max_campaigns: Optional[int] = None
    max_outbound_minutes_day: Optional[int] = None
    max_outbound_cps: Optional[int] = None


class LicenseUpdate(BaseModel):
    plan: Optional[str] = Field(default=None, pattern="^(trial|free|pro|enterprise|custom)$")
    status: Optional[str] = Field(default=None, pattern="^(trial|active|suspended)$")
    expires_at: Optional[datetime] = None
    max_extensions: Optional[int] = Field(default=None, ge=0)
    max_trunks: Optional[int] = Field(default=None, ge=0)
    max_concurrent_calls: Optional[int] = Field(default=None, ge=0)
    max_campaigns: Optional[int] = Field(default=None, ge=0)
    max_outbound_minutes_day: Optional[int] = Field(default=None, ge=0)
    max_outbound_cps: Optional[int] = Field(default=None, ge=1, le=1000)


class TenantCreatedOut(TenantOut):
    """Lo que ve el operador de la plataforma al crear una empresa: incluye
    las credenciales del admin recién creado, que solo se muestran una vez."""

    admin_username: str
    admin_password: str


# ---------- Cobranza ----------


class DebtCreate(BaseModel):
    phone: str = Field(..., min_length=1, max_length=30)
    debtor_name: str = Field(..., min_length=1, max_length=150)
    amount: float = Field(..., ge=0)
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = None
    status: str = Field(default="open", pattern="^(open|promised|paid|overdue)$")


class DebtUpdate(BaseModel):
    debtor_name: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(open|promised|paid|overdue)$")


class DebtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    debtor_name: str
    amount: float
    due_date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime


class PaymentPromiseUpdate(BaseModel):
    """Lo que se marca a mano según el cobro real: si pagó o no, y una nota."""

    status: Optional[str] = Field(default=None, pattern="^(pending|completed|missed)$")
    notes: Optional[str] = None


class PaymentPromiseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debt_id: Optional[int] = None
    phone: str
    debtor_name: Optional[str] = None
    amount_promised: float
    promise_date: datetime
    plan: str
    installments: Optional[int] = None
    notes: Optional[str] = None
    status: str
    call_uuid: Optional[str] = None
    created_at: datetime


# ---------- Usuarios y sesión ----------

# "plataforma" NO está: es el rol que administra todas las empresas y lo
# crea el arranque del sistema (main.py:_asegurar_plataforma), nunca un
# formulario. Si un admin de empresa pudiera asignárselo, dejaría de estar
# limitado a su empresa.
_ROLES_PATRON = "^(admin|supervisor|coordinador|asesor)$"


class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    full_name: str = Field(min_length=2, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    role: str = Field(default="asesor", pattern=_ROLES_PATRON)
    extension_id: Optional[int] = None
    enabled: bool = True

    @field_validator("username")
    @classmethod
    def _usuario_limpio(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise ValueError("El usuario solo admite letras, números, punto, guion y guion bajo")
        return v

    @field_validator("email")
    @classmethod
    def _email_plausible(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("El correo no parece válido")
        return v


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    # «Agregar persona» en un paso: además del usuario, crea su extensión
    # (con el número dado o el siguiente libre) y se la asigna.
    crear_extension: bool = False
    numero_extension: Optional[Extension] = None


class UserUpdate(BaseModel):
    """Todo opcional: se actualiza solo lo que venga."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    email: Optional[str] = Field(default=None, max_length=150)
    role: Optional[str] = Field(default=None, pattern=_ROLES_PATRON)
    extension_id: Optional[int] = None
    enabled: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    email: Optional[str] = None
    role: str
    extension_id: Optional[int] = None
    # Se resuelve en el endpoint para no obligar a la interfaz a cruzar
    # la lista de extensiones solo para mostrar un número.
    extension_number: Optional[str] = None
    enabled: bool
    # Si tiene la verificación en dos pasos activa (nunca el secreto).
    mfa_enabled: bool = False
    last_login_at: Optional[datetime] = None
    created_at: datetime


class ClienteSesion(BaseModel):
    """De dónde entra la persona. La app móvil recibe un refresh token (su
    sesión dura semanas y se renueva); el panel web no lo usa, así que no se
    le entrega: un token largo que nadie guarda es solo exposición. Sin
    `plataforma` (apps viejas) se entrega igual, por compatibilidad."""

    plataforma: Optional[str] = Field(default=None, pattern="^(web|android|ios)$")
    # "Samsung SM-A515F · Android 13": para que la persona reconozca el
    # equipo en Mi cuenta → Sesiones.
    dispositivo: Optional[str] = Field(default=None, max_length=150)


class LoginRequest(ClienteSesion):
    username: str
    password: str
    # Subdominio del panel desde el que se entra (ej. "consultorio-andino"
    # en "consultorio-andino.pbx.example.com"). Si corresponde a alguna
    # empresa, el usuario DEBE pertenecer a ella; si no coincide, se
    # rechaza el login. Vacío = acceso por el dominio base.
    subdomain: Optional[str] = Field(default=None, max_length=80)


class SesionOut(BaseModel):
    """Lo que necesita la interfaz para arrancar: quién es y qué puede."""

    token: str
    expira_en: int
    usuario: UserOut
    permisos: list[str]
    # Módulos habilitados de la empresa (voicebot/pbx). La interfaz oculta
    # las secciones del pack que la empresa no contrató.
    modulos: list[str] = Field(default_factory=list)
    # Solo lo usa la app móvil (el panel web no tiene forma de guardarlo con
    # la misma seguridad que un almacén de llavero del sistema operativo, y
    # no lo necesita: su sesión dura lo que dura la pestaña abierta).
    refresh_token: Optional[str] = None
    # Verificación en dos pasos (ver core/mfa.py): si está activa, y si el
    # rol la exige y falta activarla (la interfaz lleva a activarla).
    mfa_activo: bool = False
    mfa_pendiente: bool = False


class MfaRequeridoOut(BaseModel):
    """Respuesta del login cuando la contraseña es correcta pero falta el
    código: `mfa_token` se canjea en /api/auth/mfa/verificar."""

    mfa_requerido: bool = True
    mfa_token: str


class MfaVerificarRequest(ClienteSesion):
    mfa_token: str = Field(..., max_length=2000)
    # 6 dígitos de la app, o un código de recuperación ("abcd-efgh").
    codigo: str = Field(..., min_length=6, max_length=20)


class MfaCodigoRequest(ClienteSesion):
    codigo: str = Field(..., min_length=6, max_length=20)


class MfaDesactivarRequest(BaseModel):
    password: str = Field(..., max_length=128)
    codigo: str = Field(..., min_length=6, max_length=20)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class DeviceTokenIn(BaseModel):
    platform: str = Field(pattern="^(ios|android)$")
    # Tal cual los reporta expo-callkit-telecom del lado de la app.
    token_type: str = Field(pattern="^(APNS_VOIP|FCM)$")
    token: str


class CambiarPasswordRequest(ClienteSesion):
    password_actual: str
    password_nueva: str = Field(min_length=8, max_length=128)


# ---------- CRM (contactos, campos propios, no llamar) ----------


class TelefonoExtra(BaseModel):
    numero: Telefono
    tipo: str = Field(default="movil", max_length=20)


class ContactoIn(BaseModel):
    nombre: str = Field(default="", max_length=150)
    documento: Optional[str] = Field(default=None, max_length=30)
    telefono: Telefono
    telefonos: list[TelefonoExtra] = Field(default_factory=list, max_length=5)
    email: Optional[str] = Field(default=None, max_length=150)
    direccion: Optional[str] = Field(default=None, max_length=255)
    ciudad: Optional[str] = Field(default=None, max_length=100)
    campos: dict = Field(default_factory=dict)


class ContactoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=150)
    documento: Optional[str] = Field(default=None, max_length=30)
    telefono: Optional[Telefono] = None
    telefonos: Optional[list[TelefonoExtra]] = Field(default=None, max_length=5)
    email: Optional[str] = Field(default=None, max_length=150)
    direccion: Optional[str] = Field(default=None, max_length=255)
    ciudad: Optional[str] = Field(default=None, max_length=100)
    campos: Optional[dict] = None


class NotaIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=4000)


class CampoContactoIn(BaseModel):
    clave: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,39}$")
    nombre: str = Field(..., min_length=1, max_length=80)
    tipo: str = Field(default="texto", pattern="^(texto|numero|fecha|opciones|si_no)$")
    opciones: Optional[list[Annotated[str, Field(min_length=1, max_length=60)]]] = Field(default=None, max_length=50)
    obligatorio: bool = False
    visible_agente: bool = True
    orden: int = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def _opciones(self):
        if self.tipo == "opciones" and not self.opciones:
            raise ValueError("Un campo de opciones necesita al menos una opción")
        return self


class CampoContactoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=80)
    tipo: Optional[str] = Field(default=None, pattern="^(texto|numero|fecha|opciones|si_no)$")
    opciones: Optional[list[Annotated[str, Field(min_length=1, max_length=60)]]] = Field(default=None, max_length=50)
    obligatorio: Optional[bool] = None
    visible_agente: Optional[bool] = None
    orden: Optional[int] = Field(default=None, ge=0, le=1000)


class NoLlamarIn(BaseModel):
    telefono: Telefono
    motivo: Optional[str] = Field(default=None, max_length=255)
    hasta: Optional[datetime] = None
