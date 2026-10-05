"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, ErrorBanner, Modal, Note, Spinner, Textarea } from "@/components/ui";
import { DatosContacto, FormularioContacto, cuerpoDe, datosDe } from "@/components/crm/formulario-contacto";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FichaContacto as Ficha, PERMISOS } from "@/lib/types";
import { statusBadge, tiempoCorto } from "@/lib/utils";

function fechaHora(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString("es-CO", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function pesos(n: number) {
  return "$" + Number(n || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 });
}

const ESTADO_LLAMADA: Record<string, { label: string; color: string }> = {
  answered: { label: "Contestada", color: "green" },
  no_answer: { label: "Sin respuesta", color: "amber" },
  busy: { label: "Ocupado", color: "amber" },
  failed: { label: "Fallida", color: "red" },
  rejected: { label: "Rechazada", color: "red" },
  cancelled: { label: "Cancelada", color: "slate" },
};

function Seccion({ titulo, children, vacio }: { titulo: string; children: React.ReactNode; vacio: boolean }) {
  return (
    <section className="mt-5">
      <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">{titulo}</h4>
      {vacio ? <p className="text-xs text-faint">Nada todavía.</p> : <div className="divide-y divide-line rounded-xl border border-line">{children}</div>}
    </section>
  );
}

function Fila({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-[13px]">{children}</div>;
}

/**
 * Ficha del contacto: datos, campos propios, notas y el historial por
 * cualquiera de sus teléfonos. El backend decide qué partes del historial
 * puede ver el rol (`secciones`); acá solo se dibuja lo que llega.
 */
export function FichaContacto({
  contactoId,
  onClose,
  onCambio,
}: {
  contactoId: number | null;
  onClose: () => void;
  onCambio?: () => void;
}) {
  const { puede } = useAuth();
  const gestiona = puede(PERMISOS.crmGestionar);
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [error, setError] = useState("");
  const [editando, setEditando] = useState<DatosContacto | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [nota, setNota] = useState("");

  const cargar = useCallback(async (id: number) => {
    try {
      setFicha(await api.get<Ficha>(`/api/crm/contactos/${id}`));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el contacto");
    }
  }, []);

  useEffect(() => {
    if (contactoId === null) return;
    // Al abrir otro contacto: lo de antes ya no aplica (los setState van tras el await).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar(contactoId);
  }, [contactoId, cargar]);

  const cerrar = () => {
    setFicha(null);
    setEditando(null);
    setNota("");
    setError("");
    onClose();
  };

  const guardar = async () => {
    if (!ficha || !editando) return;
    setGuardando(true);
    try {
      await api.put(`/api/crm/contactos/${ficha.contacto.id}`, cuerpoDe(editando, ficha.campos_definidos));
      setEditando(null);
      await cargar(ficha.contacto.id);
      onCambio?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const agregarNota = async () => {
    if (!ficha || !nota.trim()) return;
    try {
      await api.post(`/api/crm/contactos/${ficha.contacto.id}/notas`, { texto: nota.trim() });
      setNota("");
      await cargar(ficha.contacto.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar la nota");
    }
  };

  const noLlamar = async () => {
    if (!ficha) return;
    const motivo = window.prompt("¿Por qué no se le debe llamar? (opcional)") ?? undefined;
    if (motivo === undefined) return;
    try {
      await api.post("/api/crm/no-llamar", { telefono: ficha.contacto.telefono, motivo: motivo || null });
      await cargar(ficha.contacto.id);
      onCambio?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo agregar a no llamar");
    }
  };

  const borrar = async () => {
    if (!ficha) return;
    if (!window.confirm(`¿Borrar a ${ficha.contacto.nombre || ficha.contacto.telefono} y sus notas? Sus números en campañas se conservan.`)) return;
    try {
      await api.del(`/api/crm/contactos/${ficha.contacto.id}`);
      onCambio?.();
      cerrar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar");
    }
  };

  const c = ficha?.contacto;
  return (
    <Modal
      open={contactoId !== null}
      onClose={cerrar}
      size="xl"
      title={c ? c.nombre || c.telefono : "Contacto"}
      subtitle={c ? [c.telefono, c.documento && `Doc. ${c.documento}`, c.ciudad].filter(Boolean).join(" · ") : undefined}
      actions={
        c && gestiona && !editando ? (
          <Button size="sm" variant="secondary" onClick={() => setEditando(datosDe(c))}>
            Editar
          </Button>
        ) : undefined
      }
      footer={
        editando ? (
          <>
            <Button variant="secondary" onClick={() => setEditando(null)}>
              Cancelar
            </Button>
            <Button onClick={guardar} loading={guardando} disabled={!editando.telefono.trim()}>
              Guardar
            </Button>
          </>
        ) : undefined
      }
    >
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      {!ficha ? (
        <Spinner />
      ) : editando ? (
        <FormularioContacto datos={editando} onChange={setEditando} defs={ficha.campos_definidos} />
      ) : (
        <>
          {ficha.telefonos_no_llamar.length > 0 && (
            <div className="mb-4">
              <Note tone="warn">
                En la lista de no llamar: {ficha.telefonos_no_llamar.join(", ")}. Ninguna campaña los marca.
              </Note>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            {[
              ["Correo", c!.email],
              ["Dirección", c!.direccion],
              ["Otros teléfonos", c!.telefonos.map((t) => `${t.numero} (${t.tipo})`).join(", ")],
              ["Origen", c!.fuente],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                <div className="text-[11px] uppercase tracking-wide text-faint">{k}</div>
                <div className="mt-0.5 truncate text-sm text-fg">{v || "—"}</div>
              </div>
            ))}
            {ficha.campos_definidos.map((def) => {
              const v = c!.campos[def.clave];
              return (
                <div key={def.clave} className="rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                  <div className="text-[11px] uppercase tracking-wide text-faint">{def.nombre}</div>
                  <div className="mt-0.5 truncate text-sm text-fg">
                    {v === undefined || v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "Sí" : "No") : String(v)}
                  </div>
                </div>
              );
            })}
          </div>

          {gestiona && (
            <div className="mt-3 flex flex-wrap gap-2">
              {!c!.no_llamar && (
                <Button size="sm" variant="secondary" onClick={noLlamar}>
                  Agregar a no llamar
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={borrar}>
                Borrar contacto
              </Button>
            </div>
          )}

          <section className="mt-5">
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Notas</h4>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Textarea label="" value={nota} onChange={setNota} rows={2} placeholder="Qué se habló, qué quedó pendiente…" />
              </div>
              <Button onClick={agregarNota} disabled={!nota.trim()}>
                Guardar nota
              </Button>
            </div>
            {ficha.notas.length > 0 && (
              <div className="mt-3 divide-y divide-line rounded-xl border border-line">
                {ficha.notas.map((n) => (
                  <div key={n.id} className="px-3.5 py-2.5">
                    <p className="whitespace-pre-wrap text-[13px] text-fg">{n.texto}</p>
                    <p className="mt-1 text-[11px] text-faint">
                      {n.autor ?? "—"} · {fechaHora(n.created_at)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          {ficha.secciones.llamadas && (
            <Seccion titulo="Llamadas" vacio={ficha.llamadas.length === 0}>
              {ficha.llamadas.map((l) => {
                const e = ESTADO_LLAMADA[l.status] ?? { label: l.status, color: "slate" };
                return (
                  <Fila key={l.id}>
                    <Badge color={l.direction === "inbound" ? "blue" : "violet"}>
                      {l.direction === "inbound" ? "Entrante" : "Saliente"}
                    </Badge>
                    <span className="font-mono text-fg-soft">
                      {l.caller_number ?? "—"} → {l.callee_number ?? "—"}
                    </span>
                    <span className="text-faint">{fechaHora(l.started_at)}</span>
                    {l.billsec > 0 && <span className="text-faint">{tiempoCorto(l.billsec)}</span>}
                    {l.ring_ms !== null && <span className="text-faint">ring {tiempoCorto(l.ring_ms / 1000)}</span>}
                    <span className="ml-auto">
                      <Badge color={e.color} dot>
                        {e.label}
                      </Badge>
                    </span>
                  </Fila>
                );
              })}
            </Seccion>
          )}

          {ficha.secciones.campanas && (
            <Seccion titulo="Campañas" vacio={ficha.campanas.length === 0}>
              {ficha.campanas.map((n) => {
                const b = n.status === "no_llamar" ? { label: "No llamar", color: "red" } : statusBadge(n.status);
                return (
                  <Fila key={n.numero_id}>
                    <span className="font-medium text-fg">{n.campana}</span>
                    <span className="font-mono text-fg-soft">{n.phone}</span>
                    <span className="text-faint">
                      {n.attempts} intento{n.attempts === 1 ? "" : "s"}
                      {n.proximo_intento_at && ` · próximo ${fechaHora(n.proximo_intento_at)}`}
                    </span>
                    <span className="ml-auto">
                      <Badge color={b.color} dot>
                        {b.label}
                      </Badge>
                    </span>
                  </Fila>
                );
              })}
            </Seccion>
          )}

          {ficha.secciones.cobranza && (ficha.deudas.length > 0 || ficha.promesas.length > 0) && (
            <Seccion titulo="Cobranza" vacio={false}>
              {ficha.deudas.map((d) => (
                <Fila key={`d${d.id}`}>
                  <span className="font-medium text-fg">Deuda {pesos(d.amount)}</span>
                  {d.invoice_number && <span className="font-mono text-faint">{d.invoice_number}</span>}
                  <span className="text-faint">vence {fechaHora(d.due_date)}</span>
                  <span className="ml-auto text-xs text-muted">{d.status}</span>
                </Fila>
              ))}
              {ficha.promesas.map((p) => (
                <Fila key={`p${p.id}`}>
                  <span className="font-medium text-fg">Promesa {pesos(p.amount_promised)}</span>
                  <span className="text-faint">para {fechaHora(p.promise_date)} · {p.plan}</span>
                  <span className="ml-auto text-xs text-muted">{p.status}</span>
                </Fila>
              ))}
            </Seccion>
          )}

          {ficha.secciones.citas && ficha.citas.length > 0 && (
            <Seccion titulo="Citas" vacio={false}>
              {ficha.citas.map((a) => (
                <Fila key={a.id}>
                  <span className="font-medium text-fg">{fechaHora(a.appointment_date)}</span>
                  <span className="text-faint">{a.patient_name}</span>
                  <span className="ml-auto text-xs text-muted">{a.status}</span>
                </Fila>
              ))}
            </Seccion>
          )}
        </>
      )}
    </Modal>
  );
}

