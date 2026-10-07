"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  fieldClass,
  Input,
  Modal,
  PageHeader,
  Pagination,
  RowActions,
  SearchInput,
  Segmented,
  Select,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { useOffsetPorFiltro } from "@/lib/paginacion";
import { api } from "@/lib/api";
import { Appointment, GestionRow } from "@/lib/types";

const gestionLabel: Record<GestionRow["action"], { label: string; color: string }> = {
  confirmada: { label: "Confirmó", color: "green" },
  cancelada: { label: "Canceló", color: "red" },
  reagendada: { label: "Reagendó", color: "amber" },
  agendada: { label: "Agendó", color: "blue" },
};

const POR_PAGINA = 50;

const empty: Omit<Appointment, "id" | "created_at"> = {
  patient_name: "",
  phone: "",
  appointment_date: "",
  duration_minutes: 30,
  status: "confirmed",
  notes: "",
};

function toLocalInputValue(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const statusLabel: Record<string, { label: string; color: string }> = {
  confirmed: { label: "Confirmada", color: "green" },
  cancelled: { label: "Cancelada", color: "red" },
  completed: { label: "Completada", color: "blue" },
};

export default function AppointmentsPage() {
  const [vista, setVista] = useState<"gestion" | "agenda">("gestion");
  const [items, setItems] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Appointment | null>(null);
  const [form, setForm] = useState(empty);
  const [dayFilter, setDayFilter] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [estadoFiltro, setEstadoFiltro] = useState("");
  const [offset, setOffset] = useOffsetPorFiltro([dayFilter, busqueda, estadoFiltro]);

  const [gestion, setGestion] = useState<GestionRow[]>([]);
  const [gestionLoading, setGestionLoading] = useState(true);
  const [errorGestion, setErrorGestion] = useState("");

  const loadGestion = useCallback(async () => {
    setGestionLoading(true);
    try {
      setGestion(await api.get<GestionRow[]>("/api/appointments/gestion?days=30"));
      setErrorGestion("");
    } catch (e) {
      setErrorGestion(e instanceof Error ? e.message : "Error");
    } finally {
      setGestionLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar o al cambiar los filtros
    loadGestion();
  }, [loadGestion]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ limit: String(POR_PAGINA), offset: String(offset) });
      if (dayFilter) qs.set("day", dayFilter);
      if (busqueda.trim()) qs.set("search", busqueda.trim());
      if (estadoFiltro) qs.set("estado", estadoFiltro);
      setItems(await api.get<Appointment[]>(`/api/appointments?${qs.toString()}`));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [dayFilter, busqueda, estadoFiltro, offset]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar o al cambiar los filtros
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setModal(true);
  };

  const openEdit = (a: Appointment) => {
    setEditing(a);
    setForm({ ...a, appointment_date: a.appointment_date, notes: a.notes ?? "" });
    setModal(true);
  };

  const save = async () => {
    try {
      // Se manda la hora tal cual la escribió el usuario, SIN pasar por
      // toISOString(): eso la convertía a UTC y la cita de las 10:00
      // terminaba guardada a las 15:00. El backend interpreta las fechas
      // sin zona como hora local del consultorio.
      const payload = { ...form, appointment_date: form.appointment_date };
      if (editing) {
        await api.put(`/api/appointments/${editing.id}`, payload);
      } else {
        await api.post("/api/appointments", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    }
  };

  const remove = async (a: Appointment) => {
    if (!confirm(`¿Eliminar la cita de ${a.patient_name}?`)) return;
    try {
      await api.del(`/api/appointments/${a.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  return (
    <div>
      <PageHeader
        title="Citas"
        subtitle="Qué hizo el agente de IA por teléfono, y la agenda que dejó — o cargala vos manualmente"
        actions={vista === "agenda" ? <Button onClick={openCreate}>+ Nueva cita</Button> : undefined}
      />

      <div className="mb-4">
        <Segmented
          value={vista}
          onChange={setVista}
          options={[
            { value: "gestion", label: "Gestión (qué hizo el bot)" },
            { value: "agenda", label: "Agenda" },
          ]}
        />
      </div>

      {vista === "gestion" ? (
        <>
          {errorGestion && (
            <div className="mb-4">
              <ErrorBanner message={errorGestion} onClose={() => setErrorGestion("")} />
            </div>
          )}
          <Card>
            <CardHeader
              title="Gestión de citas por IA"
              subtitle={`${gestion.length} acción(es) en los últimos 30 días`}
              actions={
                <Button size="sm" variant="secondary" onClick={loadGestion} loading={gestionLoading}>
                  Actualizar
                </Button>
              }
            />
            {gestionLoading ? (
              <TableSkeleton cols={5} />
            ) : gestion.length === 0 ? (
              <EmptyState
                title="Todavía no hay gestiones"
                hint="Acá va a aparecer cada vez que el voizbot confirme, cancele o reagende una cita — por una llamada entrante o por una campaña de confirmación."
              />
            ) : (
              <Table head={["Cuándo llamó", "Teléfono", "Paciente", "Gestión", "Cita"]}>
                {gestion.map((g, i) => (
                  <Tr key={g.id} delay={i * 35}>
                    <Td muted>{new Date(g.called_at).toLocaleString()}</Td>
                    <Td mono muted>{g.phone ?? "—"}</Td>
                    <Td strong>{g.patient_name ?? "—"}</Td>
                    <Td>
                      <Badge color={gestionLabel[g.action]?.color ?? "slate"} dot>
                        {gestionLabel[g.action]?.label ?? g.action}
                      </Badge>
                    </Td>
                    <Td>{g.appointment_date ? new Date(g.appointment_date).toLocaleString() : "—"}</Td>
                  </Tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      ) : (
        <>
          {error && (
            <div className="mb-4">
              <ErrorBanner message={error} onClose={() => setError("")} />
            </div>
          )}

          <Card>
            <CardHeader
              title="Lista de citas"
              subtitle={`${items.length} registrada(s)`}
              actions={
                <div className="flex flex-wrap items-center gap-2">
                  <SearchInput
                    value={busqueda}
                    onChange={setBusqueda}
                    placeholder="Buscar paciente o teléfono…"
                    className="w-56"
                  />
                  <div className="w-40">
                    <Select
                      label=""
                      value={estadoFiltro}
                      onChange={setEstadoFiltro}
                      placeholder="Cualquier estado"
                      options={Object.entries(statusLabel).map(([v, m]) => ({ value: v, label: m.label }))}
                    />
                  </div>
                  <input
                    type="date"
                    value={dayFilter}
                    onChange={(e) => setDayFilter(e.target.value)}
                    className={`${fieldClass} w-auto py-1.5`}
                  />
                  {(dayFilter || busqueda || estadoFiltro) && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setDayFilter("");
                        setBusqueda("");
                        setEstadoFiltro("");
                      }}
                    >
                      Limpiar
                    </Button>
                  )}
                </div>
              }
            />
            {loading ? (
              <TableSkeleton cols={6} />
            ) : items.length === 0 ? (
              // El texto cambia según haya filtros puestos: decir "creá la
              // primera cita" cuando en realidad hay cientos pero ninguna
              // coincide con la búsqueda hace pensar que se borró todo.
              busqueda || estadoFiltro || dayFilter ? (
                <EmptyState
                  title="Ninguna cita coincide"
                  hint="Probá con otro nombre, teléfono, estado o fecha — o limpiá los filtros."
                  action={
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setBusqueda("");
                        setEstadoFiltro("");
                        setDayFilter("");
                      }}
                    >
                      Limpiar filtros
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  title="No hay citas"
                  hint="Crea la primera, o esperá a que el agente de IA agende una por teléfono."
                  action={<Button onClick={openCreate}>+ Nueva cita</Button>}
                />
              )
            ) : (
              <Table
                head={["Fecha y hora", "Paciente", "Teléfono", "Duración", "Estado", { label: "Acciones", align: "right" }]}
              >
                {items.map((a, i) => (
                  <Tr key={a.id} delay={i * 35}>
                    <Td strong>{new Date(a.appointment_date).toLocaleString()}</Td>
                    <Td>{a.patient_name}</Td>
                    <Td mono muted>
                      {a.phone}
                    </Td>
                    <Td muted>{a.duration_minutes} min</Td>
                    <Td>
                      <Badge color={statusLabel[a.status]?.color ?? "slate"} dot>
                        {statusLabel[a.status]?.label ?? a.status}
                      </Badge>
                    </Td>
                    <Td align="right">
                      <RowActions>
                        <Button size="sm" variant="secondary" onClick={() => openEdit(a)}>
                          Editar
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => remove(a)}>
                          Eliminar
                        </Button>
                      </RowActions>
                    </Td>
                  </Tr>
                ))}
              </Table>
            )}
            <Pagination
              offset={offset}
              limit={POR_PAGINA}
              recibidos={items.length}
              onChange={setOffset}
              cargando={loading}
            />
          </Card>
        </>
      )}

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar cita de ${editing.patient_name}` : "Nueva cita"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save}>{editing ? "Guardar" : "Crear"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="Paciente"
            value={form.patient_name}
            onChange={(v) => setForm({ ...form, patient_name: v })}
            required
          />
          <Input label="Teléfono" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} required mono />
          <Field label="Fecha y hora">
            <input
              type="datetime-local"
              value={toLocalInputValue(form.appointment_date)}
              onChange={(e) => setForm({ ...form, appointment_date: e.target.value })}
              className={fieldClass}
            />
          </Field>
          <Input
            label="Duración (minutos)"
            type="number"
            value={form.duration_minutes}
            onChange={(v) => setForm({ ...form, duration_minutes: Number(v) })}
          />
          <Select
            label="Estado"
            value={form.status}
            onChange={(v) => setForm({ ...form, status: v as Appointment["status"] })}
            options={[
              { value: "confirmed", label: "Confirmada" },
              { value: "cancelled", label: "Cancelada" },
              { value: "completed", label: "Completada" },
            ]}
          />
          <Input label="Notas" value={form.notes ?? ""} onChange={(v) => setForm({ ...form, notes: v })} />
        </div>
      </Modal>
    </div>
  );
}
