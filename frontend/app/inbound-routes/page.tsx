"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
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
import { EditorHorario } from "@/components/editor-horario";
import { api } from "@/lib/api";
import { Extension, InboundRoute, Queue, VoiceBot } from "@/lib/types";

type DestType = "extension" | "voicemail" | "queue" | "voicebot" | "buzon_remoto" | "hangup";

const empty: Omit<InboundRoute, "id" | "created_at"> = {
  name: "",
  did_pattern: "any",
  destination_type: "extension",
  destination_value: "",
  priority: 100, // «cualquier número» va al final (ver el formulario)
  enabled: true,
};

export default function InboundRoutesPage() {
  const [items, setItems] = useState<InboundRoute[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [queues, setQueues] = useState<Queue[]>([]);
  const [bots, setBots] = useState<VoiceBot[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<InboundRoute | null>(null);
  const [form, setForm] = useState(empty);
  const [destPick, setDestPick] = useState(""); // valor crudo elegido en el select (número o id)

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [routes, exts, qs, vbots] = await Promise.all([
        api.get<InboundRoute[]>("/api/inbound-routes"),
        api.get<Extension[]>("/api/extensions"),
        api.get<Queue[]>("/api/queues"),
        api.get<VoiceBot[]>("/api/voicebots"),
      ]);
      setItems(routes);
      setExtensions(exts);
      setQueues(qs);
      setBots(vbots);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar o al cambiar los filtros
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setDestPick("");
    setModal(true);
  };

  const openEdit = (r: InboundRoute) => {
    setEditing(r);
    setForm({ ...r, destination_value: r.destination_value ?? "" });
    setDestPick(r.destination_value ?? "");
    setModal(true);
  };

  const destOptions = (type: DestType) => {
    if (type === "voicemail")
      return extensions
        .filter((e) => e.voicemail)
        .map((e) => ({ value: e.number, label: `${e.number} — ${e.caller_id_name || "sin nombre"}` }));
    if (type === "extension")
      return extensions.map((e) => ({ value: e.number, label: `${e.number} — ${e.caller_id_name || "sin nombre"}` }));
    if (type === "queue") return queues.map((q) => ({ value: q.extension, label: `${q.extension} — ${q.name}` }));
    if (type === "voicebot") return bots.map((b) => ({ value: `bot_${b.id}`, label: b.name }));
    return [];
  };

  // `saving` no es solo un spinner: sin él, el botón quedaba activo
  // mientras el POST viajaba y un doble clic creaba la ruta DOS veces.
  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const payload = {
        ...form,
        destination_value: form.destination_type === "hangup" || form.destination_type === "buzon_remoto" ? null : destPick || null,
        horario: form.horario || null,
        fuera_horario_tipo: form.horario ? form.fuera_horario_tipo || "hangup" : null,
        fuera_horario_valor:
          form.horario && form.fuera_horario_tipo && form.fuera_horario_tipo !== "hangup" ? form.fuera_horario_valor || null : null,
      };
      if (editing) {
        await api.put(`/api/inbound-routes/${editing.id}`, payload);
      } else {
        await api.post("/api/inbound-routes", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (r: InboundRoute) => {
    if (!confirm(`¿Eliminar el número entrante ${r.name}? Las llamadas a ese número dejarán de entrar.`)) return;
    try {
      await api.del(`/api/inbound-routes/${r.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const destLabel = (r: InboundRoute) => {
    if (r.destination_type === "hangup") return "Colgar";
    if (r.destination_type === "buzon_remoto") return "Escuchar el buzón (con PIN)";
    if (r.destination_type === "extension") {
      const ext = extensions.find((e) => e.number === r.destination_value);
      return `Ext. ${r.destination_value}${ext?.caller_id_name ? ` (${ext.caller_id_name})` : ""}`;
    }
    if (r.destination_type === "voicemail") {
      const ext = extensions.find((e) => e.number === r.destination_value);
      return `Buzón de ${ext?.caller_id_name || `la ext. ${r.destination_value}`}`;
    }
    if (r.destination_type === "queue") {
      const q = queues.find((q) => q.extension === r.destination_value);
      return `Cola ${q?.name ?? r.destination_value}`;
    }
    if (r.destination_type === "voicebot") {
      const b = bots.find((b) => `bot_${b.id}` === r.destination_value);
      return `Voizbot ${b?.name ?? r.destination_value}`;
    }
    return r.destination_value ?? "—";
  };

  return (
    <div>
      <PageHeader
        title="Números entrantes"
        subtitle="A dónde va una llamada cuando alguien marca tu número: a una persona, a un grupo o al voizbot. Término técnico: rutas entrantes por DID."
        actions={<Button guia="entrantes:nuevo" onClick={openCreate}>+ Configurar número</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader
          title="Tus números"
          subtitle={`${items.length} configurado(s). Si una llamada coincide con varios, gana el de menor prioridad.`}
        />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Todavía no recibes llamadas"
            hint="Mientras no configures un número, las llamadas que entran por tu proveedor se cuelgan solas. Lo más simple: «cualquier número» → una persona o un grupo."
            action={<Button onClick={openCreate}>+ Configurar número</Button>}
          />
        ) : (
          <Table head={["Prioridad", "Nombre", "Número", "Va a", "Estado", { label: "Acciones", align: "right" }]}>
            {items.map((r, i) => (
              <Tr key={r.id} delay={i * 35}>
                <Td mono muted>
                  {r.priority}
                </Td>
                <Td>
                  {r.name}
                  {r.horario && (
                    <span className="ml-2" title="Fuera del horario de atención va a otro destino">
                      <Badge color="sky">Con horario</Badge>
                    </span>
                  )}
                </Td>
                <Td mono strong>
                  {r.did_pattern === "any" ? <Badge color="violet">Cualquiera</Badge> : r.did_pattern}
                </Td>
                <Td>{destLabel(r)}</Td>
                <Td>
                  {r.enabled ? (
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
                    <Button size="sm" variant="secondary" onClick={() => openEdit(r)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(r)}>
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
        title={editing ? `Editar número ${editing.name}` : "Configurar número entrante"}
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
          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">Cuando llamen a…</span>
            <div className="grid grid-cols-2 gap-2">
              {[
                { todos: true, titulo: "Cualquier número", detalle: "Todas las llamadas que entran por tus proveedores." },
                { todos: false, titulo: "Un número específico", detalle: "Si tienes varios números y cada uno va a un lugar." },
              ].map((o) => {
                const activo = (form.did_pattern.trim().toLowerCase() === "any") === o.todos;
                return (
                  <button
                    key={o.titulo}
                    type="button"
                    aria-pressed={activo}
                    onClick={() =>
                      setForm(
                        o.todos
                          // El comodín va al final: los números específicos ganan primero.
                          ? { ...form, did_pattern: "any", priority: Math.max(form.priority, 100) }
                          : { ...form, did_pattern: form.did_pattern === "any" ? "" : form.did_pattern, priority: form.priority >= 100 ? 10 : form.priority }
                      )
                    }
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      activo ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                    }`}
                  >
                    <span className="block text-sm font-semibold text-fg">{o.titulo}</span>
                    <span className="mt-0.5 block text-xs text-muted">{o.detalle}</span>
                  </button>
                );
              })}
            </div>
          </div>
          {form.did_pattern.trim().toLowerCase() !== "any" && (
            <Input
              label="Tu número"
              value={form.did_pattern}
              onChange={(v) => setForm({ ...form, did_pattern: v })}
              placeholder="6017654321"
              hint="Tu número con o sin +57 (técnico: DID): da igual cómo lo mande el proveedor. Si no estás seguro, usa «Cualquier número»."
              required
              mono
            />
          )}
          <Select
            label="…la llamada va a"
            value={form.destination_type}
            onChange={(v) => {
              setForm({ ...form, destination_type: v as DestType });
              setDestPick("");
            }}
            options={[
              { value: "extension", label: "Una persona (su extensión)" },
              { value: "voicemail", label: "El buzón de voz de una persona (deja un mensaje)" },
              { value: "queue", label: "Un grupo de atención (suena en varias personas)" },
              { value: "voicebot", label: "El voizbot (contesta solo)" },
              { value: "buzon_remoto", label: "Escuchar mensajes del buzón (pide extensión y PIN)" },
              { value: "hangup", label: "Colgar" },
            ]}
          />
          {form.destination_type !== "hangup" && form.destination_type !== "buzon_remoto" && (
            <Select
              label={form.destination_type === "queue" ? "¿Qué grupo?" : form.destination_type === "voicebot" ? "¿Qué voizbot?" : form.destination_type === "voicemail" ? "¿El buzón de quién?" : "¿Quién?"}
              value={destPick}
              onChange={setDestPick}
              placeholder="— Elige —"
              options={destOptions(form.destination_type as DestType)}
            />
          )}
          <div className="rounded-xl border border-line p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-fg-soft">
                Solo en horario de atención
                <span className="mt-0.5 block text-xs text-faint">Fuera de él, la llamada va a otro lado (o se cuelga).</span>
              </span>
              <Toggle
                checked={!!form.horario}
                onChange={(v) =>
                  setForm({
                    ...form,
                    horario: v ? JSON.stringify(Object.fromEntries(["mon", "tue", "wed", "thu", "fri"].map((d) => [d, ["08:00", "18:00"]]))) : null,
                  })
                }
              />
            </div>
            {form.horario && (
              <div className="mt-3 space-y-3">
                <EditorHorario value={form.horario} onChange={(v) => setForm({ ...form, horario: v })} />
                <Select
                  label="Fuera de horario, la llamada va a"
                  value={form.fuera_horario_tipo || "hangup"}
                  onChange={(v) => setForm({ ...form, fuera_horario_tipo: v as DestType, fuera_horario_valor: "" })}
                  options={[
                    { value: "hangup", label: "Colgar" },
                    { value: "voicemail", label: "Un buzón de voz (dejan un mensaje)" },
                    { value: "voicebot", label: "El voizbot (puede tomar el recado)" },
                    { value: "extension", label: "Una persona (por ejemplo, de guardia)" },
                    { value: "queue", label: "Un grupo de atención" },
                  ]}
                />
                {form.fuera_horario_tipo && form.fuera_horario_tipo !== "hangup" && (
                  <Select
                    label="¿A cuál?"
                    value={form.fuera_horario_valor ?? ""}
                    onChange={(v) => setForm({ ...form, fuera_horario_valor: v })}
                    placeholder="— Elige —"
                    options={destOptions(form.fuera_horario_tipo as DestType)}
                  />
                )}
              </div>
            )}
          </div>
          <Input
            label="Nombre"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="Línea principal"
            hint="Solo para reconocerlo en la lista."
            required
          />
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Activo</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
          <details className="rounded-xl border border-line">
            <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium text-fg-soft">Opciones avanzadas</summary>
            <div className="space-y-4 border-t border-line p-3">
              <Input
                label="Prioridad"
                type="number"
                value={form.priority}
                onChange={(v) => setForm({ ...form, priority: Number(v) })}
                hint="Si una llamada coincide con varios números configurados, gana el de número más bajo. «Cualquier número» va con 100 para quedar al final."
              />
            </div>
          </details>
        </div>
      </Modal>
    </div>
  );
}
