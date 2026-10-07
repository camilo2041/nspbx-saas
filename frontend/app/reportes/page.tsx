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
  Select,
  StatCard,
  Table,
  TableSkeleton,
  Td,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { reloj } from "@/lib/supervision";
import {
  CampaignWithStats,
  Cumplimiento,
  FilaAgenteReporte,
  FilaCampanaReporte,
  FilaDisposicionReporte,
  ReporteProgramado,
} from "@/lib/types";

type Vista = "agentes" | "campanas" | "entrantes" | "disposiciones" | "cumplimiento" | "audio" | "programados";

const VISTAS: { value: Vista; label: string }[] = [
  { value: "agentes", label: "Agentes" },
  { value: "campanas", label: "Campañas" },
  { value: "entrantes", label: "Llamadas entrantes" },
  { value: "disposiciones", label: "Disposiciones" },
  { value: "cumplimiento", label: "Cumplimiento" },
  { value: "audio", label: "Calidad de audio" },
  { value: "programados", label: "Programados" },
];

const NOMBRE_TIPO: Record<string, string> = { agentes: "Agentes", campanas: "Campañas", entrantes: "Llamadas entrantes", disposiciones: "Disposiciones", cumplimiento: "Cumplimiento" };
const FRECUENCIAS: Record<string, string> = { diaria: "Cada día (el día anterior)", semanal: "Cada lunes (la semana anterior)", mensual: "Cada día 1 (el mes anterior)" };

function hoyMenos(dias: number): string {
  const d = new Date();
  d.setDate(d.getDate() - dias);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${v} %`);
const horas = (s: number) => reloj(Math.round(s));

async function bajar(path: string, nombre: string) {
  const blob = await api.getBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Reportes del contact center: agentes, campañas, disposiciones y
 * cumplimiento, por rango de días locales, con CSV para Excel y envío
 * programado por correo. Ver backend/app/services/reportes.py.
 */
export default function ReportesPage() {
  const [vista, setVista] = useState<Vista>("agentes");
  const [desde, setDesde] = useState(() => hoyMenos(6));
  const [hasta, setHasta] = useState(() => hoyMenos(0));
  const [campana, setCampana] = useState("");
  const [agrupar, setAgrupar] = useState("campana");
  const [maxSemana, setMaxSemana] = useState("1");
  const [soloCobranza, setSoloCobranza] = useState(true);
  const [umbral, setUmbral] = useState("20");
  const [campanas, setCampanas] = useState<CampaignWithStats[]>([]);
  // Cada respuesta va con la consulta que la pidió y solo se dibuja si es la
  // vigente. Antes, al cambiar de pestaña se dibujaba un instante la vista
  // nueva con los datos de la anterior (otra forma: Cumplimiento sin
  // `abandono`, Disposiciones sin `callbacks`) y la página se caía; igual con
  // una respuesta lenta que llegaba después de cambiar.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [resultado, setResultado] = useState<{ clave: string; datos: any } | null>(null);
  const vigenteRef = useRef("");
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<CampaignWithStats[]>("/api/campaigns")
      .then((c) => setCampanas(c.filter((x) => x.metodo && x.metodo !== "voizbot")))
      .catch(() => setCampanas([]));
  }, []);

  const consulta = useCallback(
    (extra: Record<string, string> = {}) => {
      const qs = new URLSearchParams({ desde, hasta, ...extra });
      if (campana && vista !== "cumplimiento" && vista !== "entrantes" && vista !== "audio") qs.set("campaign_id", campana);
      if (vista === "entrantes") qs.set("umbral_s", String(Math.min(600, Math.max(1, Number(umbral) || 20))));
      if (vista === "disposiciones") qs.set("agrupar", agrupar);
      if (vista === "cumplimiento") {
        qs.set("max_contactos_semana", maxSemana || "1");
        qs.set("solo_cobranza", String(soloCobranza));
      }
      return `/api/reportes/${vista}?${qs.toString()}`;
    },
    [desde, hasta, campana, vista, agrupar, maxSemana, soloCobranza, umbral]
  );

  const clave = vista === "programados" ? "" : consulta();
  const datos = resultado && resultado.clave === clave ? resultado.datos : null;

  const cargar = useCallback(async () => {
    if (vista === "programados") return;
    const pedida = consulta();
    vigenteRef.current = pedida;
    setCargando(true);
    setError("");
    try {
      const r = await api.get(pedida);
      if (vigenteRef.current === pedida) setResultado({ clave: pedida, datos: r });
    } catch (e) {
      if (vigenteRef.current === pedida) setError(e instanceof Error ? e.message : "No se pudo generar el reporte");
    } finally {
      if (vigenteRef.current === pedida) setCargando(false);
    }
  }, [consulta, vista]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const csv = (seccion?: string) =>
    bajar(consulta({ formato: "csv", ...(seccion ? { seccion } : {}) }), `${vista}${seccion ? "-" + seccion : ""}_${desde}_${hasta}.csv`).catch((e) =>
      setError(e instanceof Error ? e.message : "No se pudo descargar")
    );

  return (
    <div>
      <PageHeader title="Reportes" subtitle="Del contact center, por rango de días. Ver o bajar un reporte queda en la auditoría." />
      <div className="mb-4 overflow-x-auto">
        <Segmented guia="reportes" value={vista} onChange={setVista} options={VISTAS} />
      </div>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {vista === "programados" ? (
        <Programados campanas={campanas} />
      ) : (
        <>
          <Card className="mb-4">
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
              <Input label="Desde" type="date" value={desde} onChange={setDesde} />
              <Input label="Hasta" type="date" value={hasta} onChange={setHasta} />
              {vista === "entrantes" && (
                <Input
                  label="Contestar antes de (seg)"
                  type="number"
                  value={umbral}
                  onChange={setUmbral}
                  hint="La meta del nivel de servicio. Lo típico: 20 s."
                />
              )}
              {vista !== "cumplimiento" && vista !== "entrantes" && vista !== "audio" && (
                <Select
                  label="Campaña"
                  value={campana}
                  onChange={setCampana}
                  placeholder="Todas"
                  options={campanas.map((c) => ({ value: String(c.id), label: c.name }))}
                />
              )}
              {vista === "disposiciones" && (
                <Select
                  label="Agrupar por"
                  value={agrupar}
                  onChange={setAgrupar}
                  options={[
                    { value: "campana", label: "Campaña" },
                    { value: "agente", label: "Agente" },
                    { value: "lista", label: "Lista" },
                  ]}
                />
              )}
              {vista === "cumplimiento" && (
                <>
                  <Input
                    label="Contactos por semana permitidos"
                    type="number"
                    value={maxSemana}
                    onChange={setMaxSemana}
                    hint="Llamadas contestadas al mismo número en la semana."
                  />
                  <label className="flex items-end gap-2 pb-2 text-sm text-fg-soft">
                    <Toggle checked={soloCobranza} onChange={setSoloCobranza} /> Solo campañas de cobranza
                  </label>
                </>
              )}
              <div className="flex items-end gap-2">
                {vista !== "cumplimiento" && vista !== "audio" && (
                  <Button variant="secondary" disabled={!datos} onClick={() => csv()}>
                    Descargar CSV
                  </Button>
                )}
              </div>
            </div>
          </Card>

          {cargando && !datos ? (
            <Card>
              <TableSkeleton cols={6} />
            </Card>
          ) : !datos ? null : vista === "agentes" ? (
            <Agentes filas={datos.filas} total={datos.total} />
          ) : vista === "campanas" ? (
            <Campanas filas={datos.filas} total={datos.total} />
          ) : vista === "entrantes" ? (
            <Entrantes d={datos} />
          ) : vista === "audio" ? (
            <AudioVista d={datos} />
          ) : vista === "disposiciones" ? (
            <Disposiciones filas={datos.filas} total={datos.total} callbacks={datos.callbacks} />
          ) : (
            <CumplimientoVista c={datos} onCsv={csv} />
          )}
        </>
      )}
    </div>
  );
}

function Agentes({ filas, total }: { filas: FilaAgenteReporte[]; total: Record<string, number | null> }) {
  const [abierto, setAbierto] = useState<FilaAgenteReporte | null>(null);
  if (!filas.length) return <Card><EmptyState title="Sin actividad de agentes en el rango" hint="Aparece cuando alguien trabaja desde la consola de agente." /></Card>;
  return (
    <Card>
      <CardHeader
        title="Tiempo de los agentes"
        subtitle={`Conectados ${horas(total.login_s ?? 0)} · ${total.llamadas} llamadas · ocupación ${pct(total.ocupacion_pct)}`}
      />
      <Table head={["Agente", "Conectado", "Listo", "Pausa", "En llamada", "Disposición", "Llamadas", "AHT", "Ocupación", "Utilización"]}>
        {filas.map((f) => (
          <Tr key={f.user_id}>
            <Td strong>
              <button type="button" className="text-left hover:underline" onClick={() => setAbierto(f)}>
                {f.nombre}
              </button>
            </Td>
            <Td mono>{horas(f.login_s)}</Td>
            <Td mono>{horas(f.listo_s)}</Td>
            <Td mono>{horas(f.pausa_s)}</Td>
            <Td mono>{horas(f.en_llamada_s)}</Td>
            <Td mono>{horas(f.dispo_s)}</Td>
            <Td>{f.llamadas}</Td>
            <Td mono>{f.aht_s == null ? "—" : horas(f.aht_s)}</Td>
            <Td>{pct(f.ocupacion_pct)}</Td>
            <Td>{pct(f.utilizacion_pct)}</Td>
          </Tr>
        ))}
      </Table>
      <p className="px-5 py-3 text-xs text-muted">
        Ocupación: tiempo con clientes (en llamada + disposición) sobre el tiempo disponible (conectado sin pausas). Utilización: lo mismo sobre todo el tiempo conectado.
      </p>
      <Modal open={abierto !== null} onClose={() => setAbierto(null)} title={`Pausas de ${abierto?.nombre ?? ""}`} footer={<Button onClick={() => setAbierto(null)}>Cerrar</Button>}>
        {abierto && (
          <div className="space-y-3">
            <p className="text-sm text-muted">
              Vista previa {horas(abierto.previa_s)} · Timbrando {horas(abierto.timbrando_s)} · {abierto.sesiones} sesión(es)
              {abierto.llamadas_hora != null && ` · ${abierto.llamadas_hora} llamadas/hora`}
            </p>
            {abierto.pausas.length === 0 ? (
              <p className="text-sm text-muted">Sin pausas.</p>
            ) : (
              <Table head={["Código", "Veces", "Total", "Promedio"]}>
                {abierto.pausas.map((p) => (
                  <Tr key={String(p.codigo_pausa_id)}>
                    <Td strong>{p.nombre}</Td>
                    <Td>{p.veces}</Td>
                    <Td mono>{horas(p.total_s)}</Td>
                    <Td mono>{p.promedio_s == null ? "—" : horas(p.promedio_s)}</Td>
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

function Campanas({ filas, total }: { filas: FilaCampanaReporte[]; total: Record<string, number | null> }) {
  if (!filas.length) return <Card><EmptyState title="Sin llamadas de campañas en el rango" /></Card>;
  return (
    <Card>
      <CardHeader
        title="Resultado de las campañas"
        subtitle={`${total.intentos} intentos · contacto ${pct(total.contacto_pct)} · abandono ${pct(total.abandono_pct)} · conversión ${pct(total.conversion_pct)}`}
      />
      <Table head={["Campaña", "Intentos", "Contestadas", "Ocupado", "No contesta", "Abandonadas", "Contacto", "Ring medio", "Conversación", "Ventas + promesas", "Conversión"]}>
        {filas.map((f) => (
          <Tr key={f.campaign_id}>
            <Td strong>{f.nombre}</Td>
            <Td>{f.intentos}</Td>
            <Td>{f.contestadas}</Td>
            <Td>{f.ocupado}</Td>
            <Td>{f.no_contesta}</Td>
            <Td>
              {f.abandonadas} <span className="text-xs text-muted">({pct(f.abandono_pct)})</span>
            </Td>
            <Td>{pct(f.contacto_pct)}</Td>
            <Td>{f.ring_promedio_s == null ? "—" : `${f.ring_promedio_s} s`}</Td>
            <Td mono>{f.aht_s == null ? "—" : horas(f.aht_s)}</Td>
            <Td>{f.ventas + f.promesas}</Td>
            <Td>{pct(f.conversion_pct)}</Td>
          </Tr>
        ))}
      </Table>
      <p className="px-5 py-3 text-xs text-muted">Conversión: ventas y promesas de pago sobre las llamadas dispuestas con conversación con una persona.</p>
    </Card>
  );
}

interface MedidasEntrantes {
  ofrecidas: number;
  atendidas: number;
  atendidas_en_umbral?: number;
  abandonadas: number;
  desbordadas: number;
  nivel_servicio_pct: number | null;
  atencion_pct: number | null;
  abandono_pct: number | null;
  espera_promedio_s: number | null;
  espera_max_s: number;
  espera_abandono_s: number | null;
  conversacion_promedio_s: number | null;
}

interface ReporteEntrantes {
  umbral_s: number;
  filas: (MedidasEntrantes & { cola: string })[];
  total: MedidasEntrantes;
  por_hora: { hora: number; ofrecidas: number; atendidas: number; abandonadas: number; nivel_servicio_pct: number | null }[];
  por_agente: { extension: string; nombre: string; atendidas: number; espera_promedio_s: number | null; conversacion_promedio_s: number | null }[];
}

const seg = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v)} s`);

/** Llamadas que entraron a grupos de atención (services/reportes.entrantes). */
function Entrantes({ d }: { d: ReporteEntrantes }) {
  const [hora, setHora] = useState<number | null>(null);
  if (!d.total.ofrecidas)
    return (
      <Card>
        <EmptyState
          title="Sin llamadas a grupos de atención en el rango"
          hint="Aquí se ven las llamadas que entran a un grupo (Ventas, Soporte…): cuántas se atienden a tiempo, cuántas cuelgan esperando y cuánto esperan."
        />
      </Card>
    );
  const t = d.total;
  const max = Math.max(1, ...d.por_hora.map((h) => h.ofrecidas));
  const conDatos = d.por_hora.filter((h) => h.ofrecidas > 0);
  const desde = conDatos.length ? conDatos[0].hora : 0;
  const hasta = conDatos.length ? conDatos[conDatos.length - 1].hora : 23;
  const visibles = d.por_hora.filter((h) => h.hora >= desde && h.hora <= hasta);
  const elegida = hora == null ? null : d.por_hora[hora];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label={`Atendidas antes de ${d.umbral_s} s`}
          value={pct(t.nivel_servicio_pct)}
          color="emerald"
          hint={`${t.atendidas_en_umbral ?? 0} de ${t.ofrecidas} (nivel de servicio)`}
        />
        <StatCard label="Colgaron esperando" value={pct(t.abandono_pct)} color="rose" hint={`${t.abandonadas} llamada(s)`} />
        <StatCard label="Espera media" value={seg(t.espera_promedio_s)} color="sky" hint={`Máxima: ${seg(t.espera_max_s)}`} />
        <StatCard
          label="Llamadas a grupos"
          value={t.ofrecidas}
          color="violet"
          hint={`${t.atendidas} atendidas · ${t.desbordadas} pasaron a «si nadie contesta»`}
        />
      </div>

      <Card>
        <CardHeader
          title="Llamadas por hora del día"
          subtitle={
            elegida
              ? `${String(elegida.hora).padStart(2, "0")}:00 · ${elegida.ofrecidas} llamada(s) · ${elegida.atendidas} atendidas · ${elegida.abandonadas} colgaron · nivel de servicio ${pct(elegida.nivel_servicio_pct)}`
              : "Pasa el mouse por una barra para ver el detalle. Sirve para saber a qué horas hace falta más gente."
          }
        />
        <div className="px-5 pb-4">
          <div className="flex h-40 items-end gap-[2px] border-b border-line" role="list" aria-label="Llamadas por hora">
            {visibles.map((h) => (
              <div
                key={h.hora}
                role="listitem"
                tabIndex={0}
                aria-label={`${h.hora}:00, ${h.ofrecidas} llamadas, ${h.abandonadas} colgaron`}
                onMouseEnter={() => setHora(h.hora)}
                onMouseLeave={() => setHora(null)}
                onFocus={() => setHora(h.hora)}
                onBlur={() => setHora(null)}
                className="flex h-full flex-1 cursor-default items-end"
              >
                <div
                  className={`w-full rounded-t-[4px] transition-colors ${hora === h.hora ? "bg-brand-text" : "bg-brand"}`}
                  style={{ height: `${(h.ofrecidas / max) * 100}%`, minHeight: h.ofrecidas ? 2 : 0 }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex gap-[2px] text-[10px] tabular-nums text-muted">
            {visibles.map((h) => (
              <span key={h.hora} className="flex-1 text-center">
                {h.hora % 2 === 0 || visibles.length <= 12 ? h.hora : ""}
              </span>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Por grupo de atención" subtitle={`Nivel de servicio: atendidas antes de ${d.umbral_s} s, sin contar a quien colgó en menos de 5 s.`} />
        <Table head={["Grupo", "Llamadas", "Atendidas", "A tiempo", "Colgaron", "Pasaron a «si nadie contesta»", "Espera media", "Espera máx.", "Conversación media"]}>
          {d.filas.map((f) => (
            <Tr key={f.cola}>
              <Td strong>{f.cola}</Td>
              <Td>{f.ofrecidas}</Td>
              <Td>{f.atendidas}</Td>
              <Td>{pct(f.nivel_servicio_pct)}</Td>
              <Td>
                {f.abandonadas} <span className="text-xs text-muted">({pct(f.abandono_pct)})</span>
              </Td>
              <Td>{f.desbordadas}</Td>
              <Td>{seg(f.espera_promedio_s)}</Td>
              <Td>{seg(f.espera_max_s)}</Td>
              <Td mono>{f.conversacion_promedio_s == null ? "—" : horas(f.conversacion_promedio_s)}</Td>
            </Tr>
          ))}
        </Table>
      </Card>

      {d.por_agente.length > 0 && (
        <Card>
          <CardHeader title="Quién atendió" />
          <Table head={["Persona", "Extensión", "Atendidas", "Espera media del cliente", "Conversación media"]}>
            {d.por_agente.map((a) => (
              <Tr key={a.extension}>
                <Td strong>{a.nombre}</Td>
                <Td mono>{a.extension}</Td>
                <Td>{a.atendidas}</Td>
                <Td>{seg(a.espera_promedio_s)}</Td>
                <Td mono>{a.conversacion_promedio_s == null ? "—" : horas(a.conversacion_promedio_s)}</Td>
              </Tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}

function Disposiciones({
  filas,
  total,
  callbacks,
}: {
  filas: FilaDisposicionReporte[];
  total: number;
  callbacks: { total: number; hechos: number; vencidos: number; cancelados: number };
}) {
  return (
    <Card>
      <CardHeader
        title="Disposiciones"
        subtitle={`${total} llamadas dispuestas · callbacks del rango: ${callbacks.hechos} cumplidos de ${callbacks.total}${callbacks.vencidos ? `, ${callbacks.vencidos} vencidos` : ""}`}
      />
      {!filas.length ? (
        <EmptyState title="Sin disposiciones en el rango" />
      ) : (
        <Table head={["Grupo", "Disposición", "Categoría", "Cantidad", "% del grupo"]}>
          {filas.map((f, i) => (
            <Tr key={i}>
              <Td strong>{f.grupo}</Td>
              <Td>
                {f.disposicion} <span className="font-mono text-xs text-faint">{f.codigo}</span>
              </Td>
              <Td muted>{f.categoria}</Td>
              <Td>{f.cantidad}</Td>
              <Td>{pct(f.pct)}</Td>
            </Tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function CumplimientoVista({ c, onCsv }: { c: Cumplimiento; onCsv: (seccion: string) => void }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Abandono por día"
          subtitle={c.abandono_incumplido ? `${c.abandono_incumplido} día(s) sobre el objetivo` : "Todos los días dentro del objetivo"}
          actions={<Button size="sm" variant="secondary" onClick={() => onCsv("abandono")}>CSV</Button>}
        />
        {!c.abandono.length ? (
          <EmptyState title="Sin campañas proporcionales o predictivas en el rango" />
        ) : (
          <Table head={["Fecha", "Campaña", "Contestadas", "Abandonadas", "Abandono", "Objetivo", ""]}>
            {c.abandono.map((a, i) => (
              <Tr key={i}>
                <Td mono>{a.fecha}</Td>
                <Td strong>{a.campana}</Td>
                <Td>{a.contestadas}</Td>
                <Td>{a.abandonadas}</Td>
                <Td>{pct(a.abandono_pct)}</Td>
                <Td muted>{a.objetivo_pct} %</Td>
                <Td>{a.cumple ? <Badge color="green">Cumple</Badge> : <Badge color="red">No cumple</Badge>}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader
          title="Llamadas fuera del horario permitido"
          subtitle={c.fuera_de_horario_total ? `${c.fuera_de_horario_total} llamada(s): revisar` : "Ninguna (es lo esperado)"}
          actions={<Button size="sm" variant="secondary" onClick={() => onCsv("fuera_de_horario")}>CSV</Button>}
        />
        {c.fuera_de_horario.length > 0 && (
          <Table head={["Fecha", "Campaña", "Teléfono"]}>
            {c.fuera_de_horario.map((f, i) => (
              <Tr key={i}>
                <Td mono>{f.fecha.replace("T", " ")}</Td>
                <Td>{f.campana ?? "—"}</Td>
                <Td mono>{f.telefono ?? "—"}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader
          title="Contactos por número por semana"
          subtitle={
            c.contactos_semana_total
              ? `${c.contactos_semana_total} número(s) con más de ${c.max_contactos_semana} contacto(s) en una semana`
              : `Ningún número pasó de ${c.max_contactos_semana} contacto(s) por semana`
          }
          actions={<Button size="sm" variant="secondary" onClick={() => onCsv("contactos_semana")}>CSV</Button>}
        />
        <div className="px-5 pb-3">
          <Note tone="info">
            Ley 2300 de 2023 (cobranza): confirma con tu abogado el tope que aplica a tu operación y ajústalo arriba. Cuenta las llamadas
            contestadas al mismo número de lunes a domingo.
          </Note>
        </div>
        {c.contactos_semana.length > 0 && (
          <Table head={["Teléfono", "Semana", "Contestadas", "Intentos", "Campañas"]}>
            {c.contactos_semana.map((f, i) => (
              <Tr key={i}>
                <Td mono>{f.telefono}</Td>
                <Td mono>{f.semana}</Td>
                <Td>{f.contestadas}</Td>
                <Td>{f.intentos}</Td>
                <Td muted>{f.campanas.join(", ")}</Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

const vacio = {
  id: 0,
  nombre: "",
  tipo: "campanas" as ReporteProgramado["tipo"],
  frecuencia: "diaria" as ReporteProgramado["frecuencia"],
  hora: "7",
  destinatarios: "",
  campaign_id: "",
  max_contactos_semana: "1",
  activo: true,
};

function Programados({ campanas }: { campanas: CampaignWithStats[] }) {
  const [lista, setLista] = useState<ReporteProgramado[] | null>(null);
  const [correo, setCorreo] = useState(true);
  const [form, setForm] = useState<typeof vacio | null>(null);
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState("");

  const cargar = useCallback(async () => {
    try {
      const r = await api.get<{ correo_configurado: boolean; programados: ReporteProgramado[] }>("/api/reportes/programados");
      setLista(r.programados);
      setCorreo(r.correo_configurado);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los programados");
    }
  }, []);
  useEffect(() => {
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
      const filtros: Record<string, unknown> = {};
      if (form.campaign_id && form.tipo !== "cumplimiento") filtros.campaign_id = Number(form.campaign_id);
      if (form.tipo === "cumplimiento") filtros.max_contactos_semana = Number(form.max_contactos_semana) || 1;
      const cuerpo = {
        nombre: form.nombre.trim(),
        tipo: form.tipo,
        frecuencia: form.frecuencia,
        hora: Number(form.hora),
        destinatarios: form.destinatarios,
        filtros,
        activo: form.activo,
      };
      if (form.id) await api.put(`/api/reportes/programados/${form.id}`, cuerpo);
      else await api.post("/api/reportes/programados", cuerpo);
      setForm(null);
    });

  return (
    <Card>
      <CardHeader
        title="Reportes programados"
        subtitle="Salen solos por correo con el CSV adjunto, siempre del período ya cerrado"
        actions={<Button onClick={() => setForm({ ...vacio })}>+ Nuevo</Button>}
      />
      <div className="space-y-3 px-5 pb-5">
        {!correo && (
          <Note tone="warn">
            El correo saliente no está configurado en el servidor (SMTP_HOST y SMTP_REMITENTE en el .env): los reportes quedan guardados pero no
            se envían hasta configurarlo.
          </Note>
        )}
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {!lista ? (
          <TableSkeleton cols={4} />
        ) : lista.length === 0 ? (
          <p className="text-sm text-muted">Ninguno todavía.</p>
        ) : (
          <Table head={["Reporte", "Cuándo", "Para", "Último envío", "Activo", ""]}>
            {lista.map((r) => (
              <Tr key={r.id}>
                <Td strong>
                  {r.nombre}
                  <div className="text-xs font-normal text-faint">{NOMBRE_TIPO[r.tipo]}</div>
                </Td>
                <Td muted>
                  {FRECUENCIAS[r.frecuencia]}, {String(r.hora).padStart(2, "0")}:00
                </Td>
                <Td muted>{r.destinatarios}</Td>
                <Td muted>
                  {r.ultimo_periodo ?? "—"}
                  {r.ultimo_error && <div className="max-w-xs truncate text-xs text-danger-text">{r.ultimo_error}</div>}
                </Td>
                <Td>
                  <Toggle checked={r.activo} onChange={(v) => hacer(`act-${r.id}`, () => api.put(`/api/reportes/programados/${r.id}`, { activo: v }))} />
                </Td>
                <Td>
                  <div className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!correo}
                      loading={trabajando === `env-${r.id}`}
                      onClick={() =>
                        hacer(`env-${r.id}`, async () => {
                          const x = await api.post<{ periodo: string }>(`/api/reportes/programados/${r.id}/enviar`, {});
                          alert(`Enviado (${x.periodo}).`);
                        })
                      }
                    >
                      Enviar ya
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setForm({
                          id: r.id,
                          nombre: r.nombre,
                          tipo: r.tipo,
                          frecuencia: r.frecuencia,
                          hora: String(r.hora),
                          destinatarios: r.destinatarios,
                          campaign_id: r.filtros.campaign_id ? String(r.filtros.campaign_id) : "",
                          max_contactos_semana: String(r.filtros.max_contactos_semana ?? 1),
                          activo: r.activo,
                        })
                      }
                    >
                      Editar
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => confirm(`¿Borrar «${r.nombre}»?`) && hacer(`del-${r.id}`, () => api.del(`/api/reportes/programados/${r.id}`))}
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
        title={form?.id ? "Editar reporte programado" : "Nuevo reporte programado"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button loading={trabajando === "guardar"} disabled={!form?.nombre.trim() || !form?.destinatarios.trim()} onClick={guardar}>
              Guardar
            </Button>
          </>
        }
      >
        {form && (
          <div className="space-y-4">
            <Input label="Nombre" value={form.nombre} onChange={(v) => setForm({ ...form, nombre: v })} placeholder="Resultado diario de cobranza" />
            <Select
              label="Reporte"
              value={form.tipo}
              onChange={(v) => setForm({ ...form, tipo: v as ReporteProgramado["tipo"] })}
              options={Object.entries(NOMBRE_TIPO).map(([value, label]) => ({ value, label }))}
            />
            <div className="grid grid-cols-[1fr_7rem] gap-2">
              <Select
                label="Cuándo"
                value={form.frecuencia}
                onChange={(v) => setForm({ ...form, frecuencia: v as ReporteProgramado["frecuencia"] })}
                options={Object.entries(FRECUENCIAS).map(([value, label]) => ({ value, label }))}
              />
              <Select
                label="Hora"
                value={form.hora}
                onChange={(v) => setForm({ ...form, hora: v })}
                options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, "0")}:00` }))}
              />
            </div>
            {form.tipo !== "cumplimiento" ? (
              <Select
                label="Campaña"
                value={form.campaign_id}
                onChange={(v) => setForm({ ...form, campaign_id: v })}
                placeholder="Todas"
                options={campanas.map((c) => ({ value: String(c.id), label: c.name }))}
              />
            ) : (
              <Input
                label="Contactos por semana permitidos"
                type="number"
                value={form.max_contactos_semana}
                onChange={(v) => setForm({ ...form, max_contactos_semana: v })}
              />
            )}
            <Input
              label="Para"
              value={form.destinatarios}
              onChange={(v) => setForm({ ...form, destinatarios: v })}
              placeholder="gerencia@empresa.com, calidad@empresa.com"
              hint="Hasta 10 correos, separados por coma."
            />
          </div>
        )}
      </Modal>
    </Card>
  );
}

interface FilaAudio {
  clave: string;
  llamadas: number;
  mos: number | null;
  malas: number;
  malas_pct: number;
  perdida_pct: number | null;
}

/** MOS (1 a 5): 4 o más, bien; 3.5 a 4, aceptable; menos, se nota. */
function Mos({ v, malo }: { v: number | null; malo: number }) {
  if (v === null) return <span className="text-faint">—</span>;
  return <Badge color={v >= 4 ? "green" : v >= malo ? "amber" : "red"}>{v.toFixed(2)}</Badge>;
}

function AudioVista({ d }: { d: { total: FilaAudio; por_troncal: FilaAudio[]; por_agente: FilaAudio[]; mos_malo: number } }) {
  if (!d.total.llamadas) {
    return (
      <Card>
        <EmptyState
          title="Sin llamadas medidas en el rango"
          hint="FreeSWITCH mide el audio de cada llamada contestada al colgar; aparecen aquí desde que se actualizó el sistema."
        />
      </Card>
    );
  }
  const tabla = (titulo: string, filas: FilaAudio[]) => (
    <Card>
      <CardHeader title={titulo} subtitle="De peor a mejor. Una llamada «mala» tiene MOS menor a 3.5: cortes o voz robótica." />
      <Table head={["", "Llamadas", "MOS promedio", "Malas", "Paquetes perdidos"]}>
        {filas.map((f) => (
          <Tr key={f.clave}>
            <Td>{f.clave}</Td>
            <Td>{f.llamadas}</Td>
            <Td>
              <Mos v={f.mos} malo={d.mos_malo} />
            </Td>
            <Td>
              {f.malas} ({f.malas_pct}%)
            </Td>
            <Td muted>{f.perdida_pct === null ? "—" : `${f.perdida_pct}%`}</Td>
          </Tr>
        ))}
      </Table>
    </Card>
  );
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-6 p-5 text-sm">
          <span>
            <span className="text-muted">Llamadas medidas</span> <b className="ml-1 text-fg">{d.total.llamadas}</b>
          </span>
          <span className="flex items-center gap-2">
            <span className="text-muted">MOS promedio</span> <Mos v={d.total.mos} malo={d.mos_malo} />
          </span>
          <span>
            <span className="text-muted">Malas</span> <b className="ml-1 text-fg">{d.total.malas_pct}%</b>
          </span>
        </div>
      </Card>
      {tabla("Por proveedor", d.por_troncal)}
      {d.por_agente.length > 0 && tabla("Por agente", d.por_agente)}
    </div>
  );
}
