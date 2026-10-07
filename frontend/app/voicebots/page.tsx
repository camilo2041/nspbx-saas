"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  Note,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  Textarea,
  Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, TtsVoice, VoiceBot } from "@/lib/types";

const empty: Omit<VoiceBot, "id" | "created_at"> = {
  name: "",
  bot_type: "ivr",
  welcome_message: "",
  config: "",
  greeting_audio_path: null,
  flow_json: null,
  enabled: true,
};

interface MenuRow {
  digit: string;
  target: string;
}

function parseMenu(configJson: string | null | undefined): MenuRow[] {
  if (!configJson) return [];
  try {
    const data = JSON.parse(configJson);
    const menu = data?.menu;
    if (!menu || typeof menu !== "object") return [];
    return Object.entries(menu).map(([digit, target]) => ({ digit, target: String(target) }));
  } catch {
    return [];
  }
}

function serializeMenu(rows: MenuRow[]): string {
  const menu: Record<string, string> = {};
  for (const row of rows) {
    if (row.digit && row.target) menu[row.digit] = row.target;
  }
  return JSON.stringify({ menu });
}

export default function VoicebotsPage() {
  const router = useRouter();
  const [items, setItems] = useState<VoiceBot[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<VoiceBot | null>(null);
  const [form, setForm] = useState(empty);
  const [menuRows, setMenuRows] = useState<MenuRow[]>([]);
  const [reloading, setReloading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [ttsText, setTtsText] = useState("");
  const [ttsVoice, setTtsVoice] = useState("es-CO-SalomeNeural");
  const [ttsProvider, setTtsProvider] = useState<"edge" | "elevenlabs">("edge");
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (ttsProvider === "edge") {
      api.get<TtsVoice[]>("/api/voicebots/tts/voices").then((vs) => {
        setVoices(vs);
        setTtsVoice(vs[0]?.id || "");
      });
      return;
    }
    api
      .get<TtsVoice[]>("/api/voicebots/tts/voices?provider=elevenlabs")
      .then((vs) => {
        setVoices(vs);
        setTtsVoice(vs[0]?.id || "");
      })
      .catch(() => setError("No se pudieron cargar las voces de ElevenLabs — revisa la API key en Ajustes"));
  }, [ttsProvider]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bots, exts] = await Promise.all([
        api.get<VoiceBot[]>("/api/voicebots"),
        api.get<Extension[]>("/api/extensions"),
      ]);
      setItems(bots);
      setExtensions(exts);
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

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setMenuRows([]);
    setModal(true);
  };

  const openEdit = (bot: VoiceBot) => {
    setEditing(bot);
    setForm({ ...bot });
    setMenuRows(parseMenu(bot.config));
    setModal(true);
  };

  const closeModal = async () => {
    setModal(false);
    await load();
  };

  const save = async () => {
    try {
      const payload = {
        ...form,
        config: menuRows.length ? serializeMenu(menuRows) : null,
        welcome_message: form.welcome_message || null,
      };
      if (editing) {
        await api.put(`/api/voicebots/${editing.id}`, payload);
      } else {
        const created = await api.post<VoiceBot>("/api/voicebots", payload);
        setEditing(created);
        setForm({ ...created });
        await load();
        return; // deja el modal abierto para poder subir el audio del saludo
      }
      await closeModal();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    }
  };

  const remove = async (bot: VoiceBot) => {
    if (!confirm(`¿Eliminar el voizbot ${bot.name}?`)) return;
    try {
      await api.del(`/api/voicebots/${bot.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const reload = async () => {
    setReloading(true);
    try {
      await api.post<{ ok: boolean }>("/api/voicebots/reload");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al recargar");
    } finally {
      setReloading(false);
    }
  };

  const uploadGreeting = async (file: File) => {
    if (!editing) return;
    setUploading(true);
    try {
      const updated = await api.upload<VoiceBot>(`/api/voicebots/${editing.id}/greeting`, file);
      setEditing(updated);
      setForm({ ...updated });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al subir el audio");
    } finally {
      setUploading(false);
    }
  };

  const generateTts = async () => {
    if (!editing || !ttsText.trim()) return;
    setGenerating(true);
    try {
      const updated = await api.post<VoiceBot>(`/api/voicebots/${editing.id}/tts`, {
        text: ttsText,
        voice: ttsVoice,
        provider: ttsProvider,
      });
      setEditing(updated);
      setForm({ ...updated });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar el audio");
    } finally {
      setGenerating(false);
    }
  };

  const removeGreeting = async () => {
    if (!editing) return;
    try {
      const updated = await api.del<VoiceBot>(`/api/voicebots/${editing.id}/greeting`);
      setEditing(updated);
      setForm({ ...updated });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al quitar el audio");
    }
  };

  const addMenuRow = () => setMenuRows([...menuRows, { digit: "", target: "" }]);
  const updateMenuRow = (i: number, patch: Partial<MenuRow>) =>
    setMenuRows(menuRows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const removeMenuRow = (i: number) => setMenuRows(menuRows.filter((_, idx) => idx !== i));

  const fileInputClass =
    "block w-full cursor-pointer text-xs text-muted file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-on-brand hover:file:brightness-110";

  return (
    <div>
      <PageHeader
        title="Voizbots"
        subtitle="IVR con menú de teclas (DTMF) y flujos de audio"
        actions={
          <>
            <Button variant="secondary" onClick={reload} loading={reloading}>
              {reloading ? "Recargando…" : "Recargar en FreeSWITCH"}
            </Button>
            <Button guia="voizbots:nuevo" onClick={openCreate}>+ Nuevo voizbot</Button>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 rounded-2xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            title="No hay voizbots"
            hint="Crea el primero para atender llamadas con un menú de audio."
            action={<Button onClick={openCreate}>+ Nuevo voizbot</Button>}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {items.map((bot, i) => (
            <Card key={bot.id} hover delay={i * 60} className="flex h-full flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate text-base font-semibold tracking-tight text-fg">{bot.name}</h3>
                    {bot.bot_type === "ivr" ? <Badge color="indigo">IVR</Badge> : <Badge color="violet">IA</Badge>}
                  </div>
                  <p className="mt-1.5 text-xs text-muted">
                    Marca <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-fg-soft">bot_{bot.id}</span>{" "}
                    desde una extensión para probarlo
                  </p>
                  {bot.welcome_message && (
                    <p className="mt-1.5 line-clamp-2 text-xs italic text-faint">&ldquo;{bot.welcome_message}&rdquo;</p>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  {bot.enabled ? (
                    <Badge color="green" dot>
                      Activo
                    </Badge>
                  ) : (
                    <Badge color="red" dot>
                      Inactivo
                    </Badge>
                  )}
                  {bot.greeting_audio_path && <Badge color="blue">Audio propio</Badge>}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
                <Button guia="voizbot:flujo" onClick={() => router.push(`/voicebots/${bot.id}/flow`)}>Editar flujo</Button>
                <Button variant="secondary" onClick={() => openEdit(bot)}>
                  Editar
                </Button>
                <Button variant="danger" onClick={() => remove(bot)}>
                  Eliminar
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={modal}
        onClose={closeModal}
        title={editing ? `Editar voizbot ${editing.name}` : "Nuevo voizbot"}
        footer={
          <>
            <Button variant="secondary" onClick={closeModal}>
              Cerrar
            </Button>
            <Button onClick={save}>{editing ? "Guardar" : "Crear"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />

          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">Tipo</span>
            <Segmented
              value={form.bot_type}
              onChange={(v) => setForm({ ...form, bot_type: v })}
              options={[
                { value: "ivr", label: "IVR (menú DTMF)" },
                { value: "ai", label: "IA (próximamente)", disabled: true, title: "Motor de IA aún no disponible" },
              ]}
            />
          </div>

          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">Audio de saludo (WAV o MP3)</span>
            {editing ? (
              <div className="space-y-3">
                {editing.greeting_audio_path ? (
                  <div className="flex items-center justify-between gap-2 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-xs">
                    <span className="truncate text-fg-soft">🎵 {editing.greeting_audio_path.split("/").pop()}</span>
                    <button
                      type="button"
                      onClick={removeGreeting}
                      className="shrink-0 font-medium text-danger-text hover:underline"
                    >
                      Quitar
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-faint">
                    Sin audio propio — si no subes uno, se usa el mensaje de bienvenida leído por voz sintética.
                  </p>
                )}
                <input
                  type="file"
                  accept=".wav,.mp3,audio/wav,audio/mpeg"
                  disabled={uploading}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadGreeting(file);
                    e.target.value = "";
                  }}
                  className={fileInputClass}
                />
                {uploading && <p className="text-xs text-muted">Subiendo…</p>}

                <div className="rounded-xl border border-dashed border-line-strong bg-surface-2 p-3.5">
                  <span className="mb-2 block text-xs font-medium text-fg-soft">
                    O genera el audio con voz sintética
                  </span>
                  <div className="space-y-2.5">
                    <Textarea
                      value={ttsText}
                      onChange={setTtsText}
                      rows={3}
                      placeholder="Escribe aquí el texto del saludo…"
                    />
                    <div className="grid grid-cols-2 gap-2">
                      <Select
                        label="Proveedor"
                        value={ttsProvider}
                        onChange={(v) => setTtsProvider(v as "edge" | "elevenlabs")}
                        options={[
                          { value: "edge", label: "Gratis (edge-tts)" },
                          { value: "elevenlabs", label: "ElevenLabs" },
                        ]}
                      />
                      <Select
                        label="Voz"
                        value={ttsVoice}
                        onChange={setTtsVoice}
                        options={voices.map((v) => ({ value: v.id, label: v.label }))}
                      />
                    </div>
                    <Button variant="secondary" onClick={generateTts} loading={generating} disabled={!ttsText.trim()}>
                      {generating ? "Generando…" : "Generar y usar como saludo"}
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <Note tone="muted">Crea el voizbot primero; luego podrás subir el audio aquí mismo.</Note>
            )}
          </div>

          <Input
            label="Mensaje de bienvenida (respaldo por voz sintética)"
            value={form.welcome_message ?? ""}
            onChange={(v) => setForm({ ...form, welcome_message: v })}
            placeholder="Ej. Bienvenido a NSPBX"
            hint="Se usa solo si no subes un audio propio arriba"
          />

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium text-fg-soft">Menú (tecla → extensión)</span>
              <button
                type="button"
                onClick={addMenuRow}
                className="text-xs font-medium text-brand-text hover:underline"
              >
                + Agregar opción
              </button>
            </div>
            {menuRows.length === 0 ? (
              <p className="text-xs text-faint">
                Sin opciones: la llamada se cuelga tras el saludo. Agrega al menos una tecla para enrutar.
              </p>
            ) : (
              <div className="space-y-2">
                {menuRows.map((row, i) => (
                  <div key={i} className="animate-fade-up flex items-end gap-2">
                    <input
                      value={row.digit}
                      onChange={(e) => updateMenuRow(i, { digit: e.target.value.slice(0, 1) })}
                      placeholder="1"
                      maxLength={1}
                      className="w-14 shrink-0 rounded-xl border border-line bg-surface-2 px-2 py-2 text-center font-mono text-sm text-fg outline-none transition-all focus:border-brand focus:bg-surface focus:ring-4 focus:ring-brand/15"
                    />
                    <span className="pb-2 text-faint">→</span>
                    <div className="flex-1">
                      <Select
                        label=""
                        value={row.target}
                        onChange={(v) => updateMenuRow(i, { target: v })}
                        placeholder="— Elige una extensión —"
                        options={extensions.map((e) => ({
                          value: e.number,
                          label: `${e.number}${e.caller_id_name ? ` — ${e.caller_id_name}` : ""}`,
                        }))}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => removeMenuRow(i)}
                      aria-label="Quitar opción"
                      className="press mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-danger-text transition-colors hover:bg-danger-soft"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                        <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitado</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
        </div>
      </Modal>
    </div>
  );
}
