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
  Note,
  PageHeader,
  Table,
  TableSkeleton,
  Td,
  Textarea,
  Tr,
  fieldClass,
} from "@/components/ui";
import { api } from "@/lib/api";
import { CobranzaSummary, Debt, PaymentPromise } from "@/lib/types";

const ESTADOS_DEUDA = [
  { value: "open", label: "Pendiente" },
  { value: "promised", label: "Con promesa" },
  { value: "overdue", label: "Vencida" },
  { value: "paid", label: "Pagada" },
];

const PLANES: Record<string, string> = {
  completo: "Pago total",
  abono: "Abono",
  cuotas: "Plan de cuotas",
};

function pesos(n: number) {
  return "$" + Number(n || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 });
}

function fecha(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso + (iso.includes("T") ? "" : "T00:00:00"));
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

const vacio = { phone: "", debtor_name: "", amount: "", due_date: "", invoice_number: "", notes: "" };

export default function CobranzaPage() {
  const [debts, setDebts] = useState<Debt[]>([]);
  const [promises, setPromises] = useState<PaymentPromise[]>([]);
  const [summary, setSummary] = useState<CobranzaSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creando, setCreando] = useState(false);
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState(vacio);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, p, s] = await Promise.all([
        api.get<Debt[]>("/api/cobranza/debts"),
        api.get<PaymentPromise[]>("/api/cobranza/promises"),
        api.get<CobranzaSummary>("/api/cobranza/summary"),
      ]);
      setDebts(d);
      setPromises(p);
      setSummary(s);
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

  const crear = async () => {
    setCreando(true);
    try {
      await api.post("/api/cobranza/debts", {
        phone: form.phone.trim(),
        debtor_name: form.debtor_name.trim(),
        amount: Number(form.amount) || 0,
        due_date: form.due_date.trim() || null,
        invoice_number: form.invoice_number.trim() || null,
        notes: form.notes.trim() || null,
      });
      setForm(vacio);
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear la deuda");
    } finally {
      setCreando(false);
    }
  };

  const cambiarEstado = async (d: Debt, estado: string) => {
    try {
      await api.put(`/api/cobranza/debts/${d.id}`, { status: estado });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al actualizar");
    }
  };

  const set = <K extends keyof typeof vacio>(k: K, v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div>
      <PageHeader
        title="Cobranza"
        subtitle="Cartera: deudas y promesas de pago registradas por el voizbot"
        actions={
          <Button
            onClick={() => {
              setForm(vacio);
              setModal(true);
            }}
          >
            + Nueva deuda
          </Button>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Deudas vigentes", value: summary?.debts_open ?? 0, tone: "text-warn-text" },
          { label: "Monto adeudado", value: pesos(summary?.amount_owed ?? 0), tone: "text-danger-text" },
          { label: "Promesas pendientes", value: summary?.promises_pending ?? 0, tone: "text-info-text" },
          { label: "Monto prometido", value: pesos(summary?.amount_promised ?? 0), tone: "text-ok-text" },
        ].map((s, i) => (
          <div
            key={s.label}
            style={{ animationDelay: `${i * 50}ms` }}
            className="animate-fade-up rounded-xl border border-line bg-surface-2 p-3"
          >
            <div className={`text-lg font-bold tabular-nums ${s.tone}`}>{s.value}</div>
            <div className="mt-0.5 text-xs text-muted">{s.label}</div>
          </div>
        ))}
      </div>

      <Card className="mb-4">
        <CardHeader
          title="Deudas"
          subtitle="El voizbot las consulta por teléfono al contestar; la campaña las crea al cargar los números (cliente, monto, vencimiento, factura)."
        />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : debts.length === 0 ? (
          <EmptyState
            title="No hay deudas"
            hint="Cargá números en una campaña de cobranza, o creá una a mano para probar."
            action={<Button onClick={() => setModal(true)}>+ Nueva deuda</Button>}
          />
        ) : (
          <Table head={["Nombre", "Teléfono", "Monto", "Vencimiento", "Factura", "Estado"]}>
            {debts.map((d) => (
              <Tr key={d.id}>
                <Td strong>{d.debtor_name}</Td>
                <Td mono>{d.phone}</Td>
                <Td>{pesos(d.amount)}</Td>
                <Td>{fecha(d.due_date)}</Td>
                <Td mono>{d.invoice_number ?? "—"}</Td>
                <Td>
                  <select
                    className={`${fieldClass} w-40 px-2 py-1 text-xs`}
                    value={d.status}
                    onChange={(e) => cambiarEstado(d, e.target.value)}
                  >
                    {ESTADOS_DEUDA.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Promesas de pago"
          subtitle="Lo que el voizbot registra en la llamada: monto, fecha y tipo (total, abono o cuotas)."
        />
        {loading ? (
          <TableSkeleton cols={7} />
        ) : promises.length === 0 ? (
          <EmptyState title="Sin promesas todavía" hint="Aparecen acá cuando el bot cierra una promesa en una llamada." />
        ) : (
          <Table head={["Fecha", "Teléfono", "Nombre", "Monto prometido", "Plan", "Cuotas", "Estado"]}>
            {promises.map((p) => (
              <Tr key={p.id}>
                <Td>{fecha(p.promise_date)}</Td>
                <Td mono>{p.phone}</Td>
                <Td strong>{p.debtor_name ?? "—"}</Td>
                <Td>{pesos(p.amount_promised)}</Td>
                <Td>{PLANES[p.plan] ?? p.plan}</Td>
                <Td>{p.installments ?? "—"}</Td>
                <Td>
                  <Badge color={p.status === "completed" ? "green" : p.status === "missed" ? "red" : "amber"} dot>
                    {p.status === "pending" ? "Pendiente" : p.status === "completed" ? "Cumplida" : "Vencida"}
                  </Badge>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Nueva deuda"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={crear} loading={creando} disabled={!form.phone.trim() || !form.debtor_name.trim()}>
              Guardar
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre del deudor" value={form.debtor_name} onChange={(v) => set("debtor_name", v)} required />
          <Input label="Teléfono" value={form.phone} onChange={(v) => set("phone", v)} required mono placeholder="3011234567" />
          <Input label="Monto (pesos)" type="number" value={form.amount} onChange={(v) => set("amount", v)} mono />
          <Input
            label="Vencimiento"
            value={form.due_date}
            onChange={(v) => set("due_date", v)}
            placeholder="AAAA-MM-DD"
            mono
          />
          <Input label="Factura / número de cuenta (opcional)" value={form.invoice_number} onChange={(v) => set("invoice_number", v)} mono />
          <Textarea label="Notas (opcional)" value={form.notes} onChange={(v) => set("notes", v)} rows={2} />
        </div>
      </Modal>

      <Note tone="muted">
        Las promesas las registra el voizbot con la herramienta{" "}
        <span className="font-mono">registrar_promesa</span> al cierre de la llamada; también se pueden marcar como
        cumplidas o vencidas desde acá según el cobro real.
      </Note>
    </div>
  );
}
