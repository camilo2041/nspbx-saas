"use client";

import { useEffect, useState } from "react";
import { Button, Check, IconButton, Input, Note, Select, Textarea } from "@/components/ui";
import { EditorHorario } from "@/components/editor-horario";
import { api } from "@/lib/api";
import { FlowNode, TtsVoice } from "@/lib/types";

/* Qué hace cada gestión, en la propia pantalla: el guion, las
   herramientas y el tope de turnos cambian según la que se elija
   (ver backend/app/services/ai_intents.py). */
const AYUDA_GESTION: Record<string, string> = {
  confirmar:
    "Saluda nombrando la cita y solo pide un sí o un no. Si no puede asistir, le ofrece moverla. Pensada para resolverse en 2 o 3 frases.",
  reagendar:
    "Da por hecho que quiere mover la cita: pregunta el día, consulta la agenda y ofrece horarios reales. No puede crear una cita nueva por error.",
  cancelar:
    "Ofrece moverla una sola vez antes de cancelar. Si insiste, cancela sin poner peros.",
  agendar:
    "Para quien todavía no tiene cita. Pide el día, ofrece horarios y pregunta el nombre una sola vez.",
  general:
    "El bot averigua qué necesita la persona. Útil cuando la llamada no entra por una opción del menú.",
};

type Provider = "edge" | "elevenlabs";

const fileInputClass =
  "block w-full cursor-pointer text-xs text-muted file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-3 file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-fg-soft hover:file:bg-line";

export function NodePanel({
  botId,
  node,
  voices: initialVoices,
  onChange,
  onDelete,
  onClose,
}: {
  botId: number;
  node: FlowNode;
  voices: TtsVoice[];
  onChange: (data: Partial<FlowNode["data"]>, autoSave?: boolean) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [ttsText, setTtsText] = useState("");
  const [provider, setProvider] = useState<Provider>("edge");
  const [voices, setVoices] = useState<TtsVoice[]>(initialVoices);
  const [voice, setVoice] = useState(initialVoices[0]?.id || "es-CO-SalomeNeural");
  const [whisperTtsText, setWhisperTtsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (provider === "edge") {
      setVoices(initialVoices);
      setVoice(initialVoices[0]?.id || "");
      return;
    }
    api
      .get<TtsVoice[]>(`/api/voicebots/tts/voices?provider=elevenlabs`)
      .then((vs) => {
        setVoices(vs);
        setVoice(vs[0]?.id || "");
      })
      .catch(() => setError("No se pudieron cargar las voces de ElevenLabs — revisa la API key en Ajustes"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  const uploadAudio = async (file: File, kind: "audio" | "whisper" = "audio") => {
    setBusy(true);
    setError("");
    try {
      const nodeKey = kind === "whisper" ? `${node.id}_whisper` : node.id;
      const res = await api.upload<{ path: string }>(`/api/voicebots/${botId}/flow/nodes/${nodeKey}/audio`, file);
      onChange(
        kind === "whisper"
          ? { whisper_audio_path: res.path, whisper_text: null }
          : { audio_path: res.path, tts_text: null },
        true
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al subir el audio");
    } finally {
      setBusy(false);
    }
  };

  const generateTts = async (kind: "audio" | "whisper" = "audio") => {
    const text = kind === "whisper" ? whisperTtsText : ttsText;
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ path: string }>(`/api/voicebots/${botId}/flow/nodes/${node.id}/tts`, {
        text,
        voice,
        kind,
        provider,
      });
      onChange(
        kind === "whisper"
          ? { whisper_audio_path: res.path, whisper_text: text }
          : { audio_path: res.path, tts_text: text },
        true
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar el audio");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-slide-left flex h-full w-80 shrink-0 flex-col overflow-y-auto border-l border-line bg-surface p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-semibold tracking-tight text-fg">
          {node.type === "menu"
            ? "Menú de audio"
            : node.type === "transfer"
              ? "Transferir llamada"
              : node.type === "horario"
                ? "Horario de atención"
                : "Colgar"}
        </h4>
        <IconButton label="Cerrar panel" onClick={onClose} className="h-8 w-8">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </IconButton>
      </div>

      {error && (
        <div className="mb-3">
          <Note tone="warn">{error}</Note>
        </div>
      )}

      <div className="space-y-3.5">
        <Input label="Nombre del nodo" value={node.data.label || ""} onChange={(v) => onChange({ label: v })} />

        {node.type === "horario" && (
          <>
            <Note tone="muted">
              Une la salida «Abierto» con lo que pasa en horario (por ejemplo, el menú) y «Cerrado» con lo que pasa fuera de él
              (un mensaje, un buzón o colgar).
            </Note>
            <EditorHorario value={node.data.horario} onChange={(v) => onChange({ horario: v })} />
          </>
        )}

        {(node.type === "menu" || node.type === "horario") && (
          <Check
            checked={!!node.data.start}
            onChange={(v) => onChange({ start: v })}
            label={<span className="text-xs">Es el nodo inicial (saludo)</span>}
          />
        )}

        {(node.type === "menu" || node.type === "hangup") && (
          <div className="rounded-xl border border-line bg-surface-2 p-3">
            <div className="mb-2 text-xs font-medium text-fg-soft">Audio</div>
            {node.data.audio_path && (
              <p className="mb-2 truncate rounded-lg bg-ok-soft px-2 py-1 text-[11px] text-ok-text">
                🎵 {node.data.audio_path.split("/").pop()}
              </p>
            )}
            <input
              type="file"
              accept=".wav,.mp3"
              className={`${fileInputClass} mb-2`}
              onChange={(e) => e.target.files?.[0] && uploadAudio(e.target.files[0])}
            />
            <Textarea
              value={ttsText}
              onChange={setTtsText}
              rows={2}
              placeholder="O escribe el texto para generar voz..."
            />
            <div className="my-2 grid grid-cols-2 gap-2">
              <Select
                label="Proveedor"
                value={provider}
                onChange={(v) => setProvider(v as Provider)}
                options={[
                  { value: "edge", label: "Gratis (edge-tts)" },
                  { value: "elevenlabs", label: "ElevenLabs" },
                ]}
              />
              <Select
                label="Voz"
                value={voice}
                onChange={setVoice}
                options={voices.map((v) => ({ value: v.id, label: v.label }))}
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => generateTts("audio")}
              loading={busy}
              disabled={!ttsText.trim()}
            >
              Generar voz
            </Button>
          </div>
        )}

        {node.type === "transfer" && (
          <>
            <Check
              checked={node.data.extension === "ai_agent"}
              onChange={(v) => onChange({ extension: v ? "ai_agent" : "" }, true)}
              label={
                <span className="text-xs">Transferir al voizbot con IA (agenda/reagenda/cancela citas por voz)</span>
              }
            />
            {node.data.extension !== "ai_agent" && (
              <>
                <Select
                  label="¿A dónde va la llamada?"
                  value={node.data.destino_tipo || "extension"}
                  onChange={(v) => onChange({ destino_tipo: v as FlowNode["data"]["destino_tipo"] })}
                  options={[
                    { value: "extension", label: "A una persona (su extensión)" },
                    { value: "grupo", label: "A un grupo de atención" },
                    { value: "buzon", label: "Al buzón de voz de una persona" },
                    { value: "numero", label: "A un número externo" },
                  ]}
                />
                <Input
                  label={
                    node.data.destino_tipo === "grupo"
                      ? "Número interno del grupo"
                      : node.data.destino_tipo === "numero"
                        ? "Número (sale por tus reglas de salida)"
                        : "Extensión"
                  }
                  value={node.data.extension || ""}
                  onChange={(v) => onChange({ extension: v })}
                  placeholder={node.data.destino_tipo === "grupo" ? "8000" : node.data.destino_tipo === "numero" ? "3001234567" : "1000"}
                  mono
                />
              </>
            )}
            {node.data.extension === "ai_agent" && (
              <>
                {/* Cada gestión es un guion distinto, con sus propias
                    herramientas. Elegirla acá evita que el bot pregunte
                    lo que la persona ya respondió con el teclado. */}
                <Select
                  label="¿Qué viene a resolver el bot?"
                  value={(node.data.ai_intent as string) || "general"}
                  onChange={(v) => onChange({ ai_intent: v }, true)}
                  options={[
                    { value: "confirmar", label: "Confirmar la cita" },
                    { value: "reagendar", label: "Reagendar la cita" },
                    { value: "cancelar", label: "Cancelar la cita" },
                    { value: "agendar", label: "Agendar una cita nueva" },
                    { value: "general", label: "Lo que la persona necesite" },
                  ]}
                  hint={AYUDA_GESTION[(node.data.ai_intent as string) || "general"]}
                />
                <Note tone="brand">Requiere configurar las API keys de voz y de DeepSeek en Ajustes.</Note>
              </>
            )}
            {(node.data.destino_tipo || "extension") === "extension" && node.data.extension !== "ai_agent" && (
            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <div className="mb-2 text-xs font-medium text-fg-soft">
                Aviso a la persona antes de conectar (opcional)
              </div>
              {node.data.whisper_audio_path && (
                <p className="mb-2 truncate rounded-lg bg-ok-soft px-2 py-1 text-[11px] text-ok-text">
                  🎵 {node.data.whisper_audio_path.split("/").pop()}
                </p>
              )}
              <input
                type="file"
                accept=".wav,.mp3"
                className={`${fileInputClass} mb-2`}
                onChange={(e) => e.target.files?.[0] && uploadAudio(e.target.files[0], "whisper")}
              />
              <Textarea
                value={whisperTtsText}
                onChange={setWhisperTtsText}
                rows={2}
                placeholder='Ej: "Cliente marcó la opción de soporte técnico"'
              />
              <div className="mt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => generateTts("whisper")}
                  loading={busy}
                  disabled={!whisperTtsText.trim()}
                >
                  Generar voz de aviso
                </Button>
              </div>
            </div>
            )}
          </>
        )}
      </div>

      <div className="mt-auto pt-4">
        <Button variant="danger" onClick={onDelete} className="w-full justify-center">
          Eliminar nodo
        </Button>
      </div>
    </div>
  );
}
