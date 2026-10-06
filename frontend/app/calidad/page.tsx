"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  Table,
  TableSkeleton,
  Td,
  Textarea,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PERMISOS } from "@/lib/types";
import { tiempoCorto } from "@/lib/utils";

interface Criterio {
  id: number | null;
  nombre: string;
  descripcion: string | null;
  peso: number;
  activo: boolean;
}

interface Evaluacion {
  id: number;
  call_id: number;
  agente: string | null;
  evaluador: string | null;
  puntajes: Record<string, number>;
  total_pct: number;
  comentario: string | null;
  origen: "manual" | "ia";
  created_at: string;
}

interface FilaLlamada {
  id: number;
  started_at: string | null;
  direccion: string;
  de: string | null;
  a: string | null;
  billsec: number;
  cola: string | null;
  agente: string | null;
  evaluacion: { id: number; total_pct: number; origen: string } | null;
}

interface Detalle {
  id: number;
  started_at: string | null;
  de: string | null;
  a: string | null;
  billsec: number;
  cola: string | null;
  agente: string | null;
  resumen: string | null;
  transcripcion: { rol: string; texto: string }[] | null;
  evaluaciones: Evaluacion[];
}

type Vista = "evaluar" | "resultados" | "criterios";

const NOTAS = [
  { valor: 2, texto: "Cumple", tono: "bg-ok text-white" },
  { valor: 1, texto: "A medias", tono: "bg-warn text-white" },
  { valor: 0, texto: "No cumple", tono: "bg-danger text-white" },
];

function hoyMenos(dias: number): string {
  const d = new Date();
  d.setDate(d.getDate() - dias);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const fecha = (iso: string | null) =>
  iso ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" }) : "—";

const tonoPct = (v: number | null | undefined) => (v == null ? "slate" : v >= 85 ? "green" : v >= 65 ? "amber" : "red");

/**
 * Calidad de llamadas: escuchar una llamada grabada, calificarla contra los
 * criterios de la empresa (a mano o con una sugerencia de la IA que se
 * revisa) y ver el promedio de cada persona. Quien no supervisa ve aquí sus
 * propias evaluaciones. Backend: services/calidad.py.
 */
export default function CalidadPage() {
  const { puede } = useAuth();
  const supervisa = puede(PERMISOS.supervisionVer);
  const [vista, setVista] = useState<Vista>("evaluar");

  if (!supervisa) return <MisEvaluaciones />;
  return (
    <div>
      <PageHeader
        title="Calidad"
        subtitle="Escucha llamadas grabadas, califícalas con los criterios de tu empresa y mira cómo va cada persona."
      />
      <div className="mb-4">
        <Segmented
          value={vista}
          onChange={setVista}
          options={[
            { value: "evaluar", label: "Evaluar llamadas" },
            { value: "resultados", label: "Resultados" },
            { value: "criterios", label: "Criterios" },
          ]}
        />
      </div>
      {vista === "evaluar" ? <Evaluar /> : vista === "resultados" ? <Resultados /> : <Criterios />}
    </div>
  );
}

// --- Evaluar ---------------------------------------------------------------------------

function Evaluar() {
  const [desde, setDesde] = useState(() => hoyMenos(6));
  const [hasta, setHasta] = useState(() => hoyMenos(0));
  const [sinEvaluar, setSinEvaluar] = useState(true);
  const [filas, setFilas] = useState<FilaLlamada[] | null>(null);
  const [error, setError] = useState("");
  const [abierta, setAbierta] = useState<number | null>(null);

  const cargar = useCallback(async () => {
    try {
      setFilas(
        await api.get<FilaLlamada[]>(`/api/calidad/llamadas?desde=${desde}&hasta=${hasta}&sin_evaluar=${sinEvaluar}`)
      );
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las llamadas");
      setFilas([]);
    }
  }, [desde, hasta, sinEvaluar]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  return (
    <>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      <Card>
        <CardHeader
          title="Llamadas grabadas"
          subtitle="Contestadas, de 10 segundos o más."
          actions={
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-40">
                <Input label="Desde" type="date" value={desde} onChange={setDesde} />
              </div>
              <div className="w-40">
                <Input label="Hasta" type="date" value={hasta} onChange={setHasta} />
              </div>
              <label className="flex items-center gap-2 pb-2 text-sm text-fg-soft">
                <Toggle checked={sinEvaluar} onChange={setSinEvaluar} /> Solo sin evaluar
              </label>
            </div>
          }
        />
        {filas === null ? (
          <TableSkeleton cols={6} />
        ) : filas.length === 0 ? (
          <EmptyState
            title={sinEvaluar ? "No hay llamadas grabadas sin evaluar en el rango" : "No hay llamadas grabadas en el rango"}
            hint="Para tener llamadas que evaluar, activa la grabación (Ajustes → grabar todas las llamadas, o en cada grupo de atención)."
          />
        ) : (
          <Table head={["Fecha", "Atendió", "Cliente", "Duración", "Grupo", "Evaluación", ""]}>
            {filas.map((f) => (
              <Tr key={f.id}>
                <Td>{fecha(f.started_at)}</Td>
                <Td strong>{f.agente || "—"}</Td>
                <Td mono>{f.direccion === "inbound" ? f.de : f.a}</Td>
                <Td>{tiempoCorto(f.billsec)}</Td>
                <Td>{f.cola || "—"}</Td>
                <Td>
                  {f.evaluacion ? (
                    <Badge color={tonoPct(f.evaluacion.total_pct)}>{f.evaluacion.total_pct} %</Badge>
                  ) : (
                    <span className="text-xs text-muted">Sin evaluar</span>
                  )}
                </Td>
                <Td align="right">
                  <Button size="sm" variant={f.evaluacion ? "secondary" : "primary"} onClick={() => setAbierta(f.id)}>
                    {f.evaluacion ? "Ver" : "Evaluar"}
                  </Button>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
      {abierta !== null && (
        <EvaluarLlamada
          callId={abierta}
          onCerrar={(guardo) => {
            setAbierta(null);
            if (guardo) cargar();
          }}
        />
      )}
    </>
  );
}

function Grabacion({ callId }: { callId: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  const ref = useRef<string | null>(null);
  useEffect(() => {
    let vivo = true;
    api
      .getBlob(`/api/calls/${callId}/recording`)
      .then((b) => {
        if (!vivo) return;
        ref.current = URL.createObjectURL(b);
        setUrl(ref.current);
      })
      .catch((e) => vivo && setError(e instanceof Error ? e.message : "No se pudo cargar la grabación"));
    return () => {
      vivo = false;
      if (ref.current) URL.revokeObjectURL(ref.current);
    };
  }, [callId]);
  if (error) return <p className="text-xs text-danger-text">{error}</p>;
  if (!url) return <p className="text-xs text-muted">Cargando la grabación…</p>;
  return <audio controls src={url} className="w-full" />;
}

function EvaluarLlamada({ callId, onCerrar }: { callId: number; onCerrar: (guardo: boolean) => void }) {
  const [detalle, setDetalle] = useState<Detalle | null>(null);
  const [criterios, setCriterios] = useState<Criterio[]>([]);
  const [puntajes, setPuntajes] = useState<Record<string, number>>({});
  const [comentario, setComentario] = useState("");
  const [origen, setOrigen] = useState<"manual" | "ia">("manual");
  const [trabajando, setTrabajando] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.get<Detalle>(`/api/calidad/llamadas/${callId}`), api.get<Criterio[]>("/api/calidad/criterios")])
      .then(([d, c]) => {
        setDetalle(d);
        setCriterios(c.filter((x) => x.activo));
      })
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar la llamada"));
  }, [callId]);

  const transcribir = async () => {
    setTrabajando("transcribir");
    setError("");
    try {
      const r = await api.post<{ transcripcion: Detalle["transcripcion"] }>(`/api/calidad/llamadas/${callId}/transcribir`);
      setDetalle((d) => (d ? { ...d, transcripcion: r.transcripcion } : d));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo transcribir");
    } finally {
      setTrabajando("");
    }
  };

  const sugerir = async () => {
    setTrabajando("ia");
    setError("");
    try {
      const r = await api.post<{ puntajes: Record<string, number>; comentario: string }>(
        `/api/calidad/llamadas/${callId}/sugerencia`
      );
      setPuntajes(r.puntajes);
      setComentario(r.comentario);
      setOrigen("ia");
      if (!detalle?.transcripcion) {
        const d = await api.get<Detalle>(`/api/calidad/llamadas/${callId}`);
        setDetalle(d);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "La IA no pudo evaluar la llamada");
    } finally {
      setTrabajando("");
    }
  };

  const guardar = async () => {
    setTrabajando("guardar");
    setError("");
    try {
      await api.post(`/api/calidad/llamadas/${callId}/evaluaciones`, { puntajes, comentario: comentario || null, origen });
      onCerrar(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setTrabajando("");
    }
  };

  const completa = criterios.length > 0 && criterios.every((c) => puntajes[String(c.id)] !== undefined);
  const posible = criterios.reduce((s, c) => s + c.peso * 2, 0);
  const logrado = criterios.reduce((s, c) => s + c.peso * (puntajes[String(c.id)] ?? 0), 0);
  const pct = posible ? Math.round((1000 * logrado) / posible) / 10 : 0;
  const previa = detalle?.evaluaciones[0];

  return (
    <Modal
      open
      onClose={() => onCerrar(false)}
      size="xl"
      title={detalle ? `Llamada de ${detalle.agente || "—"}` : "Llamada"}
      subtitle={detalle ? `${fecha(detalle.started_at)} · ${tiempoCorto(detalle.billsec)}${detalle.cola ? ` · ${detalle.cola}` : ""}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={() => onCerrar(false)}>
            Cerrar
          </Button>
          <Button onClick={guardar} loading={trabajando === "guardar"} disabled={!completa}>
            Guardar evaluación{completa ? ` (${pct} %)` : ""}
          </Button>
        </>
      }
    >
      {error && <Note tone="warn">{error}</Note>}
      {!detalle ? (
        <p className="text-sm text-muted">Cargando…</p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-3">
            <Grabacion callId={callId} />
            {detalle.resumen && <Note tone="muted">{detalle.resumen}</Note>}
            <div className="rounded-xl border border-line">
              <div className="flex items-center justify-between border-b border-line px-3 py-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted">Transcripción</span>
                {!detalle.transcripcion && (
                  <Button size="sm" variant="secondary" onClick={transcribir} loading={trabajando === "transcribir"}>
                    Transcribir
                  </Button>
                )}
              </div>
              <div className="max-h-72 space-y-1.5 overflow-y-auto p-3 text-xs">
                {detalle.transcripcion ? (
                  detalle.transcripcion.length ? (
                    detalle.transcripcion.map((t, i) => (
                      <p key={i}>
                        <span className="font-semibold text-fg">{t.rol}:</span> <span className="text-fg-soft">{t.texto}</span>
                      </p>
                    ))
                  ) : (
                    <p className="text-muted">La grabación no tiene voz reconocible.</p>
                  )
                ) : (
                  <p className="text-muted">Transcribe la llamada para leerla o para que la IA sugiera la evaluación.</p>
                )}
              </div>
            </div>
          </div>

          <div className="space-y-3">
            {previa && (
              <Note tone="brand">
                Ya tiene una evaluación de {previa.total_pct} % ({previa.evaluador || "—"}, {fecha(previa.created_at)}). Si
                guardas otra, queda la más reciente.
              </Note>
            )}
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-fg">Criterios</span>
              <Button size="sm" variant="secondary" onClick={sugerir} loading={trabajando === "ia"}>
                ✨ Sugerir con IA
              </Button>
            </div>
            {origen === "ia" && (
              <p className="text-xs text-muted">La IA propuso estas notas a partir de la transcripción. Revísalas antes de guardar.</p>
            )}
            <ul className="space-y-2">
              {criterios.map((c) => (
                <li key={c.id} className="rounded-xl border border-line p-3">
                  <p className="text-sm font-medium text-fg">
                    {c.nombre}
                    {c.peso > 1 && <span className="ml-1 text-xs text-muted">(vale ×{c.peso})</span>}
                  </p>
                  {c.descripcion && <p className="text-xs text-muted">{c.descripcion}</p>}
                  <div className="mt-2 flex gap-1.5" role="radiogroup" aria-label={c.nombre}>
                    {NOTAS.map((n) => {
                      const activo = puntajes[String(c.id)] === n.valor;
                      return (
                        <button
                          key={n.valor}
                          type="button"
                          role="radio"
                          aria-checked={activo}
                          onClick={() => setPuntajes({ ...puntajes, [String(c.id)]: n.valor })}
                          className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                            activo ? `${n.tono} border-transparent` : "border-line text-fg-soft hover:bg-surface-2"
                          }`}
                        >
                          {n.texto}
                        </button>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ul>
            <Textarea
              label="Comentario para la persona (opcional)"
              value={comentario}
              onChange={setComentario}
              rows={3}
              placeholder="Qué hizo bien y qué puede mejorar."
            />
          </div>
        </div>
      )}
    </Modal>
  );
}

// --- Resultados ----------------------------------------------------------------------------

interface Resumen {
  criterios: Criterio[];
  filas: { agente_id: number | null; agente: string; evaluaciones: number; promedio_pct: number | null; por_criterio: Record<string, number> }[];
  total: { evaluaciones: number; promedio_pct: number | null };
}

function Resultados() {
  const [desde, setDesde] = useState(() => hoyMenos(29));
  const [hasta, setHasta] = useState(() => hoyMenos(0));
  const [datos, setDatos] = useState<Resumen | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Resumen>(`/api/calidad/resumen?desde=${desde}&hasta=${hasta}`)
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, [desde, hasta]);

  const activos = (datos?.criterios ?? []).filter((c) => c.activo);
  return (
    <>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      <Card>
        <CardHeader
          title="Promedio por persona"
          subtitle={
            datos?.total.evaluaciones
              ? `${datos.total.evaluaciones} evaluación(es) · promedio general ${datos.total.promedio_pct} %`
              : "Evaluaciones hechas en el rango."
          }
          actions={
            <div className="flex gap-3">
              <div className="w-40">
                <Input label="Desde" type="date" value={desde} onChange={setDesde} />
              </div>
              <div className="w-40">
                <Input label="Hasta" type="date" value={hasta} onChange={setHasta} />
              </div>
            </div>
          }
        />
        {!datos ? (
          <TableSkeleton cols={4} />
        ) : datos.filas.length === 0 ? (
          <EmptyState title="Todavía no hay evaluaciones en el rango" hint="Evalúa llamadas en la pestaña «Evaluar llamadas»." />
        ) : (
          <Table head={["Persona", "Evaluaciones", "Promedio", ...activos.map((c) => c.nombre)]}>
            {datos.filas.map((f) => (
              <Tr key={f.agente_id ?? "x"}>
                <Td strong>{f.agente}</Td>
                <Td>{f.evaluaciones}</Td>
                <Td>
                  <Badge color={tonoPct(f.promedio_pct)}>{f.promedio_pct ?? "—"} %</Badge>
                </Td>
                {activos.map((c) => (
                  <Td key={c.id}>{f.por_criterio[String(c.id)] != null ? `${f.por_criterio[String(c.id)]} %` : "—"}</Td>
                ))}
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

// --- Criterios ------------------------------------------------------------------------------

function Criterios() {
  const [lista, setLista] = useState<Criterio[] | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);

  useEffect(() => {
    api
      .get<Criterio[]>("/api/calidad/criterios")
      .then((c) => setLista(c.filter((x) => x.activo)))
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, []);

  const cambiar = (i: number, cambio: Partial<Criterio>) => {
    setOk(false);
    setLista((l) => l && l.map((c, j) => (j === i ? { ...c, ...cambio } : c)));
  };

  const guardar = async () => {
    if (!lista) return;
    setGuardando(true);
    setError("");
    try {
      const r = await api.put<Criterio[]>(
        "/api/calidad/criterios",
        lista.filter((c) => c.nombre.trim()).map((c) => ({ ...c, nombre: c.nombre.trim() }))
      );
      setLista(r.filter((x) => x.activo));
      setOk(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold text-fg">Qué se evalúa en cada llamada</h2>
      <p className="mt-1 text-sm text-fg-soft">
        Cada criterio se califica «Cumple», «A medias» o «No cumple». Un criterio con peso 2 cuenta el doble en el total.
      </p>
      {error && (
        <div className="mt-3">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      {!lista ? (
        <p className="mt-4 text-sm text-muted">Cargando…</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {lista.map((c, i) => (
            <li key={c.id ?? `n${i}`} className="grid gap-2 rounded-xl border border-line p-3 sm:grid-cols-[1fr_1fr_6rem_auto]">
              <Input label="Criterio" value={c.nombre} onChange={(v) => cambiar(i, { nombre: v })} />
              <Input label="Qué significa (opcional)" value={c.descripcion ?? ""} onChange={(v) => cambiar(i, { descripcion: v || null })} />
              <Input
                label="Peso"
                type="number"
                value={String(c.peso)}
                onChange={(v) => cambiar(i, { peso: Math.min(10, Math.max(1, Number(v) || 1)) })}
              />
              <div className="flex items-end">
                <Button variant="ghost" size="sm" onClick={() => setLista(lista.filter((_, j) => j !== i))}>
                  Quitar
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => setLista((l) => [...(l ?? []), { id: null, nombre: "", descripcion: null, peso: 1, activo: true }])}
        >
          + Agregar criterio
        </Button>
        <Button onClick={guardar} loading={guardando} disabled={!lista?.some((c) => c.nombre.trim())}>
          Guardar criterios
        </Button>
        {ok && <span className="text-sm text-ok-text">Guardado.</span>}
      </div>
    </Card>
  );
}

// --- Para quien no supervisa: sus evaluaciones ------------------------------------------------

function MisEvaluaciones() {
  const [datos, setDatos] = useState<{ criterios: Criterio[]; evaluaciones: Evaluacion[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api
      .get<{ criterios: Criterio[]; evaluaciones: Evaluacion[] }>("/api/calidad/mias")
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, []);
  const nombre = (id: string) => datos?.criterios.find((c) => String(c.id) === id)?.nombre ?? "Criterio";
  return (
    <div>
      <PageHeader title="Mis evaluaciones" subtitle="Cómo te calificaron en las llamadas evaluadas y qué te recomendaron." />
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}
      {!datos ? (
        <Card>
          <TableSkeleton cols={3} />
        </Card>
      ) : datos.evaluaciones.length === 0 ? (
        <Card>
          <EmptyState title="Todavía no tienes llamadas evaluadas" />
        </Card>
      ) : (
        <div className="space-y-3">
          {datos.evaluaciones.map((e) => (
            <Card key={e.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-fg-soft">
                  {fecha(e.created_at)} · evaluó {e.evaluador || "—"}
                </p>
                <Badge color={tonoPct(e.total_pct)}>{e.total_pct} %</Badge>
              </div>
              <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                {Object.entries(e.puntajes).map(([id, v]) => (
                  <li key={id} className="flex justify-between gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5">
                    <span className="text-fg-soft">{nombre(id)}</span>
                    <span className="font-medium text-fg">{NOTAS.find((n) => n.valor === v)?.texto}</span>
                  </li>
                ))}
              </ul>
              {e.comentario && <p className="mt-2 text-sm text-fg">{e.comentario}</p>}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
