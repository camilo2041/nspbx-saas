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
  Table,
  TableSkeleton,
  Td,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { OutboundRoute, Trunk } from "@/lib/types";

const empty: Omit<OutboundRoute, "id" | "created_at"> = {
  name: "",
  pattern: "",
  strip_digits: 0,
  prepend: "",
  trunk_ids: "",
  allow_international: false,
  priority: 10,
  enabled: true,
};

/** Ejemplo de qué marca la regla, calculado en vivo mientras se escribe.
 *
 * No es decoración: el error caro acá es silencioso —una regla que atrapa
 * de más manda llamadas por la troncal equivocada, y una que normaliza mal
 * las hace fallar sin decir por qué—. Ver el número resultante antes de
 * guardar es lo que evita descubrirlo en la factura. */
function ejemplo(pattern: string, strip: number, prepend: string): string {
  const simbolos: string[] = [];
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "[") {
      const fin = pattern.indexOf("]", i);
      if (fin < 0) return "patrón incompleto";
      simbolos.push(pattern[i + 1] ?? "1");
      i = fin;
    } else if (c === "X") simbolos.push("5");
    else if (c === "Z") simbolos.push("3");
    else if (c === "N") simbolos.push("7");
    else if (c === ".") simbolos.push("123");
    else simbolos.push(c);
  }
  if (!simbolos.length) return "";
  if (strip >= simbolos.length) return "quitás más dígitos de los que tiene el patrón";
  const marcado = simbolos.join("");
  const sale = prepend + simbolos.slice(strip).join("");
  return `marcando ${marcado} sale ${sale}`;
}

// Plantillas del plan de numeración de Colombia (desde 2021 los fijos son de
// 10 dígitos con indicativo 60X). Las cifras a quitar o anteponer dependen
// del proveedor: se dejan en cero y se ajustan en «Opciones avanzadas».
const PLANTILLAS = [
  { name: "Celulares Colombia", pattern: "3XXXXXXXXX", detalle: "10 dígitos, empiezan por 3" },
  { name: "Fijos Colombia", pattern: "60XXXXXXXX", detalle: "601… a 608…, 10 dígitos" },
  { name: "Líneas 01 8000", pattern: "018000XXXXXX", detalle: "Gratuitas nacionales" },
];

export default function OutboundRoutesPage() {
  const [items, setItems] = useState<OutboundRoute[]>([]);
  const [trunks, setTrunks] = useState<Trunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<OutboundRoute | null>(null);
  const [form, setForm] = useState(empty);
  const [creandoBasicas, setCreandoBasicas] = useState(false);

  // Un clic: las tres reglas de Colombia, saliendo por todos los proveedores.
  const crearBasicas = async () => {
    setCreandoBasicas(true);
    try {
      const existentes = new Set(items.map((r) => r.pattern));
      for (const [i, p] of PLANTILLAS.entries()) {
        if (existentes.has(p.pattern)) continue;
        await api.post("/api/outbound-routes", { ...empty, prepend: null, name: p.name, pattern: p.pattern, priority: 10 + i });
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron crear las reglas");
    } finally {
      setCreandoBasicas(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rutas, tks] = await Promise.all([
        api.get<OutboundRoute[]>("/api/outbound-routes"),
        api.get<Trunk[]>("/api/trunks"),
      ]);
      setItems(rutas);
      setTrunks(tks);
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
    setModal(true);
  };

  const openEdit = (r: OutboundRoute) => {
    setEditing(r);
    setForm({ ...r, prepend: r.prepend ?? "" });
    setModal(true);
  };

  const elegidas = new Set(form.trunk_ids.split(",").filter(Boolean));

  const alternarTroncal = (id: number) => {
    const actuales = form.trunk_ids.split(",").filter(Boolean);
    const clave = String(id);
    // El ORDEN importa: es el de reintento si la primera rechaza. Al
    // marcar una troncal se agrega al final, no se reordena la lista.
    const siguientes = actuales.includes(clave)
      ? actuales.filter((t) => t !== clave)
      : [...actuales, clave];
    setForm({ ...form, trunk_ids: siguientes.join(",") });
  };

  // `saving` evita que un doble clic cree la regla dos veces (ver el mismo
  // recaudo en rutas entrantes).
  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const payload = { ...form, prepend: form.prepend || null };
      if (editing) {
        await api.put(`/api/outbound-routes/${editing.id}`, payload);
      } else {
        await api.post("/api/outbound-routes", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (r: OutboundRoute) => {
    if (!confirm(`¿Eliminar la ruta ${r.name}?`)) return;
    try {
      await api.del(`/api/outbound-routes/${r.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const troncalesLabel = (r: OutboundRoute) => {
    const ids = r.trunk_ids.split(",").filter(Boolean);
    if (!ids.length) return "Todas";
    return ids.map((id) => trunks.find((t) => String(t.id) === id)?.name ?? `#${id}`).join(" → ");
  };

  return (
    <div>
      <PageHeader
        title="Reglas de salida"
        subtitle="A qué números se puede llamar y por qué proveedor sale cada uno. Término técnico: rutas salientes."
        actions={<Button onClick={openCreate}>+ Nueva regla</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader
          title="Tus reglas"
          subtitle={`${items.length} regla(s). Con reglas, solo salen los números que cubra alguna.`}
        />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Sin reglas: las llamadas salen por tus proveedores"
            hint="Todo sale por tus proveedores en orden. Si quieres limitar a qué se llama (por ejemplo, solo celulares y fijos de Colombia), crea las reglas básicas con un clic. Las internacionales siguen bloqueadas."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button onClick={crearBasicas} loading={creandoBasicas}>
                  Crear reglas de Colombia (celulares, fijos, 01 8000)
                </Button>
                <Button variant="secondary" onClick={openCreate}>
                  + Regla a mano
                </Button>
              </div>
            }
          />
        ) : (
          <Table head={["Prioridad", "Nombre", "Números", "Sale por", "Estado", { label: "Acciones", align: "right" }]}>
            {items.map((r, i) => (
              <Tr key={r.id} delay={i * 35}>
                <Td mono muted>
                  {r.priority}
                </Td>
                <Td>
                  {r.name}
                  {r.allow_international && (
                    <span className="ml-2">
                      <Badge color="amber">Internacional</Badge>
                    </span>
                  )}
                </Td>
                <Td mono strong>
                  {r.pattern}
                  {(r.strip_digits > 0 || r.prepend) && (
                    <span className="ml-2 text-xs text-fg-soft">
                      {r.strip_digits > 0 && `−${r.strip_digits}`}
                      {r.prepend && ` +${r.prepend}`}
                    </span>
                  )}
                </Td>
                <Td>{troncalesLabel(r)}</Td>
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
        title={editing ? `Editar regla ${editing.name}` : "Nueva regla de salida"}
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
          {!editing && (
            <div>
              <span className="mb-1.5 block text-xs font-medium text-fg-soft">Empieza con una plantilla</span>
              <div className="flex flex-wrap gap-2">
                {PLANTILLAS.map((p) => (
                  <button
                    key={p.pattern}
                    type="button"
                    onClick={() => setForm({ ...form, name: p.name, pattern: p.pattern })}
                    className={`rounded-lg border px-3 py-1.5 text-left text-xs ${
                      form.pattern === p.pattern ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                    }`}
                  >
                    <span className="block font-semibold text-fg">{p.name}</span>
                    <span className="text-muted">{p.detalle}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <Input
            label="Nombre"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="Celulares Colombia"
            required
          />
          <Input
            label="Números que cubre"
            value={form.pattern}
            onChange={(v) => setForm({ ...form, pattern: v.toUpperCase() })}
            placeholder="3XXXXXXXXX"
            hint="Cada X es un dígito cualquiera: 3XXXXXXXXX = celulares de 10 dígitos que empiezan por 3. (Z = 1-9 · N = 2-9 · . = uno o más · [1-5] = rango.)"
            required
            mono
          />
          {form.pattern && (
            <div className="rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm">
              <span className="text-fg-soft">Ejemplo: </span>
              <span className="font-mono">{ejemplo(form.pattern, form.strip_digits, form.prepend ?? "")}</span>
            </div>
          )}

          <div>
            <div className="mb-1.5 text-sm text-fg-soft">Sale por (en orden; si el primero falla, prueba el siguiente)</div>
            <div className="space-y-1.5">
              {trunks.length === 0 && <div className="text-sm text-fg-soft">Todavía no conectas un proveedor de telefonía.</div>}
              {trunks.map((t) => (
                <label
                  key={t.id}
                  className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-line bg-surface-2 px-3.5 py-2"
                >
                  <input
                    type="checkbox"
                    checked={elegidas.has(String(t.id))}
                    onChange={() => alternarTroncal(t.id)}
                  />
                  <span className="text-sm">{t.name}</span>
                  {elegidas.has(String(t.id)) && (
                    <span className="ml-auto text-xs text-fg-soft">
                      #{form.trunk_ids.split(",").filter(Boolean).indexOf(String(t.id)) + 1}
                    </span>
                  )}
                </label>
              ))}
            </div>
            <div className="mt-1.5 text-xs text-fg-soft">
              Sin marcar ninguno, usa todos tus proveedores activos.
            </div>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <div>
              <div className="text-sm text-fg-soft">Permitir llamadas internacionales</div>
              <div className="text-xs text-fg-soft">
                Apagado bloquea 00 y 011. Ahí ocurre casi todo el fraude telefónico: actívalo solo si de verdad lo necesitas.
              </div>
            </div>
            <Toggle
              checked={form.allow_international}
              onChange={(v) => setForm({ ...form, allow_international: v })}
            />
          </div>

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Activa</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>

          <details className="rounded-xl border border-line">
            <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium text-fg-soft">
              Opciones avanzadas <span className="text-xs font-normal text-muted">(solo si tu proveedor pide otro formato)</span>
            </summary>
            <div className="space-y-4 border-t border-line p-3">
              <Input
                label="Prioridad"
                type="number"
                value={form.priority}
                onChange={(v) => setForm({ ...form, priority: Number(v) })}
                hint="Si un número coincide con varias reglas, gana la de número más bajo."
              />
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="Quitar dígitos al inicio"
                  type="number"
                  value={form.strip_digits}
                  onChange={(v) => setForm({ ...form, strip_digits: Number(v) })}
                />
                <Input
                  label="Agregar al inicio"
                  value={form.prepend ?? ""}
                  onChange={(v) => setForm({ ...form, prepend: v })}
                  placeholder="57"
                  hint="Después de quitar."
                  mono
                />
              </div>
            </div>
          </details>
        </div>
      </Modal>
    </div>
  );
}
