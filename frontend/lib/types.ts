export interface Trunk {
  id: number;
  name: string;
  gateway_host: string;
  gateway_port: number;
  username: string | null;
  password: string | null;
  from_domain: string | null;
  register_enabled: boolean;
  caller_id_number: string | null;
  transport: "udp" | "tcp" | "tls";
  ping: number | null;
  codec_prefs: string | null;
  enabled: boolean;
  created_at: string;
}

export interface TrunkStatus {
  state: string | null;
  status: string | null;
  ping_ms: string | null;
}

export interface Extension {
  id: number;
  number: string;
  password: string;
  caller_id_name: string | null;
  voicemail: boolean;
  enabled: boolean;
  /** Puede llamar afuera fuera del horario laboral (si la empresa lo limita). */
  outbound_after_hours: boolean;
  created_at: string;
}

export interface TtsVoice {
  id: string;
  label: string;
}

export interface VoiceBot {
  id: number;
  name: string;
  bot_type: "ivr" | "ai";
  welcome_message: string | null;
  config: string | null;
  greeting_audio_path: string | null;
  flow_json: string | null;
  enabled: boolean;
  created_at: string;
}

export type FlowNodeType = "menu" | "transfer" | "hangup" | "horario";

export interface FlowNodeData {
  [key: string]: unknown;
  label?: string;
  start?: boolean;
  audio_path?: string | null;
  tts_text?: string | null;
  extension?: string;
  whisper_audio_path?: string | null;
  ai_intent?: string;
  whisper_text?: string | null;
  /** Nodo «Transferir»: a qué va `extension` (por omisión, una extensión). */
  destino_tipo?: "extension" | "grupo" | "buzon" | "numero";
  /** Nodo «Horario»: JSON {"mon": ["08:00", "18:00"], ...}. */
  horario?: string | null;
}

export interface FlowNode {
  id: string;
  type: FlowNodeType;
  position: { x: number; y: number };
  data: FlowNodeData;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
}

export interface VoiceBotFlow {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

export interface Campaign {
  id: number;
  name: string;
  trunk_id: number | null;
  voicebot_id: number | null;
  max_concurrency: number;
  retries: number;
  /** Topes diarios: llamadas lanzadas y minutos por troncal. null = sin tope. */
  max_calls_per_day: number | null;
  max_minutes_per_day: number | null;
  message_template: string | null;
  ai_intent: string | null;
  /** Minutos de espera antes de volver a marcar, por resultado. */
  reglas_reciclaje: Partial<Record<"busy" | "noanswer" | "failed", number>> | null;
  /** voizbot = lo de antes; el resto, con agentes humanos. */
  metodo: MetodoCampana;
  guion: string | null;
  grabacion: "todas" | "ninguna";
  /** Proporcional: llamadas por agente libre (fijo). */
  nivel_marcacion?: number;
  /** Predictivo: tope de llamadas por agente libre. */
  nivel_max?: number;
  /** Predictivo: lo que está marcando ahora (llamadas en curso por agente libre). */
  nivel_actual?: number | null;
  /** % de contestadas sin agente que se tolera (3 % es el estándar). */
  abandono_objetivo?: number;
  /** Segundos que espera un cliente que contestó antes de darlo por abandonado. */
  temporizador_abandono?: number;
  mensaje_abandono?: string | null;
  audio_abandono?: string | null;
  /** Plantilla de la URL del CRM con {variables}; la consola la abre firmada. */
  crm_url?: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CampaignNumber {
  id: number;
  campaign_id: number;
  phone: string;
  status: string;
  attempts: number;
  last_error: string | null;
  vars: Record<string, string>;
  created_at: string;
}

export interface CampaignNumbersUploadResult {
  added: number;
  updated: number;
  total: number;
  agenda_creadas: number;
  agenda_omitidas: { phone: string; motivo: string }[];
  /** Números que la política de salientes no deja marcar; no se cargan. */
  bloqueados?: { phone: string; motivo: string }[];
}

export interface CampaignStats {
  total: number;
  pending: number;
  dialing: number;
  answered: number;
  busy: number;
  noanswer: number;
  failed: number;
  done: number;
  /** En la lista de no llamar: no se marcan. */
  no_llamar?: number;
  /** Pendientes que esperan su próximo intento o cuya lista está pausada. */
  en_espera?: number;
  active_calls: number;
  llamadas_hoy?: number;
  minutos_hoy?: number;
  /** Si ya llegó a un tope diario, el motivo (sigue mañana). */
  tope_alcanzado?: string | null;
  /** Proporcional y predictivo: lo de hoy y lo que está en curso. */
  predictivo?: MetricasPredictivo | null;
}

export interface MetricasPredictivo {
  intentos: number;
  contestadas: number;
  asignadas: number;
  abandonadas: number;
  /** null mientras no haya contestadas. */
  abandono_pct: number | null;
  nivel: number | null;
  timbrando: number;
  en_espera: number;
}

export interface CampaignWithStats extends Campaign {
  stats: CampaignStats;
  trunk_name?: string | null;
  voicebot_name?: string | null;
}

export interface Debt {
  id: number;
  phone: string;
  debtor_name: string;
  amount: number;
  due_date: string | null;
  invoice_number: string | null;
  notes: string | null;
  status: string;
  created_at: string;
}

export interface PaymentPromise {
  id: number;
  debt_id: number | null;
  phone: string;
  debtor_name: string | null;
  amount_promised: number;
  promise_date: string;
  plan: string;
  installments: number | null;
  notes: string | null;
  status: string;
  call_uuid: string | null;
  created_at: string;
}

export interface CobranzaSummary {
  debts_total: number;
  debts_open: number;
  amount_owed: number;
  promises_total: number;
  promises_pending: number;
  amount_promised: number;
}

export interface InboundRoute {
  id: number;
  name: string;
  did_pattern: string;
  destination_type: "extension" | "voicemail" | "queue" | "voicebot" | "hangup";
  destination_value: string | null;
  priority: number;
  enabled: boolean;
  /** Horario de atención (JSON por día); null = siempre. */
  horario?: string | null;
  /** Fuera de horario, la llamada va a esto (null = colgar). */
  fuera_horario_tipo?: "extension" | "voicemail" | "queue" | "voicebot" | "hangup" | null;
  fuera_horario_valor?: string | null;
  created_at: string;
}

export interface OutboundRoute {
  id: number;
  name: string;
  /** Notación FreePBX/Issabel: X=0-9, Z=1-9, N=2-9, .=uno o más, [1-5]=rango. */
  pattern: string;
  strip_digits: number;
  prepend: string | null;
  /** Ids de troncal separados por coma, en orden. Vacío = todas. */
  trunk_ids: string;
  allow_international: boolean;
  priority: number;
  enabled: boolean;
  created_at: string;
}

export interface Queue {
  id: number;
  name: string;
  extension: string;
  strategy: string;
  moh_sound: string;
  agents: string[];
  max_wait_time: number;
  max_wait_time_with_no_agent: number;
  agent_ring_timeout: number;
  max_no_answer: number;
  wrap_up_time: number;
  record: boolean;
  failover_extension: string | null;
  announce_position: boolean;
  devolucion?: boolean;
  enabled: boolean;
  created_at: string;
}

export interface SystemSettings {
  // false con varias empresas: el backend oculta los ajustes globales (Event Socket, disco, respaldos).
  puede_infraestructura?: boolean;
  app_name: string;
  fs_domain: string;
  fs_esl_host: string;
  fs_esl_port: number;
  fs_esl_password: string;
  fs_http_base: string;
  sip_ws_url: string;
  sip_server_ip: string;
  sip_server_port: number;
  elevenlabs_api_key: string | null;
  agent_webhook_secret: string | null;
  ai_llm_provider_name: string;
  ai_llm_base_url: string;
  ai_llm_model: string;
  ai_llm_api_key: string | null;
  deepgram_api_key: string | null;
  record_all_calls: boolean;
  allow_international: boolean;
  international_countries: string;
  /** Pausa de salientes decidida por la propia empresa. */
  outbound_paused: boolean;
  /** Franja de marcación de campañas ("HH:MM-HH:MM"; "-" = ese día no). */
  campaign_hours_weekdays: string;
  campaign_hours_saturday: string;
  campaign_sundays_holidays: boolean;
  outbound_hours_enabled: boolean;
  outbound_hours_weekdays: string;
  outbound_hours_saturday: string;
  outbound_hours_sundays_holidays: boolean;
  ai_stt_provider: "elevenlabs" | "deepgram";
  ai_voice_provider: "edge" | "elevenlabs" | "deepgram";
  ai_voice_id: string;
  rate_tts_per_1k_chars: number;
  rate_stt_per_minute: number;
  rate_dg_tts_per_1k_chars: number;
  rate_dg_stt_per_minute: number;
  rate_llm_in_per_1m: number;
  rate_llm_out_per_1m: number;
  backup_enabled: boolean;
  backup_retention_days: number;
  last_backup_at: string | null;
  last_backup_ok: boolean | null;
  last_backup_error: string | null;
  recordings_retention_days: number;
  recordings_max_gb: number;
  backups_max_gb: number;
  max_call_duration_minutes: number;
  max_concurrent_calls: number;
  ari_base_url: string | null;
  ari_user: string | null;
  ari_password: string | null;
  ari_app: string;
  webcall_enabled: boolean;
  /** Para el `data-empresa` del snippet (solo lectura). */
  webcall_empresa?: string;
  webcall_queue_id: number | null;
  webcall_max_concurrent: number;
  webcall_turnstile_site_key: string | null;
  webcall_turnstile_secret: string | null;
  webcall_schedule: string | null;
  webcall_greeting: string | null;
  webcall_button_text: string | null;
  webcall_offline_text: string | null;
}

export interface MaintenanceStatus {
  backup_enabled: boolean;
  backup_retention_days: number;
  last_backup_at: string | null;
  last_backup_ok: boolean | null;
  last_backup_error: string | null;
  backups_count: number;
  backups_size_mb: number;
  recordings_retention_days: number;
  recordings_max_gb: number;
  recordings_count: number;
  recordings_size_gb: number;
}

export interface DetectedIp {
  lan_ip: string | null;
  public_ip: string | null;
}

export interface RecursosDisco {
  nombre: string;
  punto: string;
  total_gb: number;
  usado_gb: number;
  libre_gb: number;
  porcentaje: number;
}

export interface Recursos {
  cpu: { porcentaje: number; nucleos: number; por_nucleo: number[] };
  memoria: { total_gb: number; usado_gb: number; disponible_gb: number; porcentaje: number };
  swap: { total_gb: number; usado_gb: number; porcentaje: number };
  discos: RecursosDisco[];
}

export interface TrunkDiagnostic {
  id: number;
  name: string;
  gateway_host: string;
  register_enabled: boolean;
  state: string | null;
  status: string | null;
  contact_ip: string | null;
  contact_no_alcanzable: boolean;
}

export interface Diagnostics {
  esl_ok: boolean;
  sip_ws_ok: boolean;
  public_ip: string | null;
  trunks: TrunkDiagnostic[];
}

export interface Appointment {
  id: number;
  patient_name: string;
  phone: string;
  appointment_date: string;
  duration_minutes: number;
  status: "confirmed" | "cancelled" | "completed";
  notes: string | null;
  created_at: string;
}

export interface GestionRow {
  id: number;
  phone: string | null;
  action: "confirmada" | "cancelada" | "reagendada" | "agendada";
  patient_name: string | null;
  appointment_date: string | null;
  appointment_id: number | null;
  called_at: string;
}

export interface CallLog {
  id: number;
  uuid: string | null;
  caller_number: string | null;
  caller_name: string | null;
  callee_number: string | null;
  direction: "inbound" | "outbound";
  status: string;
  duration: number;
  billsec: number;
  hangup_cause: string | null;
  recording_path: string | null;
  has_recording: boolean;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  /** Tiempos separados, en milisegundos (null si no aplica). */
  setup_ms: number | null;
  ring_ms: number | null;
  espera_ms: number | null;
  colgo: "llamante" | "llamado" | null;
}

export interface CallStats {
  total: number;
  answered: number;
  no_answer: number;
  busy: number;
  failed: number;
  talk_minutes: number;
  /** Promedios en segundos; null mientras no haya llamadas con ese dato. */
  ring_promedio_s: number | null;
  setup_promedio_s: number | null;
  hablado_promedio_s: number | null;
  espera_promedio_s: number | null;
}

/** Un canal en curso, tal como lo publica /ws/tiempo-real. */
export interface LlamadaEnVivo {
  uuid: string;
  direccion: "entrante" | "saliente";
  de: string | null;
  nombre: string | null;
  a: string | null;
  campana_id: string | null;
  estado: "iniciando" | "timbrando" | "hablando" | "espera" | "colgada";
  /** Marcas de tiempo en segundos (epoch). */
  inicio_at: number;
  timbre_at: number | null;
  contesta_at: number | null;
  cambio_at: number;
  otra_pata: string | null;
  causa: string | null;
  ring_ms: number | null;
}

// ---------- Usuarios y sesión ----------
// Los nombres de permiso son los mismos que en
// backend/app/core/permissions.py: si cambian allá, cambian acá.
export const PERMISOS = {
  usuarios: "usuarios:gestionar",
  ajustes: "ajustes:gestionar",
  empresas: "empresas:gestionar",
  telefonia: "telefonia:gestionar",
  colas: "colas:gestionar",
  campanas: "campanas:gestionar",
  voizbotsGestionar: "voizbots:gestionar",
  voizbotsVer: "voizbots:ver",
  llamadasTodas: "llamadas:ver_todas",
  llamadasPropias: "llamadas:ver_propias",
  citas: "citas:gestionar",
  consumoIa: "consumo_ia:ver",
  softphone: "softphone:usar",
  crmVer: "crm:ver",
  crmGestionar: "crm:gestionar",
  agente: "agente:operar",
  supervisionVer: "supervision:ver",
  supervisionIntervenir: "supervision:intervenir",
  reportes: "reportes:ver",
} as const;

export type Rol = "admin" | "supervisor" | "coordinador" | "asesor" | "plataforma";

export interface Empresa {
  id: number;
  name: string;
  slug: string;
  sip_domain: string;
  subdomain: string | null;
  business_type: string;
  modules: string[];
  enabled: boolean;
  /** Salientes cortadas por la plataforma (la empresa no puede deshacerlo). */
  outbound_blocked: boolean;
  /** Servidor FreeSWITCH donde vive (null = el principal). */
  nodo_id: number | null;
  created_at: string;
  users_count: number;
  extensions_count: number;
  licencia: Licencia | null;
}

export interface Licencia {
  plan: string;
  status: string;
  // ok | vencida | suspendida (computado)
  estado: string;
  started_at: string | null;
  expires_at: string | null;
  max_extensions: number | null;
  max_trunks: number | null;
  max_concurrent_calls: number | null;
  max_campaigns: number | null;
  /** Minutos salientes por día; al llegar se cortan hasta medianoche. null = sin tope. */
  max_outbound_minutes_day: number | null;
  /** Llamadas salientes nuevas por segundo (freno de fraude). */
  max_outbound_cps: number | null;
}

export interface EmpresaCreada extends Empresa {
  admin_username: string;
  admin_password: string;
}

export interface Usuario {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: Rol;
  extension_id: number | null;
  extension_number: string | null;
  enabled: boolean;
  /** Verificación en dos pasos activa. */
  mfa_enabled?: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Sesion {
  token: string;
  expira_en: number;
  usuario: Usuario;
  permisos: string[];
  // Módulos habilitados de la empresa (voicebot/pbx) para ocultar secciones.
  modulos: string[];
  mfa_activo?: boolean;
  /** El rol exige verificación en dos pasos y falta activarla: hasta hacerlo,
   *  el backend solo deja entrar a /mfa. */
  mfa_pendiente?: boolean;
}

/** Respuesta del login cuando falta el código de la app (ver /api/auth/mfa/verificar). */
export interface MfaRequerido {
  mfa_requerido: true;
  mfa_token: string;
}

export interface RolInfo {
  value: Rol;
  label: string;
  description: string;
  requiere_extension: boolean;
  permisos: string[];
}

export interface MiEntorno {
  extension: {
    id: number;
    number: string;
    password: string;
    caller_id_name: string | null;
    enabled: boolean;
    dnd: boolean;
  } | null;
  fs_domain: string | null;
  sip_ws_url: string | null;
  sip_server_ip: string | null;
  sip_server_port: number | null;
  // STUN siempre; TURN solo si está configurado en el servidor. Las
  // credenciales vienen firmadas y con vencimiento, así que esta lista
  // no se cachea ni se guarda: se pide junto con el resto del entorno
  // cada vez que el softphone arranca.
  ice_servers: RTCIceServer[] | null;
}

/** GET /api/system/salientes: si la empresa puede llamar afuera ahora. */
export interface EstadoSalientes {
  bloqueo: string | null;
  minutos_hoy: number;
  cupo_diario: number | null;
  permitir_internacional: boolean;
  paises: string[];
}

/** Alerta de tráfico saliente anómalo (ver backend services/alertas.py). */
export interface AlertaTrafico {
  id: number;
  tipo: "pico" | "madrugada" | "destino_nuevo" | "cupo" | string;
  detalle: string;
  cuando: string;
  /** Solo en la vista de la plataforma. */
  empresa?: string;
}

/** Fila del registro de auditoría (backend core/auditoria.py). */
export interface RegistroAuditoria {
  id: number;
  cuando: string;
  actor: string | null;
  accion: string;
  recurso: string | null;
  detalle: Record<string, unknown> | null;
  resultado: "ok" | "denegado" | "rechazado" | "error" | string;
  ip: string | null;
  request_id: string | null;
  /** Solo en la vista de la plataforma. */
  tenant_id?: number | null;
}

// ---------- CRM ----------

export interface TelefonoExtra {
  numero: string;
  tipo: string;
}

export interface Contacto {
  id: number;
  nombre: string;
  documento: string | null;
  telefono: string;
  telefonos: TelefonoExtra[];
  email: string | null;
  direccion: string | null;
  ciudad: string | null;
  campos: Record<string, string | number | boolean>;
  fuente: string | null;
  no_llamar: boolean;
  created_at: string;
  updated_at: string;
}

export type TipoCampo = "texto" | "numero" | "fecha" | "opciones" | "si_no";

export interface CampoContacto {
  id: number;
  clave: string;
  nombre: string;
  tipo: TipoCampo;
  opciones: string[];
  obligatorio: boolean;
  visible_agente: boolean;
  orden: number;
}

export interface NotaContacto {
  id: number;
  texto: string;
  autor: string | null;
  created_at: string;
}

export interface FichaContacto {
  contacto: Contacto;
  telefonos_no_llamar: string[];
  campos_definidos: CampoContacto[];
  notas: NotaContacto[];
  secciones: { llamadas: boolean; campanas: boolean; cobranza: boolean; citas: boolean };
  llamadas: {
    id: number;
    direction: "inbound" | "outbound";
    status: string;
    caller_number: string | null;
    callee_number: string | null;
    billsec: number;
    ring_ms: number | null;
    started_at: string | null;
    tiene_grabacion: boolean;
  }[];
  campanas: {
    numero_id: number;
    campaign_id: number;
    campana: string;
    phone: string;
    status: string;
    attempts: number;
    last_error: string | null;
    ultimo_intento_at: string | null;
    proximo_intento_at: string | null;
  }[];
  deudas: { id: number; amount: number; due_date: string | null; status: string; invoice_number: string | null }[];
  promesas: { id: number; amount_promised: number; promise_date: string; plan: string; status: string }[];
  citas: { id: number; appointment_date: string; status: string; patient_name: string }[];
}

export interface RegistroNoLlamar {
  id: number;
  telefono: string;
  motivo: string | null;
  hasta: string | null;
  creado_por: string | null;
  created_at: string;
  vigente: boolean;
}

export interface ListaCampana {
  id: number;
  campaign_id: number;
  nombre: string;
  activa: boolean;
  prioridad: number;
  origen: "manual" | "csv" | "api";
  created_at: string;
  total: number;
  pendientes: number;
  por_estado: Record<string, number>;
}

export interface VistaPreviaImportacion {
  columnas: string[];
  filas: string[][];
  total_filas: number;
  sugerido: Record<string, string>;
}

export interface ReporteImportacion {
  filas: number;
  creados: number;
  actualizados: number;
  con_error: number;
  errores: { fila: number; motivo: string }[];
  campana: CampaignNumbersUploadResult | null;
}

// ---------- Agentes (contact center, fase 3) ----------

export type MetodoCampana = "voizbot" | "manual" | "vista_previa" | "progresivo" | "proporcional" | "predictivo";
export type EstadoAgente = "LISTO" | "PAUSA" | "PREVIA" | "TIMBRANDO" | "EN_LLAMADA" | "DISPO";
export type CategoriaDisposicion = "venta" | "contacto" | "no_contacto" | "callback" | "promesa" | "no_llamar";

export interface CodigoPausa {
  id: number;
  codigo: string;
  nombre: string;
  pagada?: boolean;
  max_minutos: number | null;
  activo?: boolean;
  orden?: number;
}

export interface Disposicion {
  id: number;
  codigo: string;
  nombre: string;
  categoria: CategoriaDisposicion;
  color: string | null;
  contacto_humano?: boolean;
  activa?: boolean;
  orden?: number;
}

export interface LeadAgente {
  id: number;
  telefono: string;
  intentos: number;
  variables: Record<string, string>;
  campana: { id: number; nombre: string; metodo: MetodoCampana } | null;
  guion: string | null;
  /** Ficha en el CRM de la empresa, ya firmada. */
  crm_url?: string | null;
  contacto: {
    id: number;
    nombre: string;
    documento: string | null;
    telefono: string;
    telefonos: TelefonoExtra[];
    email: string | null;
    ciudad: string | null;
    direccion: string | null;
    campos: Record<string, string | number | boolean>;
  } | null;
  notas: NotaContacto[];
  llamadas_anteriores: { started_at: string | null; status: string; billsec: number; disposicion: string | null }[];
}

export interface EstadoConsola {
  agente: {
    user_id: number;
    estado: EstadoAgente;
    desde: string;
    codigo_pausa_id: number | null;
    campanas: number[];
    audio: boolean;
    campaign_id: number | null;
    lead_id: number | null;
    telefono: string | null;
    contestada_at: string | null;
    pausa_pendiente_id: number | null;
    en_espera?: boolean;
    consulta_destino?: string | null;
    token_audio: string | null;
    extension: string | null;
  } | null;
  campanas: { id: number; nombre: string; metodo: MetodoCampana; status: string }[];
  pausas: CodigoPausa[];
  disposiciones: Disposicion[];
  lead: LeadAgente | null;
  callbacks: {
    id: number;
    lead_id: number;
    campaign_id: number;
    telefono: string;
    nombre: string | null;
    cuando: string;
    nota: string | null;
    propio: boolean;
    vencido: boolean;
  }[];
}

export interface AgenteCampana {
  id: number;
  nombre: string;
  username: string;
  extension: string | null;
  asignado: boolean;
}

// --- Supervisión (fase 5) ---------------------------------------------------

export type ModoMonitoreo = "escuchar" | "susurrar" | "intervenir";

export interface AgenteEnVivo {
  user_id: number;
  nombre: string;
  extension: string | null;
  estado: EstadoAgente;
  desde: string | null;
  /** Lo calcula el servidor: el reloj del navegador puede estar corrido. */
  en_estado_s: number | null;
  audio: boolean;
  pausa: { id: number; nombre: string; max_minutos: number | null } | null;
  pausa_excedida: boolean;
  pausa_pendiente: boolean;
  campanas: { id: number; nombre: string }[];
  campaign_id: number | null;
  campana: string | null;
  telefono: string | null;
  lead_id: number | null;
  hablado_s: number | null;
  monitoreo: { supervisor_id: number; modo: ModoMonitoreo } | null;
}

export interface MetricasHoy {
  intentos: number;
  contestadas: number;
  asignadas: number;
  abandonadas: number;
  abandono_pct: number | null;
}

export interface CampanaEnVivo {
  id: number;
  nombre: string;
  metodo: MetodoCampana;
  status: string;
  agentes: { conectados: number; listo: number; pausa: number; previa: number; timbrando: number; en_llamada: number; dispo: number };
  hopper: number;
  nivel_marcacion: number;
  nivel_max: number;
  nivel_actual: number | null;
  abandono_objetivo: number;
  max_concurrency: number;
  hoy: MetricasHoy;
  llamadas: { timbrando: number; en_espera: number } | null;
  ultimos_15: {
    contacto_pct: number | null;
    abandono_pct: number | null;
    ring_s: number | null;
    aht_s: number | null;
    espera_agente_s: number | null;
  } | null;
}

export interface MiMonitoreo {
  agente_id: number;
  modo: ModoMonitoreo;
  contestado: boolean;
  token: string;
}

export interface ResumenWallboard {
  generado_at: string;
  grupos?: import("@/components/grupos-en-vivo").GrupoEnVivo[];
  empresa?: string;
  agentes: { conectados: number; listos: number; en_llamada: number; en_pausa: number; disposicion: number; pausas_excedidas: number };
  llamadas: { activas: number; timbrando: number; en_espera: number };
  hoy: MetricasHoy;
  campanas: Pick<CampanaEnVivo, "id" | "nombre" | "metodo" | "status" | "agentes" | "hoy" | "llamadas" | "abandono_objetivo">[];
  agentes_lista: { nombre: string; estado: EstadoAgente; en_estado_s: number | null; pausa: string | null; pausa_excedida: boolean }[];
}

export interface TokenWallboard {
  id: number;
  nombre: string;
  vence: string;
  vigente: boolean;
  revocado_at: string | null;
  ultimo_uso_at: string | null;
  created_at: string | null;
  /** Solo en la respuesta de crear: no se vuelve a mostrar. */
  token?: string;
}

// --- Reportes e integraciones (fase 6) ----------------------------------------

export interface PausaReporte {
  codigo_pausa_id: number | null;
  nombre: string;
  veces: number;
  total_s: number;
  promedio_s: number | null;
}

export interface FilaAgenteReporte {
  user_id: number;
  nombre: string;
  sesiones: number;
  login_s: number;
  listo_s: number;
  pausa_s: number;
  previa_s: number;
  timbrando_s: number;
  en_llamada_s: number;
  dispo_s: number;
  llamadas: number;
  aht_s: number | null;
  ocupacion_pct: number | null;
  utilizacion_pct: number | null;
  llamadas_hora: number | null;
  pausas: PausaReporte[];
}

export interface FilaCampanaReporte {
  campaign_id: number;
  nombre: string;
  metodo: string | null;
  intentos: number;
  contestadas: number;
  abandonadas: number;
  ocupado: number;
  no_contesta: number;
  fallidas: number;
  contacto_pct: number | null;
  abandono_pct: number | null;
  ring_promedio_s: number | null;
  aht_s: number | null;
  contactos: number;
  ventas: number;
  promesas: number;
  conversion_pct: number | null;
}

export interface FilaDisposicionReporte {
  grupo_id: number | null;
  grupo: string;
  disposicion: string;
  codigo: string | null;
  categoria: string | null;
  cantidad: number;
  pct: number | null;
}

export interface Cumplimiento {
  abandono: {
    fecha: string;
    campaign_id: number;
    campana: string;
    contestadas: number;
    abandonadas: number;
    abandono_pct: number | null;
    objetivo_pct: number;
    cumple: boolean;
  }[];
  abandono_incumplido: number;
  fuera_de_horario: { fecha: string; campana: string | null; telefono: string | null; agente_id: number | null }[];
  fuera_de_horario_total: number;
  contactos_semana: { telefono: string; semana: string; intentos: number; contestadas: number; campanas: string[] }[];
  contactos_semana_total: number;
  max_contactos_semana: number;
  solo_cobranza: boolean;
}

export interface ReporteProgramado {
  id: number;
  nombre: string;
  tipo: "agentes" | "campanas" | "disposiciones" | "cumplimiento" | "entrantes";
  frecuencia: "diaria" | "semanal" | "mensual";
  hora: number;
  destinatarios: string;
  filtros: { campaign_id?: number; agrupar?: string; max_contactos_semana?: number; solo_cobranza?: boolean };
  activo: boolean;
  ultimo_envio_at: string | null;
  ultimo_periodo: string | null;
  ultimo_error: string | null;
}

export interface WebhookCrm {
  id: number;
  nombre: string;
  url: string;
  eventos: string[];
  activo: boolean;
  fallos_seguidos: number;
  ultimo_ok_at: string | null;
  created_at: string;
  pendientes: number;
  /** Solo al crear: no se vuelve a mostrar. */
  secreto?: string;
}

export interface EntregaWebhook {
  id: number;
  webhook_id: number;
  evento: string;
  estado: "pendiente" | "ok" | "fallida";
  intentos: number;
  proximo_intento_at: string | null;
  ultimo_codigo: number | null;
  ultimo_error: string | null;
  entregado_at: string | null;
  created_at: string;
}

/** Un servidor FreeSWITCH de la plataforma (backend/app/api/nodos.py). */
export interface NodoFreeswitch {
  /** null = el principal (FS_ESL_HOST), que no se edita desde el panel. */
  id: number | null;
  nombre: string;
  esl_host: string;
  esl_port: number;
  sip_host: string | null;
  capacidad_agentes: number | null;
  activo: boolean;
  principal: boolean;
  empresas: number;
  agentes_conectados: number;
  conectado?: boolean;
  error?: string;
  canales?: number | null;
  pico?: number | null;
  version?: string | null;
}

export interface MensajeBuzon {
  id: number;
  extension: string;
  caller_number: string | null;
  caller_name: string | null;
  duracion: number;
  escuchado: boolean;
  transcripcion?: string | null;
  created_at: string | null;
}

export interface DestinosTransferencia {
  extensiones: { numero: string; nombre: string | null; buzon: boolean }[];
  grupos: { numero: string; nombre: string }[];
}
