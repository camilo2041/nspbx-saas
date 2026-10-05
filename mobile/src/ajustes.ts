/**
 * Secciones de Ajustes: las mismas del panel web (frontend/app/settings),
 * cada una con sus campos. La app guarda solo los campos de la sección que
 * se editó (el backend acepta cambios parciales y descarta las claves que
 * vuelven enmascaradas sin tocar).
 */
import type { CampoDef } from "@/src/gestion";
import type { NombreIcono } from "@/src/Icono";
import type { Tono } from "@/src/ui";

export type Ajustes = Record<string, unknown> & { puede_infraestructura?: boolean };

export interface Seccion {
  clave: string;
  titulo: string;
  detalle: string;
  icono: NombreIcono;
  tono: Tono;
  /** Solo con una empresa en la instalación (lo global no se muestra a una empresa). */
  infra?: boolean;
  campos: CampoDef[];
  /** De lo guardado a los valores del formulario (por defecto, tal cual). */
  aFormulario?: (a: Ajustes) => Record<string, unknown>;
  /** De los valores del formulario a lo que se envía. */
  aCuerpo?: (v: Record<string, unknown>) => Record<string, unknown>;
}

const FRANJA = "HH:MM-HH:MM, por ejemplo 07:00-19:00. Vacío o «-» = ese día no.";

export const LLM_PRESETS = [
  { valor: "deepseek", etiqueta: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", nombre: "DeepSeek" },
  { valor: "openai", etiqueta: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", nombre: "OpenAI" },
  { valor: "groq", etiqueta: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile", nombre: "Groq" },
  {
    valor: "together",
    etiqueta: "Together AI",
    base_url: "https://api.together.xyz/v1",
    model: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    nombre: "Together AI",
  },
];

export const DIAS = [
  ["mon", "Lunes"],
  ["tue", "Martes"],
  ["wed", "Miércoles"],
  ["thu", "Jueves"],
  ["fri", "Viernes"],
  ["sat", "Sábado"],
  ["sun", "Domingo"],
] as const;

const texto = (v: unknown) => String(v ?? "").trim();
const textoONulo = (v: unknown) => texto(v) || null;
const numero = (v: unknown) => Number(String(v ?? "").replace(",", ".")) || 0;

/** Los campos que se guardan tal cual (texto), salvo los que se indique. */
function directo(claves: string[], numeros: string[] = [], nulos: string[] = [], interruptores: string[] = []) {
  return (v: Record<string, unknown>) => {
    const out: Record<string, unknown> = {};
    for (const k of claves) {
      if (numeros.includes(k)) out[k] = numero(v[k]);
      else if (interruptores.includes(k)) out[k] = !!v[k];
      else if (nulos.includes(k)) out[k] = textoONulo(v[k]);
      else out[k] = texto(v[k]);
    }
    return out;
  };
}

export function secciones(opc: {
  colas: { id: number; name: string }[];
  voces: Record<string, { id: string; label: string }[]>;
}): Seccion[] {
  return [
    {
      clave: "general",
      titulo: "General",
      detalle: "Nombre, grabación y llamadas internacionales",
      icono: "ajustes",
      tono: "neutro",
      campos: [
        { clave: "app_name", etiqueta: "Nombre del PBX" },
        { clave: "fs_domain", etiqueta: "Dominio SIP", visibleSi: (v) => v.__infra === true },
        {
          clave: "record_all_calls",
          etiqueta: "Grabar todas las llamadas",
          tipo: "conmutador",
          ayuda: "Entrantes y salientes. Ocupa ~1 MB por minuto y en muchos países hay que avisarle al interlocutor.",
        },
        {
          clave: "allow_international",
          etiqueta: "Permitir llamadas internacionales",
          tipo: "conmutador",
          ayuda: "Apagado, solo se marcan números nacionales. Actívalo solo si lo necesitas: es el destino habitual del fraude telefónico.",
        },
        {
          clave: "international_countries",
          etiqueta: "Países permitidos",
          placeholder: "57, 1, 34",
          visibleSi: (v) => !!v.allow_international,
          ayuda: "Códigos de país separados por coma. Vacío = ninguno. Satelitales y tarifas premium quedan bloqueados siempre.",
        },
      ],
      aCuerpo: (v) => ({
        app_name: texto(v.app_name),
        ...(v.__infra ? { fs_domain: texto(v.fs_domain) } : {}),
        record_all_calls: !!v.record_all_calls,
        allow_international: !!v.allow_international,
        international_countries: texto(v.international_countries),
      }),
    },
    {
      clave: "horario-salientes",
      titulo: "Horario de las salientes",
      detalle: "Llamar afuera solo en horario laboral",
      icono: "horario",
      tono: "aviso",
      campos: [
        {
          clave: "outbound_hours_enabled",
          etiqueta: "Salientes de los teléfonos solo en horario laboral",
          tipo: "conmutador",
          ayuda:
            "Fuera de la franja solo llaman afuera las extensiones marcadas para guardias. Una extensión robada se usa de noche y en fin de semana. Los desvíos del menú a un celular de guardia no se cortan.",
        },
        { clave: "outbound_hours_weekdays", etiqueta: "Lunes a viernes", placeholder: "07:00-19:00", ayuda: FRANJA, visibleSi: (v) => !!v.outbound_hours_enabled },
        { clave: "outbound_hours_saturday", etiqueta: "Sábados", placeholder: "08:00-13:00", ayuda: FRANJA, visibleSi: (v) => !!v.outbound_hours_enabled },
        {
          clave: "outbound_hours_sundays_holidays",
          etiqueta: "Domingos y festivos (con la franja del sábado)",
          tipo: "conmutador",
          visibleSi: (v) => !!v.outbound_hours_enabled,
        },
      ],
      aCuerpo: directo(
        ["outbound_hours_enabled", "outbound_hours_weekdays", "outbound_hours_saturday", "outbound_hours_sundays_holidays"],
        [],
        [],
        ["outbound_hours_enabled", "outbound_hours_sundays_holidays"]
      ),
    },
    {
      clave: "horario-campanas",
      titulo: "Horario de las campañas",
      detalle: "Cuándo pueden marcar (cobranza: Ley 2300)",
      icono: "campana",
      tono: "info",
      campos: [
        { clave: "campaign_hours_weekdays", etiqueta: "Lunes a viernes", placeholder: "07:00-19:00", ayuda: FRANJA },
        { clave: "campaign_hours_saturday", etiqueta: "Sábados", placeholder: "08:00-15:00", ayuda: FRANJA },
        {
          clave: "campaign_sundays_holidays",
          etiqueta: "Domingos y festivos (con la franja del sábado)",
          tipo: "conmutador",
          ayuda:
            "Fuera de la franja las campañas esperan sin dar números por fallidos. Las de cobranza nunca salen de la franja de la Ley 2300 (lunes a viernes 7:00-19:00, sábados 8:00-15:00, sin domingos ni festivos), aunque acá se amplíe.",
        },
      ],
      aCuerpo: directo(["campaign_hours_weekdays", "campaign_hours_saturday", "campaign_sundays_holidays"], [], [], ["campaign_sundays_holidays"]),
    },
    {
      clave: "softphones",
      titulo: "Softphones",
      detalle: "Datos que usan el navegador y los teléfonos de escritorio",
      icono: "extension",
      tono: "marca",
      campos: [
        {
          clave: "sip_ws_url",
          etiqueta: "URL del softphone (SIP sobre WebSocket)",
          placeholder: "wss://tu-dominio.com/sip",
          ayuda: "Tiene que ser alcanzable desde el equipo del usuario. Vacío con el panel por HTTPS = wss://<dominio-del-panel>/sip.",
        },
        {
          clave: "sip_server_ip",
          etiqueta: "IP del servidor SIP (teléfonos de escritorio)",
          placeholder: "192.168.1.100",
          ayuda: "La que usan Zoiper, X-Lite o 3CX como servidor. No puede ser localhost.",
        },
        { clave: "sip_server_port", etiqueta: "Puerto SIP", tipo: "numero", ayuda: "5060 por defecto." },
      ],
      aCuerpo: directo(["sip_ws_url", "sip_server_ip", "sip_server_port"], ["sip_server_port"]),
    },
    {
      clave: "llm",
      titulo: "Modelo de lenguaje",
      detalle: "El «cerebro» del voizbot",
      icono: "asistente",
      tono: "marca",
      campos: [
        {
          clave: "__preset",
          etiqueta: "Atajo de proveedor",
          tipo: "opciones",
          opciones: [...LLM_PRESETS.map((p) => ({ valor: p.valor, etiqueta: p.etiqueta })), { valor: "custom", etiqueta: "Personalizado / otro" }],
          ayuda: "Llena la URL y el modelo. Con «Personalizado» escribes los tuyos (un servidor propio con vLLM u Ollama, por ejemplo).",
        },
        { clave: "ai_llm_provider_name", etiqueta: "Nombre para mostrar", visibleSi: (v) => v.__preset === "custom", ayuda: "Así aparece en Consumo IA." },
        { clave: "ai_llm_model", etiqueta: "Modelo", visibleSi: (v) => v.__preset === "custom" },
        {
          clave: "ai_llm_base_url",
          etiqueta: "URL base de la API",
          visibleSi: (v) => v.__preset === "custom",
          ayuda: "Sin la barra final; se le agrega /chat/completions.",
        },
        { clave: "ai_llm_api_key", etiqueta: "API key", tipo: "secreto", placeholder: "sk-..." },
      ],
      aFormulario: (a) => ({
        ...a,
        __preset: LLM_PRESETS.find((p) => p.base_url === a.ai_llm_base_url && p.model === a.ai_llm_model)?.valor ?? "custom",
      }),
      aCuerpo: (v) => {
        const p = LLM_PRESETS.find((x) => x.valor === v.__preset);
        return {
          ai_llm_provider_name: p ? p.nombre : texto(v.ai_llm_provider_name),
          ai_llm_model: p ? p.model : texto(v.ai_llm_model),
          ai_llm_base_url: p ? p.base_url : texto(v.ai_llm_base_url),
          ai_llm_api_key: String(v.ai_llm_api_key ?? ""),
        };
      },
    },
    {
      clave: "voz",
      titulo: "Voz y transcripción",
      detalle: "Con qué voz habla el voizbot y cómo entiende",
      icono: "audio",
      tono: "info",
      campos: [
        {
          clave: "ai_voice_provider",
          etiqueta: "Proveedor de voz",
          tipo: "opciones",
          opciones: [
            { valor: "edge", etiqueta: "Gratis (edge-tts)", detalle: "Voces nativas de Colombia; ~$0,006 por llamada." },
            { valor: "deepgram", etiqueta: "Deepgram Aura-2" },
            { valor: "elevenlabs", etiqueta: "ElevenLabs", detalle: "La más natural; ~$0,10 por llamada." },
          ],
          ayuda: "El texto a voz es casi todo el costo de una llamada con IA.",
        },
        ...(["edge", "deepgram", "elevenlabs"] as const).map(
          (prov): CampoDef =>
            opc.voces[prov]?.length
              ? {
                  clave: `__voz_${prov}`,
                  etiqueta: "Voz",
                  tipo: "opciones",
                  visibleSi: (v) => v.ai_voice_provider === prov,
                  opciones: opc.voces[prov].map((x) => ({ valor: x.id, etiqueta: x.label })),
                }
              : {
                  clave: `__voz_${prov}`,
                  etiqueta: "Voz (identificador)",
                  visibleSi: (v) => v.ai_voice_provider === prov,
                  ayuda: "No se pudo traer la lista de voces de este proveedor; escribe el identificador.",
                }
        ),
        {
          clave: "ai_stt_provider",
          etiqueta: "Proveedor de transcripción",
          tipo: "opciones",
          opciones: [
            { valor: "deepgram", etiqueta: "Deepgram Nova-3", detalle: "$0,29 por hora." },
            { valor: "elevenlabs", etiqueta: "ElevenLabs Scribe", detalle: "$0,39 por hora." },
          ],
        },
        {
          clave: "elevenlabs_api_key",
          etiqueta: "API key de ElevenLabs",
          tipo: "secreto",
          visibleSi: (v) => v.ai_voice_provider === "elevenlabs" || v.ai_stt_provider === "elevenlabs",
        },
        {
          clave: "deepgram_api_key",
          etiqueta: "API key de Deepgram",
          tipo: "secreto",
          visibleSi: (v) => v.ai_voice_provider === "deepgram" || v.ai_stt_provider === "deepgram",
        },
      ],
      aFormulario: (a) => ({ ...a, [`__voz_${a.ai_voice_provider}`]: a.ai_voice_id }),
      aCuerpo: (v) => ({
        ai_voice_provider: v.ai_voice_provider,
        ai_voice_id: texto(v[`__voz_${v.ai_voice_provider}`]),
        ai_stt_provider: v.ai_stt_provider,
        elevenlabs_api_key: String(v.elevenlabs_api_key ?? ""),
        deepgram_api_key: String(v.deepgram_api_key ?? ""),
      }),
    },
    {
      clave: "tarifas",
      titulo: "Tarifas para estimar costos",
      detalle: "Solo para calcular el dinero en Consumo IA",
      icono: "dinero",
      tono: "ok",
      campos: [
        { clave: "rate_tts_per_1k_chars", etiqueta: "ElevenLabs voz — USD por 1.000 caracteres", tipo: "decimal" },
        { clave: "rate_stt_per_minute", etiqueta: "ElevenLabs transcripción — USD por minuto", tipo: "decimal" },
        { clave: "rate_dg_tts_per_1k_chars", etiqueta: "Deepgram voz — USD por 1.000 caracteres", tipo: "decimal" },
        { clave: "rate_dg_stt_per_minute", etiqueta: "Deepgram transcripción — USD por minuto", tipo: "decimal" },
        { clave: "rate_llm_in_per_1m", etiqueta: "Modelo — USD por millón de tokens de entrada", tipo: "decimal" },
        { clave: "rate_llm_out_per_1m", etiqueta: "Modelo — USD por millón de tokens de salida", tipo: "decimal" },
      ],
      aCuerpo: (v) => {
        const k = ["rate_tts_per_1k_chars", "rate_stt_per_minute", "rate_dg_tts_per_1k_chars", "rate_dg_stt_per_minute", "rate_llm_in_per_1m", "rate_llm_out_per_1m"];
        return directo(k, k)(v);
      },
    },
    {
      clave: "webcall",
      titulo: "Llamada desde la web",
      detalle: "Botón «hablar con un agente» para tu sitio",
      icono: "mundo",
      tono: "info",
      campos: [
        { clave: "webcall_enabled", etiqueta: "Activar el botón", tipo: "conmutador" },
        {
          clave: "webcall_queue_id",
          etiqueta: "Cola que atiende",
          tipo: "opciones",
          visibleSi: (v) => !!v.webcall_enabled,
          opciones: opc.colas.map((q) => ({ valor: String(q.id), etiqueta: q.name })),
          ayuda: "Sus agentes reciben las llamadas del sitio como cualquier entrante.",
        },
        {
          clave: "webcall_max_concurrent",
          etiqueta: "Máximo de llamadas web a la vez",
          tipo: "numero",
          visibleSi: (v) => !!v.webcall_enabled,
          ayuda: "Al llegar, el botón responde que todos los agentes están ocupados.",
        },
        { clave: "webcall_greeting", etiqueta: "Invitación", visibleSi: (v) => !!v.webcall_enabled },
        { clave: "webcall_button_text", etiqueta: "Texto del botón", visibleSi: (v) => !!v.webcall_enabled },
        { clave: "webcall_offline_text", etiqueta: "Mensaje fuera de horario", visibleSi: (v) => !!v.webcall_enabled },
        ...DIAS.map(
          ([k, nombre]): CampoDef => ({
            clave: `__dia_${k}`,
            etiqueta: `Horario ${nombre}`,
            placeholder: "08:00-18:00",
            visibleSi: (v) => !!v.webcall_enabled,
            ayuda: k === "sun" ? "Vacío = ese día no se atiende. Si todos quedan vacíos, se atiende siempre." : undefined,
          })
        ),
        { clave: "webcall_turnstile_site_key", etiqueta: "Turnstile: site key", visibleSi: (v) => !!v.webcall_enabled },
        {
          clave: "webcall_turnstile_secret",
          etiqueta: "Turnstile: secret key",
          tipo: "secreto",
          visibleSi: (v) => !!v.webcall_enabled,
          ayuda: "Frena a los robots que abusarían del botón (Cloudflare Turnstile).",
        },
      ],
      aFormulario: (a) => {
        let horario: Record<string, [string, string]> = {};
        try {
          horario = a.webcall_schedule ? JSON.parse(String(a.webcall_schedule)) : {};
        } catch {
          horario = {};
        }
        const dias: Record<string, string> = {};
        for (const [k] of DIAS) if (Array.isArray(horario[k])) dias[`__dia_${k}`] = `${horario[k][0]}-${horario[k][1]}`;
        return { ...a, webcall_queue_id: a.webcall_queue_id ? String(a.webcall_queue_id) : "", ...dias };
      },
      aCuerpo: (v) => {
        const horario: Record<string, [string, string]> = {};
        for (const [k, nombre] of DIAS) {
          const t = texto(v[`__dia_${k}`]);
          if (!t || t === "-") continue;
          const m = t.match(/^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/);
          if (!m) throw new Error(`El horario del ${nombre.toLowerCase()} va como 08:00-18:00.`);
          horario[k] = [m[1].padStart(5, "0"), m[2].padStart(5, "0")];
        }
        return {
          webcall_enabled: !!v.webcall_enabled,
          webcall_queue_id: v.webcall_queue_id ? Number(v.webcall_queue_id) : null,
          webcall_max_concurrent: numero(v.webcall_max_concurrent) || 1,
          webcall_greeting: textoONulo(v.webcall_greeting),
          webcall_button_text: textoONulo(v.webcall_button_text),
          webcall_offline_text: textoONulo(v.webcall_offline_text),
          webcall_schedule: Object.keys(horario).length ? JSON.stringify(horario) : null,
          webcall_turnstile_site_key: textoONulo(v.webcall_turnstile_site_key),
          webcall_turnstile_secret: textoONulo(v.webcall_turnstile_secret),
        };
      },
    },
    {
      clave: "agente",
      titulo: "Agente conversacional externo",
      detalle: "Otro sistema que agenda citas por API",
      icono: "llave",
      tono: "neutro",
      campos: [
        {
          clave: "agent_webhook_secret",
          etiqueta: "Secreto del webhook",
          tipo: "secreto",
          generar: true,
          ayuda: "Solo si otro sistema (no este voizbot) necesita agendar o consultar citas por API.",
        },
      ],
      aCuerpo: (v) => ({ agent_webhook_secret: String(v.agent_webhook_secret ?? "") }),
    },
    {
      clave: "capacidad",
      titulo: "Capacidad de la central",
      detalle: "Llamadas a la vez y duración máxima",
      icono: "tendencia",
      tono: "aviso",
      infra: true,
      campos: [
        {
          clave: "max_concurrent_calls",
          etiqueta: "Canales simultáneos en toda la central",
          tipo: "numero",
          ayuda: "Cuenta las dos patas de cada llamada. Al llegar, las campañas dejan de originar hasta que se libere un canal.",
        },
        {
          clave: "max_call_duration_minutes",
          etiqueta: "Duración máxima por llamada (minutos)",
          tipo: "numero",
          ayuda: "Se corta sola al llegar, contado desde que contestan. 0 = sin límite.",
        },
      ],
      aCuerpo: (v) => ({ max_concurrent_calls: Math.max(1, numero(v.max_concurrent_calls)), max_call_duration_minutes: Math.max(0, numero(v.max_call_duration_minutes)) }),
    },
    {
      clave: "esl",
      titulo: "FreeSWITCH (ESL)",
      detalle: "Canal de control con el motor telefónico",
      icono: "servidor",
      tono: "neutro",
      infra: true,
      campos: [
        { clave: "fs_esl_host", etiqueta: "Host ESL" },
        { clave: "fs_esl_port", etiqueta: "Puerto ESL", tipo: "numero" },
        { clave: "fs_esl_password", etiqueta: "Contraseña ESL", tipo: "secreto", ayuda: "Vacía = no se cambia." },
        { clave: "fs_http_base", etiqueta: "URL base HTTP de FreeSWITCH" },
      ],
      aCuerpo: directo(["fs_esl_host", "fs_esl_port", "fs_esl_password", "fs_http_base"], ["fs_esl_port"]),
    },
    {
      clave: "ari",
      titulo: "Conector Issabel (ARI)",
      detalle: "Issabel como motor telefónico externo",
      icono: "troncal",
      tono: "neutro",
      infra: true,
      campos: [
        { clave: "ari_base_url", etiqueta: "URL base de ARI", placeholder: "http://issabel:8088" },
        { clave: "ari_app", etiqueta: "Nombre de la app Stasis", placeholder: "nspbx" },
        { clave: "ari_user", etiqueta: "Usuario ARI" },
        { clave: "ari_password", etiqueta: "Contraseña ARI", tipo: "secreto" },
      ],
      aCuerpo: (v) => ({
        ari_base_url: textoONulo(v.ari_base_url),
        ari_app: texto(v.ari_app) || "nspbx",
        ari_user: textoONulo(v.ari_user),
        ari_password: textoONulo(v.ari_password),
      }),
    },
    {
      clave: "disco",
      titulo: "Disco y respaldos",
      detalle: "Cuánto se guarda y por cuánto tiempo",
      icono: "servidor",
      tono: "info",
      infra: true,
      campos: [
        { clave: "backup_enabled", etiqueta: "Respaldo diario de la base", tipo: "conmutador", ayuda: "Copia comprimida de toda la base a /backups, una vez al día." },
        { clave: "backup_retention_days", etiqueta: "Conservar respaldos (días)", tipo: "numero" },
        { clave: "backups_max_gb", etiqueta: "Tope de disco para respaldos (GB)", tipo: "decimal" },
        {
          clave: "recordings_retention_days",
          etiqueta: "Conservar grabaciones (días)",
          tipo: "numero",
          ayuda: "Pasado este tiempo se borra el audio; el registro de la llamada queda.",
        },
        { clave: "recordings_max_gb", etiqueta: "Tope de disco para grabaciones (GB)", tipo: "decimal", ayuda: "Si se supera, se borran las más viejas." },
      ],
      aCuerpo: (v) => ({
        backup_enabled: !!v.backup_enabled,
        backup_retention_days: Math.max(1, numero(v.backup_retention_days)),
        backups_max_gb: Math.max(0.5, numero(v.backups_max_gb)),
        recordings_retention_days: Math.max(1, numero(v.recordings_retention_days)),
        recordings_max_gb: Math.max(0.5, numero(v.recordings_max_gb)),
      }),
    },
  ];
}
