"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Check,
  EmptyState,
  ErrorBanner,
  Input,
  Note,
  PageHeader,
  Select,
  Spinner,
  StatusDot,
  Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { esperarSesionAgente, useSoftphone } from "@/lib/softphone-context";
import { EstadoAgente, EstadoConsola } from "@/lib/types";
import { tiempoCorto } from "@/lib/utils";

const REFRESCO_MS = 1500;

const ESTADO: Record<EstadoAgente, { label: string; color: string }> = {
  LISTO: { label: "Listo", color: "green" },
  PAUSA: { label: "En pausa", color: "amber" },
  PREVIA: { label: "Viendo un lead", color: "blue" },
  TIMBRANDO: { label: "Timbrando", color: "blue" },
  EN_LLAMADA: { label: "En llamada", color: "violet" },
  DISPO: { label: "Disposición", color: "red" },
};

const METODO: Record<string, string> = {
  manual: "Manual",
  vista_previa: "Vista previa",
  progresivo: "Progresivo",
  proporcional: "Proporcional",
  predictivo: "Predictivo",
};

function aFecha(iso: string) {
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
}

function cronometro(desde: string | null | undefined, ahora: number) {
  if (!desde) return "0:00";
  const s = Math.max(0, Math.floor((ahora - aFecha(desde).getTime()) / 1000));
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`;
}

function fechaHora(iso: string | null) {
  if (!iso) return "—";
  return aFecha(iso).toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "2026-10-03T14:30" local → ISO en UTC para la API. */
function localAIso(valor: string) {
  return valor ? new Date(valor).toISOString() : null;
}

/**
 * Consola del agente. El estado vive en el backend (services/agentes.py) y
 * se consulta cada 1,5 s: la consola solo pide acciones y dibuja lo que
 * hay. El audio llega como una llamada a la extensión del agente que el
 * softphone contesta solo (con el token de esta sesión).
 */
export default function ConsolaAgente() {
  const { connState, connect, entorno } = useSoftphone();
  const [estado, setEstado] = useState<EstadoConsola | null>(null);
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState("");
  const [ahora, setAhora] = useState(() => Date.now());
  const [elegidas, setElegidas] = useState<number[]>([]);
  const [manual, setManual] = useState({ campana: "", telefono: "" });
  const [dispo, setDispo] = useState({ id: 0, nota: "", callback: "", propio: true });
  const [nota, setNota] = useState("");

  const cargar = useCallback(async () => {
    try {
      const e = await api.get<EstadoConsola>("/api/agente/estado");
      setEstado(e);
      esperarSesionAgente(e.agente?.token_audio ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar la consola");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") cargar();
    }, REFRESCO_MS);
    const reloj = setInterval(() => setAhora(Date.now()), 1000);
    return () => {
      clearInterval(t);
      clearInterval(reloj);
    };
  }, [cargar]);

  // Al salir de la consola se deja de aceptar la llamada de la sesión.
  useEffect(() => () => esperarSesionAgente(null), []);

  const hacer = async (nombre: string, ruta: string, cuerpo?: unknown) => {
    setTrabajando(nombre);
    setError("");
    try {
      const e = await api.post<EstadoConsola>(`/api/agente/${ruta}`, cuerpo);
      setEstado(e);
      esperarSesionAgente(e.agente?.token_audio ?? null);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo");
      return false;
    } finally {
      setTrabajando("");
    }
  };

  const agente = estado?.agente ?? null;
  const misCampanas = useMemo(
    () => (estado?.campanas ?? []).filter((c) => agente?.campanas.includes(c.id)),
    [estado, agente]
  );
  const hayVistaPrevia = misCampanas.some((c) => c.metodo === "vista_previa");
  const enCurso = agente?.estado === "TIMBRANDO" || agente?.estado === "EN_LLAMADA";
  const libre = agente?.estado === "LISTO" || agente?.estado === "PAUSA";
  const pausaActual = estado?.pausas.find((p) => p.id === agente?.codigo_pausa_id);
  const dispoElegida = estado?.disposiciones.find((d) => d.id === dispo.id);

  if (!estado) {
    return (
      <div>
        <PageHeader title="Consola de agente" />
        {error ? <ErrorBanner message={error} /> : <Spinner />}
      </div>
    );
  }

  // --- Sin sesión: elegir campañas y entrar ---------------------------------
  if (!agente) {
    const softphoneListo = connState === "registered";
    return (
      <div>
        <PageHeader title="Consola de agente" subtitle="Entra a tus campañas para recibir y hacer llamadas" />
        {error && (
          <div className="mb-4">
            <ErrorBanner message={error} onClose={() => setError("")} />
          </div>
        )}
        {estado.campanas.length === 0 ? (
          <Card>
            <EmptyState
              title="No tienes campañas asignadas"
              hint="Un supervisor te asigna en Campañas → la campaña → Agentes. Solo las campañas manuales, de vista previa o progresivas usan agentes."
            />
          </Card>
        ) : (
          <Card>
            <CardHeader title="Tus campañas" subtitle="Elige en cuáles vas a trabajar hoy" />
            <CardBody className="space-y-3">
              {estado.campanas.map((c) => (
                <div key={c.id} className="flex items-center justify-between gap-3">
                  <Check
                    checked={elegidas.includes(c.id)}
                    onChange={(v) => setElegidas(v ? [...elegidas, c.id] : elegidas.filter((x) => x !== c.id))}
                    label={c.nombre}
                  />
                  <span className="flex items-center gap-2 text-xs text-muted">
                    {METODO[c.metodo] ?? c.metodo}
                    {c.status !== "running" && c.metodo !== "manual" && <Badge color="slate">Detenida</Badge>}
                  </span>
                </div>
              ))}
              {!entorno?.extension ? (
                <Note tone="warn">No tienes extensión asignada: pídele a un administrador que te asigne una.</Note>
              ) : !softphoneListo ? (
                <Note tone="warn">
                  Conecta el softphone antes de entrar: la consola te llama a tu extensión para abrir el audio.{" "}
                  <button type="button" className="font-medium underline" onClick={() => connect()}>
                    Conectar ahora
                  </button>
                </Note>
              ) : (
                <Note tone="muted">
                  Al entrar, la central llama a tu extensión {entorno.extension.number} y el softphone contesta solo. Mantén
                  esta pestaña abierta.
                </Note>
              )}
              <Button
                onClick={() => hacer("entrar", "entrar", { campanas: elegidas })}
                loading={trabajando === "entrar"}
                disabled={elegidas.length === 0 || !softphoneListo}
              >
                Entrar
              </Button>
            </CardBody>
          </Card>
        )}
      </div>
    );
  }

  const e = ESTADO[agente.estado] ?? { label: agente.estado, color: "slate" };
  const lead = estado.lead;

  return (
    <div>
      <PageHeader
        title="Consola de agente"
        subtitle={misCampanas.map((c) => `${c.nombre} (${METODO[c.metodo] ?? c.metodo})`).join(" · ")}
        actions={
          <Button variant="secondary" onClick={() => hacer("salir", "salir")} loading={trabajando === "salir"} disabled={enCurso}>
            Salir
          </Button>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {/* Barra de estado */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-3 px-5 py-4">
          <Badge color={e.color} dot>
            {e.label}
            {agente.estado === "PAUSA" && pausaActual ? `: ${pausaActual.nombre}` : ""}
          </Badge>
          <span className="font-mono text-lg tabular-nums text-fg">
            {cronometro(agente.estado === "EN_LLAMADA" ? agente.contestada_at ?? agente.desde : agente.desde, ahora)}
          </span>
          <span className="flex items-center gap-1.5 text-xs text-muted">
            <StatusDot color={agente.audio ? "ok" : "danger"} pulse={!agente.audio} />
            {agente.audio ? "Audio conectado" : "Sin audio"}
          </span>
          {agente.pausa_pendiente_id !== null && (
            <Badge color="amber">Pausa al terminar</Badge>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {!agente.audio && (
              <Button size="sm" variant="secondary" onClick={() => hacer("audio", "audio")} loading={trabajando === "audio"}>
                Reconectar audio
              </Button>
            )}
            {agente.estado === "PAUSA" && (
              <Button size="sm" variant="success" onClick={() => hacer("listo", "listo")} loading={trabajando === "listo"} disabled={!agente.audio}>
                Listo
              </Button>
            )}
            {agente.estado !== "PAUSA" && agente.pausa_pendiente_id === null && (
              <select
                value=""
                onChange={(ev) => ev.target.value && hacer("pausa", "pausa", { codigo_pausa_id: Number(ev.target.value) })}
                className="rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-fg"
                aria-label="Pausar"
              >
                <option value="">Pausar…</option>
                {estado.pausas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nombre}
                  </option>
                ))}
              </select>
            )}
            {agente.estado === "PAUSA" && (
              <select
                value={agente.codigo_pausa_id ?? ""}
                onChange={(ev) => hacer("pausa", "pausa", { codigo_pausa_id: ev.target.value ? Number(ev.target.value) : null })}
                className="rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-fg"
                aria-label="Motivo de la pausa"
              >
                <option value="">Sin motivo</option>
                {estado.pausas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nombre}
                  </option>
                ))}
              </select>
            )}
            {hayVistaPrevia && libre && (
              <Button size="sm" onClick={() => hacer("siguiente", "siguiente")} loading={trabajando === "siguiente"} disabled={!agente.audio}>
                Siguiente lead
              </Button>
            )}
            {enCurso && (
              <Button size="sm" variant="danger" onClick={() => hacer("colgar", "colgar")} loading={trabajando === "colgar"}>
                Colgar
              </Button>
            )}
          </div>
        </div>
        {libre && (
          <div className="flex flex-wrap items-end gap-2 border-t border-line px-5 py-3">
            <div className="w-56">
              <Select
                label="Marcar a mano en"
                value={manual.campana || String(misCampanas[0]?.id ?? "")}
                onChange={(v) => setManual({ ...manual, campana: v })}
                options={misCampanas.map((c) => ({ value: String(c.id), label: c.nombre }))}
              />
            </div>
            <div className="w-52">
              <Input label="Número" value={manual.telefono} onChange={(v) => setManual({ ...manual, telefono: v })} mono placeholder="3011234567" />
            </div>
            <Button
              onClick={async () => {
                const ok = await hacer("marcar", "marcar", {
                  campaign_id: Number(manual.campana || misCampanas[0]?.id),
                  telefono: manual.telefono,
                });
                if (ok) setManual({ ...manual, telefono: "" });
              }}
              loading={trabajando === "marcar"}
              disabled={!manual.telefono.trim() || !agente.audio}
            >
              Marcar
            </Button>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {lead ? (
            <>
              <Card>
                <CardHeader
                  title={lead.contacto?.nombre || lead.telefono}
                  subtitle={[lead.telefono, lead.campana?.nombre, `${lead.intentos} intento(s)`].filter(Boolean).join(" · ")}
                  actions={
                    agente.estado === "PREVIA" ? (
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => hacer("saltar", "saltar")} loading={trabajando === "saltar"}>
                          Saltar
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => hacer("marcar", "marcar", { campaign_id: lead.campana?.id, lead_id: lead.id })}
                          loading={trabajando === "marcar"}
                        >
                          Marcar
                        </Button>
                      </div>
                    ) : undefined
                  }
                />
                <CardBody>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {[
                      ["Documento", lead.contacto?.documento],
                      ["Correo", lead.contacto?.email],
                      ["Ciudad", lead.contacto?.ciudad],
                      ["Otros teléfonos", lead.contacto?.telefonos.map((t) => t.numero).join(", ")],
                      ...Object.entries(lead.contacto?.campos ?? {}).map(([k, v]) => [k, typeof v === "boolean" ? (v ? "Sí" : "No") : String(v)]),
                      ...Object.entries(lead.variables)
                        .filter(([k]) => !["nombre", "cliente", "telefono", "agente"].includes(k))
                        .map(([k, v]) => [k, v]),
                    ]
                      .filter(([, v]) => v)
                      .map(([k, v]) => (
                        <div key={String(k)} className="rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                          <div className="text-[11px] uppercase tracking-wide text-faint">{k}</div>
                          <div className="mt-0.5 truncate text-sm text-fg">{v}</div>
                        </div>
                      ))}
                  </div>
                  {lead.llamadas_anteriores.length > 0 && (
                    <div className="mt-4">
                      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">Llamadas anteriores</h4>
                      <div className="space-y-1 text-xs text-fg-soft">
                        {lead.llamadas_anteriores.map((l, i) => (
                          <div key={i}>
                            {fechaHora(l.started_at)} · {l.status}
                            {l.billsec > 0 && ` · ${tiempoCorto(l.billsec)}`}
                            {l.disposicion && ` · ${l.disposicion}`}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </CardBody>
              </Card>
              {lead.guion && (
                <Card>
                  <CardHeader title="Guion" />
                  <CardBody>
                    <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-fg">{lead.guion}</p>
                  </CardBody>
                </Card>
              )}
              {lead.contacto && (
                <Card>
                  <CardHeader title="Notas del cliente" />
                  <CardBody>
                    <div className="flex items-end gap-2">
                      <div className="flex-1">
                        <Textarea label="" value={nota} onChange={setNota} rows={2} placeholder="Qué se habló…" />
                      </div>
                      <Button
                        variant="secondary"
                        disabled={!nota.trim()}
                        onClick={async () => {
                          if (await hacer("nota", "nota", { texto: nota.trim() })) setNota("");
                        }}
                      >
                        Guardar
                      </Button>
                    </div>
                    {lead.notas.map((n) => (
                      <div key={n.id} className="mt-3 border-t border-line pt-2">
                        <p className="whitespace-pre-wrap text-[13px] text-fg">{n.texto}</p>
                        <p className="text-[11px] text-faint">
                          {n.autor ?? "—"} · {fechaHora(n.created_at)}
                        </p>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <EmptyState
                title={agente.estado === "LISTO" ? "Esperando la próxima llamada" : "Sin cliente en pantalla"}
                hint={
                  hayVistaPrevia
                    ? "Pide el siguiente lead o marca un número a mano."
                    : misCampanas.some((c) => ["progresivo", "proporcional", "predictivo"].includes(c.metodo))
                      ? "En las campañas automáticas la llamada llega sola cuando estás listo."
                      : "Marca un número a mano para empezar."
                }
              />
            </Card>
          )}
        </div>

        <div className="space-y-4">
          {agente.estado === "DISPO" && (
            <Card>
              <CardHeader title="¿Cómo terminó la llamada?" subtitle="Elige el resultado para seguir" />
              <CardBody className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  {estado.disposiciones.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => setDispo({ ...dispo, id: d.id })}
                      className={`press rounded-xl border px-2.5 py-2 text-left text-xs font-medium transition-colors ${
                        dispo.id === d.id ? "border-brand bg-brand-soft text-brand-text" : "border-line text-fg-soft hover:bg-surface-2"
                      }`}
                    >
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: d.color ?? "var(--line)" }} />
                      {d.nombre}
                    </button>
                  ))}
                </div>
                {dispoElegida?.categoria === "callback" && (
                  <>
                    <Input
                      label="Volver a llamar el"
                      type="datetime-local"
                      value={dispo.callback}
                      onChange={(v) => setDispo({ ...dispo, callback: v })}
                    />
                    <Check checked={dispo.propio} onChange={(v) => setDispo({ ...dispo, propio: v })} label="Solo yo (si no, cualquier agente de la campaña)" />
                  </>
                )}
                <Textarea label="Nota (opcional)" value={dispo.nota} onChange={(v) => setDispo({ ...dispo, nota: v })} rows={2} />
                <Button
                  onClick={async () => {
                    const ok = await hacer("disponer", "disponer", {
                      disposicion_id: dispo.id,
                      nota: dispo.nota.trim() || null,
                      callback_at: localAIso(dispo.callback),
                      callback_propio: dispo.propio,
                    });
                    if (ok) setDispo({ id: 0, nota: "", callback: "", propio: true });
                  }}
                  loading={trabajando === "disponer"}
                  disabled={!dispo.id || (dispoElegida?.categoria === "callback" && !dispo.callback)}
                >
                  Guardar y seguir
                </Button>
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Callbacks" subtitle={`${estado.callbacks.length} pendiente(s)`} />
            {estado.callbacks.length === 0 ? (
              <div className="px-5 py-6 text-center text-sm text-muted">No tienes callbacks pendientes.</div>
            ) : (
              <div className="divide-y divide-line">
                {estado.callbacks.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 px-5 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium text-fg">{c.nombre || c.telefono}</div>
                      <div className={`text-[11px] ${c.vencido ? "text-danger-text" : "text-faint"}`}>
                        {fechaHora(c.cuando)} {c.propio ? "· tuyo" : "· de la campaña"}
                        {c.nota && ` · ${c.nota}`}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!libre || !agente.audio}
                      onClick={() => hacer(`cb${c.id}`, `callbacks/${c.id}/llamar`)}
                      loading={trabajando === `cb${c.id}`}
                    >
                      Llamar
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
