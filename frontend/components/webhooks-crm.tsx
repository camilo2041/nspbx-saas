"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, Check, ErrorBanner, Input, Modal, Note, Table, Td, Toggle, Tr } from "@/components/ui";
import { api } from "@/lib/api";
import { EntregaWebhook, WebhookCrm } from "@/lib/types";

// Webhooks hacia el CRM de la empresa. Ver backend/app/services/integraciones.py.

function fecha(valor: string | null): string {
  return valor ? new Date(valor + "Z").toLocaleString() : "—";
}

const ESTADO: Record<EntregaWebhook["estado"], { label: string; color: string }> = {
  pendiente: { label: "Pendiente", color: "amber" },
  ok: { label: "Entregado", color: "green" },
  fallida: { label: "Fallida", color: "red" },
};

export function WebhooksCrm() {
  const [lista, setLista] = useState<WebhookCrm[]>([]);
  const [eventos, setEventos] = useState<{ evento: string; descripcion: string }[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState<{ id: number; nombre: string; url: string; eventos: string[] } | null>(null);
  const [secreto, setSecreto] = useState<string | null>(null);
  const [bitacora, setBitacora] = useState<{ webhook: WebhookCrm; entregas: EntregaWebhook[] } | null>(null);
  const [trabajando, setTrabajando] = useState("");

  const cargar = useCallback(async () => {
    try {
      setLista(await api.get<WebhookCrm[]>("/api/integraciones/webhooks"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los webhooks");
    }
  }, []);

  useEffect(() => {
    api.get<{ evento: string; descripcion: string }[]>("/api/integraciones/eventos").then(setEventos).catch(() => setEventos([]));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const hacer = async (clave: string, fn: () => Promise<unknown>) => {
    setTrabajando(clave);
    setError("");
    try {
      await fn();
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar");
    } finally {
      setTrabajando("");
    }
  };

  const guardar = () =>
    form &&
    hacer("guardar", async () => {
      const cuerpo = { nombre: form.nombre.trim(), url: form.url.trim(), eventos: form.eventos };
      if (form.id) {
        await api.put(`/api/integraciones/webhooks/${form.id}`, cuerpo);
      } else {
        const r = await api.post<WebhookCrm>("/api/integraciones/webhooks", cuerpo);
        setSecreto(r.secreto ?? null);
      }
      setForm(null);
    });

  const verBitacora = async (w: WebhookCrm) => {
    try {
      setBitacora({ webhook: w, entregas: await api.get<EntregaWebhook[]>(`/api/integraciones/webhooks/${w.id}/entregas`) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la bitácora");
    }
  };

  return (
    <Card className="mb-6">
      <CardHeader
        title="Webhooks hacia tu CRM"
        subtitle="Avisos firmados cuando un cliente contesta, se dispone una llamada, se agenda un callback o un número pasa a no llamar"
        actions={<Button onClick={() => setForm({ id: 0, nombre: "", url: "https://", eventos: eventos.map((e) => e.evento) })}>+ Nuevo</Button>}
      />
      <div className="space-y-3 px-5 pb-5">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {secreto && (
          <Note tone="brand">
            <div className="space-y-2">
              <div>Secreto de firma. Cópialo ahora en tu CRM: no se vuelve a mostrar.</div>
              <code className="block break-all rounded bg-surface-2 p-2 text-xs">{secreto}</code>
              <div className="text-xs text-muted">
                Cada aviso trae X-NSPBX-Firma: t=&lt;segundos&gt;,v1=&lt;hex&gt;, con v1 = HMAC-SHA256(secreto, t + &quot;.&quot; + cuerpo). Rechaza
                una firma que no coincida o con t de más de 5 minutos. X-NSPBX-Entrega identifica el aviso: si llega dos veces, procésalo una.
              </div>
              <Button size="sm" variant="secondary" onClick={() => setSecreto(null)}>
                Ya lo guardé
              </Button>
            </div>
          </Note>
        )}
        {lista.length === 0 ? (
          <p className="text-sm text-muted">Sin webhooks. Con uno, tu CRM se entera al instante de lo que pasa en las llamadas.</p>
        ) : (
          <Table head={["Nombre", "Eventos", "Estado", "Activo", ""]}>
            {lista.map((w) => (
              <Tr key={w.id}>
                <Td strong>
                  {w.nombre}
                  <div className="max-w-xs truncate font-mono text-xs font-normal text-faint">{w.url}</div>
                </Td>
                <Td muted>{w.eventos.join(", ")}</Td>
                <Td>
                  {w.fallos_seguidos > 0 ? (
                    <Badge color="red">{w.fallos_seguidos} fallo(s) seguidos</Badge>
                  ) : (
                    <Badge color={w.ultimo_ok_at ? "green" : "slate"}>{w.ultimo_ok_at ? "Entregando" : "Sin envíos"}</Badge>
                  )}
                  {w.pendientes > 0 && <div className="mt-1 text-xs text-muted">{w.pendientes} en cola</div>}
                </Td>
                <Td>
                  <Toggle checked={w.activo} onChange={(v) => hacer(`act-${w.id}`, () => api.put(`/api/integraciones/webhooks/${w.id}`, { activo: v }))} />
                </Td>
                <Td>
                  <div className="flex flex-wrap justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={trabajando === `probar-${w.id}`}
                      onClick={() =>
                        hacer(`probar-${w.id}`, async () => {
                          const e = await api.post<EntregaWebhook>(`/api/integraciones/webhooks/${w.id}/probar`, {});
                          if (e.estado !== "ok") throw new Error(`La prueba no llegó: ${e.ultimo_error ?? "sin respuesta"}`);
                          alert("La prueba llegó a tu CRM.");
                        })
                      }
                    >
                      Probar
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => verBitacora(w)}>
                      Bitácora
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setForm({ id: w.id, nombre: w.nombre, url: w.url, eventos: w.eventos })}>
                      Editar
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        confirm("¿Generar un secreto nuevo? El de ahora deja de valer ya: actualízalo en tu CRM.") &&
                        hacer(`rotar-${w.id}`, async () => {
                          const r = await api.post<{ secreto: string }>(`/api/integraciones/webhooks/${w.id}/rotar-secreto`, {});
                          setSecreto(r.secreto);
                        })
                      }
                    >
                      Rotar secreto
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        confirm(`¿Borrar el webhook «${w.nombre}»?`) && hacer(`borrar-${w.id}`, () => api.del(`/api/integraciones/webhooks/${w.id}`))
                      }
                    >
                      Borrar
                    </Button>
                  </div>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </div>

      <Modal
        open={form !== null}
        onClose={() => setForm(null)}
        title={form?.id ? "Editar webhook" : "Nuevo webhook"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button loading={trabajando === "guardar"} disabled={!form?.nombre.trim() || !form?.eventos.length} onClick={guardar}>
              Guardar
            </Button>
          </>
        }
      >
        {form && (
          <div className="space-y-4">
            <Input label="Nombre" value={form.nombre} onChange={(v) => setForm({ ...form, nombre: v })} placeholder="CRM de ventas" />
            <Input
              label="URL"
              value={form.url}
              mono
              onChange={(v) => setForm({ ...form, url: v })}
              hint="https:// y accesible desde internet. Recibe un POST JSON por cada evento."
            />
            <div className="space-y-2">
              <span className="block text-xs font-medium text-fg-soft">Eventos</span>
              {eventos.map((e) => (
                <Check
                  key={e.evento}
                  checked={form.eventos.includes(e.evento)}
                  onChange={(v) =>
                    setForm({ ...form, eventos: v ? [...form.eventos, e.evento] : form.eventos.filter((x) => x !== e.evento) })
                  }
                  label={`${e.evento} — ${e.descripcion}`}
                />
              ))}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={bitacora !== null} onClose={() => setBitacora(null)} title={`Bitácora de ${bitacora?.webhook.nombre ?? ""}`} footer={<Button onClick={() => setBitacora(null)}>Cerrar</Button>}>
        {bitacora && (
          <div className="space-y-3">
            <p className="text-sm text-muted">Los últimos 100 avisos. Se reintentan solos (30 s, 2 min, 10 min, 30 min, 2 h) y después quedan fallidos.</p>
            {bitacora.entregas.length === 0 ? (
              <p className="text-sm text-muted">Todavía no hubo avisos.</p>
            ) : (
              <Table head={["Evento", "Estado", "Intentos", "Detalle", ""]}>
                {bitacora.entregas.map((e) => (
                  <Tr key={e.id}>
                    <Td mono>
                      {e.evento}
                      <div className="text-xs text-faint">{fecha(e.created_at)}</div>
                    </Td>
                    <Td>
                      <Badge color={ESTADO[e.estado].color}>{ESTADO[e.estado].label}</Badge>
                    </Td>
                    <Td muted>{e.intentos}</Td>
                    <Td muted>
                      {e.ultimo_codigo ? `HTTP ${e.ultimo_codigo}` : ""}
                      {e.ultimo_error && <div className="max-w-xs truncate text-xs text-danger-text">{e.ultimo_error}</div>}
                      {e.estado === "pendiente" && e.proximo_intento_at && <div className="text-xs">Próximo: {fecha(e.proximo_intento_at)}</div>}
                    </Td>
                    <Td>
                      {e.estado === "fallida" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            hacer(`re-${e.id}`, async () => {
                              await api.post(`/api/integraciones/entregas/${e.id}/reintentar`, {});
                              await verBitacora(bitacora.webhook);
                            })
                          }
                        >
                          Reintentar
                        </Button>
                      )}
                    </Td>
                  </Tr>
                ))}
              </Table>
            )}
          </div>
        )}
      </Modal>
    </Card>
  );
}
