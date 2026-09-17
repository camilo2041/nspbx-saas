"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ErrorBanner,
  Input,
  Note,
  PageHeader,
  Select,
  Skeleton,
  Toggle,
} from "@/components/ui";
import { WebcallEmbed } from "@/components/webcall-embed";
import { api } from "@/lib/api";
import { DetectedIp, Diagnostics, MaintenanceStatus, Queue, SystemSettings, TtsVoice } from "@/lib/types";

function fecha(iso: string | null) {
  if (!iso) return "Nunca";
  return new Date(iso + "Z").toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// Atajos para llenar de un clic los tres campos que definen el "cerebro"
// del voizbot (URL base + modelo + nombre para mostrar) — pero sin atarse
// a esta lista: cualquier proveedor compatible con la API de chat
// completions de OpenAI funciona a mano con "Personalizado", incluida una
// URL propia (vLLM, Ollama, un proxy interno).
const LLM_PRESETS: { value: string; label: string; base_url?: string; model?: string; provider_name?: string }[] = [
  { value: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", provider_name: "DeepSeek" },
  { value: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", provider_name: "OpenAI" },
  { value: "groq", label: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile", provider_name: "Groq" },
  { value: "together", label: "Together AI", base_url: "https://api.together.xyz/v1", model: "meta-llama/Llama-3.3-70B-Instruct-Turbo", provider_name: "Together AI" },
  { value: "custom", label: "Personalizado / otro" },
];

const empty: SystemSettings = {
  app_name: "",
  fs_domain: "",
  fs_esl_host: "",
  fs_esl_port: 8021,
  fs_esl_password: "",
  fs_http_base: "",
  sip_ws_url: "",
  sip_server_ip: "",
  sip_server_port: 5060,
  elevenlabs_api_key: "",
  agent_webhook_secret: "",
  ai_llm_provider_name: "DeepSeek",
  ai_llm_base_url: "https://api.deepseek.com/v1",
  ai_llm_model: "deepseek-chat",
  ai_llm_api_key: "",
  deepgram_api_key: "",
  record_all_calls: false,
  ai_stt_provider: "elevenlabs",
  ai_voice_provider: "elevenlabs",
  ai_voice_id: "",
  // Calibrado con el consumo real del panel de ElevenLabs, no con la
  // tarifa de lista (ver Consumo IA).
  rate_tts_per_1k_chars: 0.0655,
  rate_stt_per_minute: 0.0065,
  rate_dg_tts_per_1k_chars: 0.03,
  rate_dg_stt_per_minute: 0.00483,
  rate_llm_in_per_1m: 0.04,
  rate_llm_out_per_1m: 0.04,
  backup_enabled: true,
  backup_retention_days: 14,
  last_backup_at: null,
  last_backup_ok: null,
  last_backup_error: null,
  recordings_retention_days: 90,
  recordings_max_gb: 20,
  backups_max_gb: 5,
  max_call_duration_minutes: 60,
  max_concurrent_calls: 20,
  ari_base_url: null,
  ari_user: null,
  ari_password: null,
  ari_app: "nspbx",
  webcall_enabled: false,
  webcall_queue_id: null,
  webcall_max_concurrent: 5,
  webcall_turnstile_site_key: null,
  webcall_turnstile_secret: null,
  webcall_schedule: null,
  webcall_greeting: null,
  webcall_button_text: null,
  webcall_offline_text: null,
};

export default function SettingsPage() {
  const [form, setForm] = useState<SystemSettings>(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [voicesError, setVoicesError] = useState("");
  const [mant, setMant] = useState<MaintenanceStatus | null>(null);
  const [respaldando, setRespaldando] = useState(false);
  const [errorRespaldo, setErrorRespaldo] = useState("");

  const [detectandoIp, setDetectandoIp] = useState(false);
  const [errorDetectarIp, setErrorDetectarIp] = useState("");

  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [diagCargando, setDiagCargando] = useState(true);
  const [errorDiag, setErrorDiag] = useState("");

  const [queues, setQueues] = useState<Queue[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, m, qs] = await Promise.all([
        api.get<SystemSettings>("/api/system/settings"),
        api.get<MaintenanceStatus>("/api/system/maintenance"),
        api.get<Queue[]>("/api/queues"),
      ]);
      setForm(st);
      setMant(m);
      setQueues(qs);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const cargarDiagnostico = useCallback(async () => {
    setDiagCargando(true);
    setErrorDiag("");
    try {
      setDiag(await api.get<Diagnostics>("/api/system/diagnostics"));
    } catch (e) {
      setErrorDiag(e instanceof Error ? e.message : "No se pudo revisar el estado");
    } finally {
      setDiagCargando(false);
    }
  }, []);

  useEffect(() => {
    cargarDiagnostico();
  }, [cargarDiagnostico]);

  const set = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const detectarIp = async () => {
    setDetectandoIp(true);
    setErrorDetectarIp("");
    try {
      const { lan_ip } = await api.get<DetectedIp>("/api/system/detect-ip");
      if (lan_ip) {
        set("sip_server_ip", lan_ip);
      } else {
        setErrorDetectarIp("FreeSWITCH no respondió — no se pudo detectar la IP. Revisa la conexión ESL arriba.");
      }
    } catch (e) {
      setErrorDetectarIp(e instanceof Error ? e.message : "No se pudo detectar");
    } finally {
      setDetectandoIp(false);
    }
  };

  const respaldarAhora = async () => {
    setRespaldando(true);
    setErrorRespaldo("");
    try {
      await api.post("/api/system/maintenance/backup-now");
      setMant(await api.get<MaintenanceStatus>("/api/system/maintenance"));
    } catch (e) {
      setErrorRespaldo(e instanceof Error ? e.message : "No se pudo respaldar");
    } finally {
      setRespaldando(false);
    }
  };

  // Las voces disponibles dependen del proveedor: las de edge-tts son una
  // lista fija; las de ElevenLabs salen de la cuenta del usuario (requiere
  // API key válida). Si la voz guardada ya no está en la lista, se cae a la
  // primera para no dejar el select en un valor inválido.
  useEffect(() => {
    if (loading) return;
    const provider = form.ai_voice_provider;
    api
      .get<TtsVoice[]>(`/api/voicebots/tts/voices?provider=${provider}`)
      .then((vs) => {
        setVoices(vs);
        setVoicesError("");
        setForm((f) =>
          f.ai_voice_provider === provider && !vs.some((v) => v.id === f.ai_voice_id)
            ? { ...f, ai_voice_id: vs[0]?.id ?? "" }
            : f
        );
      })
      .catch(() => {
        setVoices([]);
        setVoicesError(
          provider === "elevenlabs"
            ? "No se pudieron cargar las voces — revisa la API key de ElevenLabs más arriba y guarda."
            : "No se pudieron cargar las voces."
        );
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.ai_voice_provider, loading]);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      setForm(await api.put<SystemSettings>("/api/system/settings", form));
      setError("");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div>
        <PageHeader title="Ajustes" subtitle="Configuración general del PBX y de la conexión con FreeSWITCH (ESL)" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Skeleton className="h-80 rounded-2xl" />
          <Skeleton className="h-80 rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Ajustes"
        subtitle="Configuración general del PBX y de la conexión con FreeSWITCH (ESL). Se aplica al vuelo, sin reiniciar contenedores."
        actions={
          <div className="flex items-center gap-3">
            {saved && (
              <span className="animate-fade-soft flex items-center gap-1.5 text-sm text-ok-text">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-4 w-4">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Guardado
              </span>
            )}
            <Button onClick={save} loading={saving}>
              {saving ? "Guardando…" : "Guardar cambios"}
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card className="mb-4">
        <CardHeader
          title="Diagnóstico"
          subtitle="Estado real ahora mismo — no lo que dice esta pantalla, sino lo que FreeSWITCH y los troncales reportan en vivo"
          actions={
            <Button variant="secondary" size="sm" onClick={cargarDiagnostico} loading={diagCargando}>
              {diagCargando ? "Revisando…" : "Actualizar"}
            </Button>
          }
        />
        <CardBody className="space-y-4">
          {errorDiag && <ErrorBanner message={errorDiag} onClose={() => setErrorDiag("")} />}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
              <div className="mb-1.5 text-xs font-medium text-fg-soft">FreeSWITCH (ESL)</div>
              {diag ? (
                <Badge color={diag.esl_ok ? "green" : "red"} dot>
                  {diag.esl_ok ? "Responde" : "No responde"}
                </Badge>
              ) : (
                <Badge color="slate" dot>
                  Revisando…
                </Badge>
              )}
            </div>
            <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
              <div className="mb-1.5 text-xs font-medium text-fg-soft">WebSocket softphone (7443)</div>
              {diag ? (
                <Badge color={diag.sip_ws_ok ? "green" : "red"} dot>
                  {diag.sip_ws_ok ? "Escuchando" : "No responde"}
                </Badge>
              ) : (
                <Badge color="slate" dot>
                  Revisando…
                </Badge>
              )}
            </div>
            <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
              <div className="mb-1.5 text-xs font-medium text-fg-soft">IP pública actual</div>
              <div className="font-mono text-sm text-fg">{diag?.public_ip ?? "—"}</div>
            </div>
          </div>

          {diag && diag.trunks.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-fg-soft">Troncales</div>
              {diag.trunks.map((t) => (
                <div
                  key={t.id}
                  className={`flex items-center justify-between gap-3 rounded-xl border px-3.5 py-2.5 ${
                    t.contact_no_alcanzable ? "border-danger/25 bg-danger-soft" : "border-line bg-surface-2"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-fg">{t.name}</div>
                    <div className="truncate font-mono text-[11px] text-faint">{t.gateway_host}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <Badge color={t.state === "REGED" ? "green" : "red"} dot>
                      {t.state ?? "Sin registrar"}
                    </Badge>
                    {t.contact_ip && (
                      <div
                        className={`mt-1 font-mono text-[11px] ${
                          t.contact_no_alcanzable ? "font-semibold text-danger-text" : "text-faint"
                        }`}
                      >
                        anuncia: {t.contact_ip}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {diag?.trunks.some((t) => t.contact_no_alcanzable) && (
            <Note tone="warn">
              Al menos un troncal le está anunciando al proveedor una IP privada, loopback o de CGNAT como
              dirección de contacto — el registro se ve bien ("REGED") porque el proveedor no valida esa
              dirección, pero ninguna llamada entrante real va a poder completarse. Compará contra la "IP
              pública actual" de arriba y corregí la configuración del lado de FreeSWITCH.
            </Note>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card delay={0}>
          <CardHeader title="General" subtitle="Identidad del PBX y dominio SIP" />
          <CardBody className="space-y-4">
            <Input label="Nombre del PBX" value={form.app_name} onChange={(v) => set("app_name", v)} required />
            <Input label="Dominio SIP" value={form.fs_domain} onChange={(v) => set("fs_domain", v)} required mono />
            <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
              <div>
                <div className="text-sm text-fg-soft">Grabar todas las llamadas</div>
                <div className="mt-0.5 text-[11px] leading-snug text-faint">
                  Entrantes y salientes. Ocupa ~1 MB por minuto y en muchos países hay que avisarle al interlocutor.
                </div>
              </div>
              <Toggle checked={form.record_all_calls} onChange={(v) => set("record_all_calls", v)} />
            </div>
          </CardBody>
        </Card>

        <Card delay={80}>
          <CardHeader title="FreeSWITCH (ESL)" subtitle="Canal de control con el motor telefónico" />
          <CardBody className="space-y-4">
            <Input label="Host ESL" value={form.fs_esl_host} onChange={(v) => set("fs_esl_host", v)} required mono />
            <Input
              label="Puerto ESL"
              type="number"
              value={form.fs_esl_port}
              onChange={(v) => set("fs_esl_port", Number(v))}
            />
            <Input
              label="Password ESL"
              value={form.fs_esl_password}
              onChange={(v) => set("fs_esl_password", v)}
              required
            />
            <Input
              label="URL base HTTP de FreeSWITCH"
              value={form.fs_http_base}
              onChange={(v) => set("fs_http_base", v)}
              mono
            />
          </CardBody>
        </Card>

        <Card delay={160}>
          <CardHeader title="Softphones" subtitle="Datos que usan el navegador y los teléfonos de escritorio" />
          <CardBody className="space-y-4">
            <Input
              label="URL del softphone (SIP sobre WebSocket)"
              value={form.sip_ws_url}
              onChange={(v) => set("sip_ws_url", v)}
              placeholder="wss://tu-dominio.com/sip"
              hint="La usa el navegador para registrar el softphone; tiene que ser alcanzable desde el equipo del usuario, no desde dentro de Docker. Si el panel se sirve por HTTPS y este campo queda vacío o en localhost, se usa automáticamente wss://<dominio-del-panel>/sip, que es la ruta que el proxy dirige a FreeSWITCH."
              mono
            />
            {/* La advertencia del certificado autofirmado aplica SOLO al
                acceso directo por IP:7443. Detrás de un dominio con
                proxy, el softphone entra por /sip y reusa el certificado
                válido del panel, así que no hay nada que aceptar. */}
            {form.sip_ws_url.startsWith("wss://") && !form.sip_ws_url.includes("/sip") && (
              <Note tone="warn">
                <strong>wss://</strong> cifra la señalización SIP, pero el certificado es autofirmado (no hay un
                dominio público detrás). La primera vez, cada navegador tiene que confiar en él a mano: entrá a{" "}
                <span className="font-mono">
                  https://{form.sip_ws_url.replace("wss://", "").split(":")[0]}:7443
                </span>
                , aceptá la advertencia de "conexión no segura" una vez, y desde ahí el softphone conecta solo. Sin
                este paso, la conexión falla en silencio sin ningún mensaje de error claro.
              </Note>
            )}
            <div>
              <Input
                label="IP del servidor SIP (para softphones de escritorio)"
                value={form.sip_server_ip}
                onChange={(v) => set("sip_server_ip", v)}
                placeholder="192.168.1.100"
                hint="La IP que deben usar 3CXPhone, X-Lite o Zoiper como servidor/dominio SIP. Debe ser una IP de red alcanzable por esos programas (no localhost/127.0.0.1). Se muestra lista para copiar en cada extensión."
                mono
              />
              <div className="mt-1.5 flex items-center gap-2">
                <Button variant="secondary" size="sm" onClick={detectarIp} loading={detectandoIp}>
                  {detectandoIp ? "Detectando…" : "Detectar automáticamente"}
                </Button>
                <span className="text-[11px] text-faint">La lee de lo que FreeSWITCH tiene funcionando ahora.</span>
              </div>
              {errorDetectarIp && (
                <div className="mt-1.5">
                  <ErrorBanner message={errorDetectarIp} onClose={() => setErrorDetectarIp("")} />
                </div>
              )}
            </div>
            <Input
              label="Puerto SIP"
              type="number"
              value={form.sip_server_port}
              onChange={(v) => set("sip_server_port", Number(v))}
              hint="5060 por defecto (UDP/TCP)"
            />
          </CardBody>
        </Card>

        <Card delay={240} className="lg:col-span-2">
          <CardHeader
            title="Modelo de lenguaje (LLM)"
            subtitle="El «cerebro» del voizbot: decide qué decir y qué herramienta usar (agendar, cancelar…). Cualquier proveedor compatible con la API de chat completions de OpenAI funciona — no está atado a uno solo."
          />
          <CardBody className="space-y-4">
            <Select
              label="Proveedor"
              value={LLM_PRESETS.find((p) => p.base_url === form.ai_llm_base_url && p.model === form.ai_llm_model)?.value ?? "custom"}
              onChange={(v) => {
                const preset = LLM_PRESETS.find((p) => p.value === v);
                if (!preset || v === "custom") return;
                setForm((f) => ({
                  ...f,
                  ai_llm_base_url: preset.base_url ?? f.ai_llm_base_url,
                  ai_llm_model: preset.model ?? f.ai_llm_model,
                  ai_llm_provider_name: preset.provider_name ?? f.ai_llm_provider_name,
                }));
              }}
              options={LLM_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
              hint="Es solo un atajo: llena la URL base y el modelo de abajo. Elegí «Personalizado / otro» para escribirlos a mano (por ejemplo un servidor propio con vLLM u Ollama)."
            />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                label="Nombre para mostrar"
                value={form.ai_llm_provider_name}
                onChange={(v) => set("ai_llm_provider_name", v)}
                placeholder="DeepSeek"
                hint="Así aparece en Consumo IA — cambialo si el proveedor cambia."
              />
              <Input
                label="Modelo"
                value={form.ai_llm_model}
                onChange={(v) => set("ai_llm_model", v)}
                placeholder="deepseek-chat"
                mono
              />
            </div>
            <Input
              label="URL base de la API"
              value={form.ai_llm_base_url}
              onChange={(v) => set("ai_llm_base_url", v)}
              placeholder="https://api.deepseek.com/v1"
              hint="Sin la barra final. Se le agrega /chat/completions al hacer la consulta."
              mono
            />
            <Input
              label="API key"
              type="password"
              value={form.ai_llm_api_key ?? ""}
              onChange={(v) => set("ai_llm_api_key", v)}
              placeholder="sk-..."
              required
            />
          </CardBody>
        </Card>

        <Card delay={300} className="lg:col-span-2">
          <CardHeader
            title="Voz y transcripción"
            subtitle="Con qué voz habla el voizbot y cómo entiende lo que dice el paciente — se eligen por separado a propósito"
          />
          <CardBody>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="space-y-4">
                <Select
                  label="Proveedor de voz"
                  value={form.ai_voice_provider}
                  onChange={(v) => {
                    const p = v as SystemSettings["ai_voice_provider"];
                    setForm((f) => ({ ...f, ai_voice_provider: p, ai_voice_id: "" }));
                  }}
                  options={[
                    { value: "edge", label: "Gratis (edge-tts)" },
                    { value: "deepgram", label: "Deepgram Aura-2" },
                    { value: "elevenlabs", label: "ElevenLabs" },
                  ]}
                  hint="El texto a voz es ~95% del costo de una llamada con IA: medido, ~$0,10 con ElevenLabs y ~$0,006 con edge-tts. edge-tts tiene voces nativas de Colombia."
                />
                <Select
                  label="Voz"
                  value={form.ai_voice_id}
                  onChange={(v) => set("ai_voice_id", v)}
                  options={voices.map((v) => ({ value: v.id, label: v.label }))}
                  hint={voicesError || undefined}
                />
                <Select
                  label="Proveedor de transcripción"
                  value={form.ai_stt_provider}
                  onChange={(v) => set("ai_stt_provider", v as SystemSettings["ai_stt_provider"])}
                  options={[
                    { value: "deepgram", label: "Deepgram Nova-3" },
                    { value: "elevenlabs", label: "ElevenLabs Scribe" },
                  ]}
                  hint="La combinación más barata es voz gratis con transcripción de Deepgram ($0,29/hora contra $0,39 de Scribe)."
                />
              </div>
              <div className="space-y-4 border-t border-line pt-4 sm:border-t-0 sm:border-l sm:pl-6 sm:pt-0">
                <Input
                  label="API key de ElevenLabs"
                  type="password"
                  value={form.elevenlabs_api_key ?? ""}
                  onChange={(v) => set("elevenlabs_api_key", v)}
                  placeholder="sk_..."
                  hint="Necesaria si elegís ElevenLabs arriba, en voz o transcripción. Se consigue en elevenlabs.io → Profile → API Keys."
                />
                <Input
                  label="API key de Deepgram"
                  type="password"
                  value={form.deepgram_api_key ?? ""}
                  onChange={(v) => set("deepgram_api_key", v)}
                  hint="Necesaria si elegís Deepgram arriba, en voz o transcripción. Se consigue en console.deepgram.com."
                />
              </div>
            </div>
          </CardBody>
        </Card>

        <Card delay={330} className="lg:col-span-2">
          <CardHeader
            title="Agente conversacional externo"
            subtitle="Solo si otro sistema (no este voizbot) necesita agendar/consultar citas por API"
          />
          <CardBody>
            <Input
              label="Secreto del webhook"
              type="password"
              value={form.agent_webhook_secret ?? ""}
              onChange={(v) => set("agent_webhook_secret", v)}
              placeholder="Genera una cadena larga y aleatoria"
              hint="Lo usa un agente conversacional externo (ej. una app de ElevenLabs Agents) para autenticarse contra /api/appointments/agent/* — configúralo como header 'x-agent-secret' en esa herramienta."
            />
          </CardBody>
        </Card>

        <Card delay={340} className="lg:col-span-2">
          <CardHeader
            title="Conector Issabel (ARI)"
            subtitle="Issabel como motor telefónico externo: NSPBX se conecta como app Stasis para recibir y originar llamadas y streamear el audio por WebSocket"
          />
          <CardBody className="space-y-4">
            <Note tone={form.ari_base_url ? "brand" : "muted"}>
              {form.ari_base_url
                ? "El conector ARI está configurado. Las llamadas que Issabel enrute a la app Stasis llegarán al voicebot."
                : "Vacío = desactivado: NSPBX usa su propio FreeSWITCH. Para conectar Issabel, completá la URL base, las credenciales de ARI y el nombre de la app Stasis que habilite el proveedor."}
            </Note>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                label="URL base de ARI"
                value={form.ari_base_url ?? ""}
                onChange={(v) => set("ari_base_url", v)}
                placeholder="http://issabel.proveedor.com:8088"
                hint="Sin la barra final. El puerto típico de ARI es 8088."
                mono
              />
              <Input
                label="Nombre de la app Stasis"
                value={form.ari_app}
                onChange={(v) => set("ari_app", v)}
                placeholder="nspbx"
                hint="La app que Issabel debe habilitar y enrutar hacia este panel."
                mono
              />
              <Input
                label="Usuario ARI"
                value={form.ari_user ?? ""}
                onChange={(v) => set("ari_user", v)}
                placeholder="nspbx"
                mono
              />
              <Input
                label="Contraseña ARI"
                type="password"
                value={form.ari_password ?? ""}
                onChange={(v) => set("ari_password", v)}
                placeholder="••••••••"
              />
            </div>
          </CardBody>
        </Card>

        <Card delay={360}>
          <CardHeader
            title="Tarifas para estimar costos"
            subtitle="Se usan solo para calcular el dinero en Consumo IA; lo que se mide (caracteres y tokens) es exacto"
          />
          <CardBody className="space-y-4">
            <Input
              label="Voz — USD por cada 1.000 caracteres"
              value={String(form.rate_tts_per_1k_chars ?? "")}
              onChange={(v) => set("rate_tts_per_1k_chars", Number(v) || 0)}
              hint="Sale de dividir el gasto real entre los caracteres facturados en el panel del proveedor. Con el consumo actual: $0,15 ÷ 2.290 caracteres = $0,0655."
            />
            <Input
              label="Transcripción — USD por minuto de audio"
              value={String(form.rate_stt_per_minute ?? "")}
              onChange={(v) => set("rate_stt_per_minute", Number(v) || 0)}
              hint="En cero no suma al costo: los segundos igual quedan medidos. ElevenLabs Scribe se factura aparte de la voz."
            />
            <Input
              label="Modelo — USD por cada millón de tokens de entrada"
              value={String(form.rate_llm_in_per_1m ?? "")}
              onChange={(v) => set("rate_llm_in_per_1m", Number(v) || 0)}
            />
            <Input
              label="Modelo — USD por cada millón de tokens de salida"
              value={String(form.rate_llm_out_per_1m ?? "")}
              onChange={(v) => set("rate_llm_out_per_1m", Number(v) || 0)}
            />
          </CardBody>
        </Card>

        <Card delay={390}>
          <CardHeader
            title="CPU y memoria — capacidad de la central"
            subtitle="Cada llamada activa (audio, transcripción, IA) consume CPU y RAM del servidor — esto le pone techo"
          />
          <CardBody className="space-y-4">
            <Note tone="muted">
              No hay una perilla de "% de CPU" o "GB de RAM" real de por medio — eso lo administra Docker,
              no esta pantalla. Lo que sí controla de verdad cuánto se consume es <strong>cuántas llamadas
              corren a la vez</strong> y <strong>cuánto puede durar cada una</strong>: son los dos factores
              que multiplican el uso real. Mirá el consumo en vivo en el{" "}
              <Link href="/" className="font-medium text-brand-text underline underline-offset-2">
                Dashboard
              </Link>
              .
            </Note>
            <Input
              label="Canales simultáneos en toda la central"
              value={String(form.max_concurrent_calls ?? "")}
              onChange={(v) => set("max_concurrent_calls", Math.max(1, Number(v) || 1))}
              hint="Cuenta ambas patas de cada llamada conectada, no solo campañas. Si se llega al tope, el marcador de campañas deja de originar nuevas hasta que se libere un canal — así nunca se satura la troncal, ni el CPU/RAM del servidor, ni se bloquean las llamadas entrantes."
            />
            <Input
              label="Duración máxima por llamada — minutos"
              value={String(form.max_call_duration_minutes ?? "")}
              onChange={(v) => set("max_call_duration_minutes", Math.max(0, Number(v) || 0))}
              hint="Se corta sola al llegar a este tiempo, contado desde que contestan (no desde que timbra). 0 = sin límite. Aplica a cualquier llamada: entrante, saliente o interna."
            />
            <Note tone="muted">
              La duración máxima protege contra la factura de una llamada que quedó pegada (y el CPU/RAM que
              gasta mientras sigue activa); el tope de canales protege contra que una campaña (o un ataque)
              sature la troncal y el servidor a la vez.
            </Note>
          </CardBody>
        </Card>

        <Card delay={400} className="lg:col-span-2">
          <CardHeader
            title="Espacio en disco — grabaciones y respaldos"
            subtitle="Cuánto disco real puede ocupar cada cosa antes de que el sistema empiece a borrar lo más viejo solo"
          />
          <CardBody className="space-y-4">
            {errorRespaldo && <ErrorBanner message={errorRespaldo} onClose={() => setErrorRespaldo("")} />}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs font-medium text-fg-soft">Último respaldo</span>
                  {mant?.last_backup_ok === true && <Badge color="green">OK</Badge>}
                  {mant?.last_backup_ok === false && <Badge color="red">Falló</Badge>}
                  {mant?.last_backup_ok == null && <Badge color="slate">Sin datos aún</Badge>}
                </div>
                <div className="text-sm text-fg">{fecha(mant?.last_backup_at ?? null)}</div>
                {mant?.last_backup_error && (
                  <div className="mt-1 text-xs text-danger-text">{mant.last_backup_error}</div>
                )}
                <div className="mt-1 text-xs text-faint">
                  {mant?.backups_count ?? 0} archivo(s) ·{" "}
                  {(((mant?.backups_size_mb ?? 0) / 1024) || 0).toFixed(2)} GB de {form.backups_max_gb} GB
                </div>
              </div>

              <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
                <div className="mb-1.5 text-xs font-medium text-fg-soft">Grabaciones en disco</div>
                <div className="text-sm text-fg">
                  {mant?.recordings_size_gb ?? 0} GB de {form.recordings_max_gb} GB
                </div>
                <div className="mt-1 text-xs text-faint">{mant?.recordings_count ?? 0} archivo(s)</div>
              </div>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-3">
              <div>
                <div className="text-sm font-medium text-fg">Respaldo automático diario</div>
                <div className="text-[11px] text-faint">
                  Copia comprimida de toda la base a /backups, una vez al día.
                </div>
              </div>
              <Toggle checked={form.backup_enabled} onChange={(v) => set("backup_enabled", v)} />
            </div>

            <Input
              label="Conservar respaldos — días"
              value={String(form.backup_retention_days ?? "")}
              onChange={(v) => set("backup_retention_days", Math.max(1, Number(v) || 1))}
              hint="Respaldos más viejos que esto se borran solos en la siguiente corrida."
            />
            <Input
              label="Tope de disco para respaldos — GB"
              value={String(form.backups_max_gb ?? "")}
              onChange={(v) => set("backups_max_gb", Math.max(0.5, Number(v) || 0.5))}
              hint="Igual que el de grabaciones: si se supera aunque los respaldos sean recientes (ej. varios 'Respaldar ahora' seguidos), se borran los más viejos hasta volver a estar por debajo."
            />
            <Input
              label="Conservar grabaciones — días"
              value={String(form.recordings_retention_days ?? "")}
              onChange={(v) => set("recordings_retention_days", Math.max(1, Number(v) || 1))}
              hint="Pasado este tiempo, el audio de la llamada se borra. El registro (quién, cuándo, cuánto duró) queda igual en Llamadas."
            />
            <Input
              label="Tope de disco para grabaciones — GB"
              value={String(form.recordings_max_gb ?? "")}
              onChange={(v) => set("recordings_max_gb", Math.max(0.5, Number(v) || 0.5))}
              hint="Si se supera aunque las grabaciones sean recientes, se borran las más viejas hasta volver a estar por debajo. Es la protección contra un disco lleno."
            />

            <Note tone="muted">
              Los archivos quedan en la carpeta <span className="font-mono">backups/</span> del servidor —
              cópialos a otro disco o a la nube de vez en cuando. Esto protege contra una base corrupta o un
              error humano, no contra la pérdida del servidor completo.
            </Note>

            <Button variant="secondary" onClick={respaldarAhora} loading={respaldando}>
              {respaldando ? "Respaldando…" : "Respaldar ahora"}
            </Button>
          </CardBody>
        </Card>
      </div>

      <div className="mt-4">
        <WebcallEmbed
          value={form}
          onPatch={(p) => setForm((f) => ({ ...f, ...p }))}
          queues={queues}
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={save} loading={saving}>
          {saving ? "Guardando…" : "Guardar cambios"}
        </Button>
        {saved && <span className="animate-fade-soft text-sm text-ok-text">Guardado correctamente</span>}
      </div>
    </div>
  );
}
