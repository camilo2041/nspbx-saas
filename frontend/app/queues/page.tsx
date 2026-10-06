"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Check,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  PageHeader,
  RowActions,
  Select,
  Table,
  TableSkeleton,
  Td,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, Queue, VoiceBot } from "@/lib/types";

const STRATEGIES = [
  { value: "ring-all", label: "Suena en todos a la vez (recomendado)" },
  { value: "longest-idle-agent", label: "Al que lleva más tiempo libre" },
  { value: "round-robin", label: "Por turnos" },
  { value: "top-down", label: "Orden de la lista (de arriba a abajo)" },
  { value: "sequentially-by-agent-order", label: "Secuencial por orden de agente" },
  { value: "agent-with-least-talk-time", label: "Agente con menos tiempo hablado" },
  { value: "agent-with-fewest-calls", label: "Agente con menos llamadas" },
  { value: "random", label: "Aleatorio" },
];

type Desborde = "hangup" | "extension" | "voicemail" | "queue" | "voicebot" | "otro";
const PREFIJO_BUZON = "*99";
const PREFIJO_BOT = "bot_";

/** Qué hay en `failover_extension`: *99<ext> es el buzón de esa extensión. */
function tipoDesborde(valor: string | null | undefined, extensiones: Extension[], colas: Queue[]): Desborde {
  if (!valor) return "hangup";
  if (valor.startsWith(PREFIJO_BUZON)) return "voicemail";
  if (valor.startsWith(PREFIJO_BOT)) return "voicebot";
  if (extensiones.some((e) => e.number === valor)) return "extension";
  if (colas.some((q) => q.extension === valor)) return "queue";
  return "otro";
}

function valorDesborde(valor: string | null | undefined): string {
  return valor?.startsWith(PREFIJO_BUZON) ? valor.slice(PREFIJO_BUZON.length) : (valor ?? "");
}

const empty: Omit<Queue, "id" | "created_at"> = {
  name: "",
  extension: "",
  strategy: "ring-all",
  moh_sound: "$${hold_music}",
  agents: [],
  max_wait_time: 0,
  max_wait_time_with_no_agent: 0,
  agent_ring_timeout: 20,
  max_no_answer: 3,
  wrap_up_time: 10,
  record: false,
  failover_extension: "",
  announce_position: false,
  enabled: true,
};

export default function QueuesPage() {
  const [items, setItems] = useState<Queue[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Queue | null>(null);
  const [form, setForm] = useState(empty);
  const [bots, setBots] = useState<VoiceBot[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [qs, exts] = await Promise.all([
        api.get<Queue[]>("/api/queues"),
        api.get<Extension[]>("/api/extensions"),
      ]);
      setItems(qs);
      setExtensions(exts);
      setError("");
      // Los voizbots son opcionales (módulo aparte): sin acceso, la lista queda vacía.
      api.get<VoiceBot[]>("/api/voicebots").then(setBots, () => setBots([]));
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
    setModal(true);
  };

  const openEdit = (q: Queue) => {
    setEditing(q);
    setForm({ ...q, failover_extension: q.failover_extension ?? "" });
    setModal(true);
  };

  // Ver el mismo caso en inbound-routes: sin `saving`, un doble clic
  // creaba la cola dos veces (y una cola duplicada además reescribe la
  // config de FreeSWITCH, así que no era solo una fila de más).
  const save = async () => {
    if (saving) return;
    if (form.failover_extension === PREFIJO_BUZON) {
      setError("Elige de quién es el buzón al que van las llamadas que nadie contesta.");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, failover_extension: form.failover_extension || null };
      if (editing) {
        await api.put(`/api/queues/${editing.id}`, payload);
      } else {
        await api.post("/api/queues", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const desbordeLabel = (q: Queue) => {
    const tipo = tipoDesborde(q.failover_extension, extensions, items);
    const v = valorDesborde(q.failover_extension);
    const nombre = (n: string) => extensions.find((e) => e.number === n)?.caller_id_name;
    const espera = q.max_wait_time > 0 ? ` (a los ${q.max_wait_time} s)` : "";
    if (tipo === "hangup") return "Cuelga";
    if (tipo === "voicemail") return `Buzón de ${nombre(v) || `la ${v}`}${espera}`;
    if (tipo === "extension") return `${nombre(v) || `Ext. ${v}`}${espera}`;
    if (tipo === "queue") return `Grupo ${items.find((x) => x.extension === v)?.name ?? v}${espera}`;
    if (tipo === "voicebot") return `Voizbot ${bots.find((b) => `${PREFIJO_BOT}${b.id}` === v)?.name ?? v}${espera}`;
    return `${v}${espera}`;
  };

  // Personas de este grupo que están también en otros (sus tiempos se combinan).
  const compartidas = form.agents
    .map((n) => ({
      persona: extensions.find((e) => e.number === n)?.caller_id_name || n,
      grupos: items.filter((q) => q.id !== editing?.id && q.enabled && q.agents.includes(n)).map((q) => q.name),
    }))
    .filter((c) => c.grupos.length > 0);

  const tipoForm = tipoDesborde(form.failover_extension, extensions, items);
  const cambiarDesborde = (tipo: Desborde, valor = "") => {
    // Al cambiar de tipo sin elegir todavía, el primero de la lista (un valor
    // vacío se leería como «Colgar» y el selector volvería atrás).
    if (!valor) {
      if (tipo === "voicebot") valor = bots[0] ? `${PREFIJO_BOT}${bots[0].id}` : "";
      if (tipo === "queue") valor = items.find((q) => q.id !== editing?.id)?.extension ?? "";
      if (tipo === "extension") valor = extensions[0]?.number ?? "";
    }
    setForm({
      ...form,
      failover_extension: tipo === "hangup" ? "" : tipo === "voicemail" ? (valor ? `${PREFIJO_BUZON}${valor}` : PREFIJO_BUZON) : valor,
    });
  };

  const remove = async (q: Queue) => {
    if (!confirm(`¿Eliminar la cola ${q.name}?`)) return;
    try {
      await api.del(`/api/queues/${q.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const toggleAgent = (number: string) => {
    setForm((f) => ({
      ...f,
      agents: f.agents.includes(number) ? f.agents.filter((a) => a !== number) : [...f.agents, number],
    }));
  };

  const strategyLabel = (value: string) => STRATEGIES.find((s) => s.value === value)?.label ?? value;

  return (
    <div>
      <PageHeader
        title="Grupos de atención"
        subtitle="Varias personas que atienden las mismas llamadas (ventas, soporte…): la llamada suena en el grupo y la toma quien esté libre. Término técnico: colas."
        actions={<Button onClick={openCreate}>+ Nuevo grupo</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Tus grupos" subtitle={`${items.length} grupo(s)`} />
        {loading ? (
          <TableSkeleton cols={7} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Todavía no hay grupos"
            hint="Crea uno para que las llamadas de tu número suenen en varias personas. Luego, en Números entrantes, envía tu número a este grupo."
            action={<Button onClick={openCreate}>+ Nuevo grupo</Button>}
          />
        ) : (
          <Table
            head={[
              "Número interno",
              "Nombre",
              "Cómo suena",
              "Personas",
              "Si nadie contesta",
              "Estado",
              { label: "Acciones", align: "right" },
            ]}
          >
            {items.map((q, i) => (
              <Tr key={q.id} delay={i * 35}>
                <Td mono strong>
                  {q.extension}
                </Td>
                <Td>{q.name}</Td>
                <Td>{strategyLabel(q.strategy)}</Td>
                <Td>
                  <Badge color="indigo">{q.agents.length}</Badge>
                </Td>
                <Td muted>{desbordeLabel(q)}</Td>
                <Td>
                  {q.enabled ? (
                    <Badge color="green" dot>
                      Activa
                    </Badge>
                  ) : (
                    <Badge color="red" dot>
                      Inactiva
                    </Badge>
                  )}
                </Td>
                <Td align="right">
                  <RowActions>
                    <Button size="sm" variant="secondary" onClick={() => openEdit(q)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(q)}>
                      Eliminar
                    </Button>
                  </RowActions>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar grupo ${editing.name}` : "Nuevo grupo de atención"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save} loading={saving}>
              {editing ? "Guardar" : "Crear"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="Nombre del grupo"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="ventas, soporte…"
            hint="Sin espacios ni tildes: letras, números, punto, guion."
            required
          />

          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">
              ¿Quiénes atienden? {form.agents.length > 0 && <span className="text-brand-text">({form.agents.length})</span>}
            </span>
            <div className="max-h-44 overflow-y-auto rounded-xl border border-line bg-surface-2 p-1.5">
              {extensions.length === 0 ? (
                <p className="px-2 py-2 text-xs text-faint">
                  Todavía no hay extensiones: crea una por persona en Central telefónica → Extensiones.
                </p>
              ) : (
                extensions.map((ext) => (
                  <Check
                    key={ext.id}
                    checked={form.agents.includes(ext.number)}
                    onChange={() => toggleAgent(ext.number)}
                    label={
                      <span className="flex items-baseline gap-2">
                        <span className="font-mono">{ext.number}</span>
                        {ext.caller_id_name && <span className="text-xs text-muted">— {ext.caller_id_name}</span>}
                      </span>
                    }
                  />
                ))
              )}
            </div>
          </div>

          <Select
            label="¿Cómo suena?"
            value={form.strategy}
            onChange={(v) => setForm({ ...form, strategy: v })}
            options={STRATEGIES}
          />

          <div className="space-y-3 rounded-xl border border-line p-3">
            <Select
              label="Si nadie contesta, la llamada va a"
              value={tipoForm === "otro" ? "extension" : tipoForm}
              onChange={(v) => cambiarDesborde(v as Desborde)}
              options={[
                { value: "voicemail", label: "El buzón de voz de una persona (deja un mensaje)" },
                { value: "extension", label: "Una persona" },
                { value: "queue", label: "Otro grupo" },
                ...(bots.length || tipoForm === "voicebot" ? [{ value: "voicebot", label: "Un voizbot (asistente de voz)" }] : []),
                { value: "hangup", label: "Colgar" },
              ]}
            />
            {tipoForm !== "hangup" && (
              <Select
                label={
                  tipoForm === "queue"
                    ? "¿Qué grupo?"
                    : tipoForm === "voicebot"
                      ? "¿Qué voizbot?"
                      : tipoForm === "voicemail"
                        ? "¿El buzón de quién?"
                        : "¿Quién?"
                }
                value={valorDesborde(form.failover_extension)}
                onChange={(v) => cambiarDesborde(tipoForm === "otro" ? "extension" : tipoForm, v)}
                placeholder="— Elige —"
                options={
                  tipoForm === "queue"
                    ? items
                        .filter((q) => q.id !== editing?.id)
                        .map((q) => ({ value: q.extension, label: `${q.extension} — ${q.name}` }))
                    : tipoForm === "voicebot"
                      ? bots.map((b) => ({ value: `${PREFIJO_BOT}${b.id}`, label: b.name }))
                      : extensions
                        .filter((e) => tipoForm !== "voicemail" || e.voicemail)
                        .map((e) => ({ value: e.number, label: `${e.number} — ${e.caller_id_name || "sin nombre"}` }))
                }
              />
            )}
            <Input
              label="Si nadie contesta en (segundos)"
              type="number"
              value={form.max_wait_time}
              onChange={(v) => setForm({ ...form, max_wait_time: Number(v) })}
              hint={
                form.max_wait_time > 0
                  ? `A los ${form.max_wait_time} s de espera la llamada sale del grupo.`
                  : "0 = espera sin límite mientras haya alguien conectado. Recomendado: 60."
              }
            />
          </div>

          <Input
            label="Número interno del grupo"
            value={form.extension}
            onChange={(v) => setForm({ ...form, extension: v })}
            placeholder="8000"
            hint="Para transferir llamadas al grupo desde un teléfono. Que no sea el de una extensión."
            required
            mono
          />

          <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">
              Decirle a quien espera cuántas personas tiene antes
              <span className="block text-xs text-muted">
                Al entrar al grupo. Mientras espera oye música y, cada 30 s, «Gracias por esperar».
              </span>
            </span>
            <Toggle checked={form.announce_position} onChange={(v) => setForm({ ...form, announce_position: v })} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Grabar las llamadas del grupo</span>
            <Toggle checked={form.record} onChange={(v) => setForm({ ...form, record: v })} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Activo</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>

          <details className="rounded-xl border border-line">
            <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium text-fg-soft">
              Opciones avanzadas <span className="text-xs font-normal text-muted">(tiempos de espera y timbre)</span>
            </summary>
            <div className="grid grid-cols-2 gap-3 border-t border-line p-3">
              {compartidas.length > 0 && (
                <p className="col-span-2 rounded-lg bg-surface-2 px-3 py-2 text-xs text-fg-soft">
                  {compartidas.map((c) => `${c.persona} también está en ${c.grupos.join(", ")}`).join(". ")}. A una persona
                  que está en varios grupos se le aplica el valor más alto de estos tres tiempos entre todos sus grupos.
                </p>
              )}
              <Input
                label="Segundos que suena en cada persona"
                type="number"
                value={form.agent_ring_timeout}
                onChange={(v) => setForm({ ...form, agent_ring_timeout: Number(v) })}
              />
              <Input
                label="Llamadas sin contestar antes de pausar a la persona"
                type="number"
                value={form.max_no_answer}
                onChange={(v) => setForm({ ...form, max_no_answer: Number(v) })}
              />
              <Input
                label="Espera máxima si no hay nadie conectado (seg)"
                type="number"
                value={form.max_wait_time_with_no_agent}
                onChange={(v) => setForm({ ...form, max_wait_time_with_no_agent: Number(v) })}
                hint="0 = sin límite."
              />
              <Input
                label="Descanso tras cada llamada (seg)"
                type="number"
                value={form.wrap_up_time}
                onChange={(v) => setForm({ ...form, wrap_up_time: Number(v) })}
              />
            </div>
          </details>
        </div>
      </Modal>
    </div>
  );
}
