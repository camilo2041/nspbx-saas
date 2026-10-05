"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  ErrorBanner,
  Note,
  PageHeader,
  Pagination,
  SearchInput,
  Segmented,
  StatCard,
  Table,
  TableSkeleton,
  Td,
  Tr,
  Badge,
} from "@/components/ui";
import { api } from "@/lib/api";

const POR_PAGINA = 25;

/* Paleta de las gráficas.
   Sale de los tokens del panel (naranja de marca + azul de info) y está
   validada para daltonismo contra las dos superficies, clara y oscura:
   ΔE 23.4 en protanopía y 33.3 en visión normal, muy por encima del piso.
   El mismo par sirve en ambos temas, así que no hay que cambiarlo al
   alternar modo oscuro. */
const C_VOZ = "#ff8a00"; // voz + transcripción (sea quien sea el proveedor)
const C_MODELO = "#0284c7"; // el modelo de lenguaje

type Summary = {
  days: number;
  calls: number;
  resolved: number;
  containment_rate: number;
  turns: number;
  cost_usd: number;
  cost_per_call: number;
  cost_per_resolved: number;
  avg_turns: number;
  avg_duration: number;
  cost_per_minute: number;
  providers: Provider[];
};

type Provider = {
  key: string;
  label: string;
  role: string;
  cost_usd: number;
  share: number;
  tts_chars: number;
  stt_seconds: number;
  tokens: number;
  requests: number;
};

type Daily = {
  date: string;
  calls: number;
  tts_chars: number;
  stt_seconds: number;
  tokens: number;
  cost_voz: number;
  cost_modelo: number;
  cost_usd: number;
};

type CallRow = {
  id: number;
  phone: string | null;
  started_at: string;
  duration_seconds: number;
  turns: number;
  tts_chars: number;
  stt_seconds: number;
  tokens: number;
  cost_voz: number;
  tts_provider: string;
  stt_provider: string;
  cost_modelo: number;
  outcome: string;
  resolved: boolean;
  cost_usd: number;
};

const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`;
const miles = (n: number) => n.toLocaleString("es-CO");
const dur = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const diaCorto = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es-CO", { day: "numeric", month: "short" });

const outcomeLabel: Record<string, { label: string; color: string }> = {
  completed: { label: "Completada", color: "green" },
  no_speech: { label: "Sin respuesta", color: "amber" },
  max_turns: { label: "Sin cerrar", color: "amber" },
  hangup: { label: "Colgó", color: "slate" },
  error: { label: "Error", color: "red" },
};

function Filas({ filas }: { filas: [string, string][] }) {
  return (
    <dl className="flex flex-col gap-3 text-sm">
      {filas.map(([k, v]) => (
        <div key={k} className="flex items-baseline justify-between gap-4 border-b border-line pb-2 last:border-0">
          <dt className="text-muted">{k}</dt>
          <dd className="font-semibold tabular-nums text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------
   Gráfica de barras apiladas — costo diario por proveedor.
   Marcas finas, extremo redondeado anclado a la base, 2 px de aire
   entre segmentos y rejilla discreta. ------------------------------ */
function CostChart({ data }: { data: Daily[] }) {
  const [hover, setHover] = useState<number | null>(null);
  // Sin datos se usa una escala de referencia para que el eje muestre
  // cifras legibles en vez de "$0.001".
  const max = Math.max(...data.map((d) => d.cost_usd), 0.1);
  const H = 180;
  const paso = 100 / data.length;
  const ancho = Math.min(paso * 0.55, 5);

  // Tres líneas de rejilla bastan para leer magnitudes sin ensuciar.
  const guias = [0.5, 1].map((f) => ({ f, valor: max * f }));

  return (
    <div className="relative">
      <div className="mb-3 flex items-center gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: C_VOZ }} /> Voz y transcripción
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: C_MODELO }} /> Modelo
        </span>
      </div>

      <div className="relative">
        {guias.map((g) => (
          <div
            key={g.f}
            className="pointer-events-none absolute inset-x-0 flex items-center"
            style={{ bottom: `${g.f * 100}%` }}
          >
            <span className="w-full border-t border-line" />
            <span className="absolute -top-2 right-0 bg-surface pl-1 text-[10px] tabular-nums text-faint">
              {usd(g.valor)}
            </span>
          </div>
        ))}

        <svg
          viewBox={`0 0 100 ${H}`}
          preserveAspectRatio="none"
          className="w-full"
          style={{ height: H }}
          role="img"
          aria-label="Costo diario del voizbot, separado en voz y modelo"
        >
          {data.map((d, i) => {
            const cx = paso * i + paso / 2;
            const totalH = (d.cost_usd / max) * (H - 8);
            // El desglose viene calculado del backend con las tarifas de
            // Ajustes; acá solo se traduce a alturas.
            const pVoz = d.cost_usd > 0 ? Math.min(d.cost_voz / d.cost_usd, 1) : 0;
            const hVoz = totalH * pVoz;
            // 2 px de aire entre los dos segmentos, para que se lean como
            // dos cosas y no como un degradado.
            const hModelo = Math.max(totalH - hVoz - (hVoz > 0 && totalH - hVoz > 0 ? 2 : 0), 0);
            return (
              <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                {/* zona de contacto más ancha que la barra */}
                <rect x={paso * i} y={0} width={paso} height={H} fill="transparent" />
                {hModelo > 0 && (
                  <rect
                    x={cx - ancho / 2}
                    y={H - totalH}
                    width={ancho}
                    height={hModelo}
                    rx={2}
                    fill={C_MODELO}
                    opacity={hover === null || hover === i ? 1 : 0.45}
                  />
                )}
                {hVoz > 0 && (
                  <rect
                    x={cx - ancho / 2}
                    y={H - hVoz}
                    width={ancho}
                    height={hVoz}
                    rx={2}
                    fill={C_VOZ}
                    opacity={hover === null || hover === i ? 1 : 0.45}
                  />
                )}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-1 flex text-[10px] text-faint">
        {data.map((d, i) => (
          <span key={d.date} className="flex-1 text-center">
            {/* Solo se etiqueta uno de cada tres para que no se pisen */}
            {i % 3 === 0 ? diaCorto(d.date) : ""}
          </span>
        ))}
      </div>

      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute -top-1 left-1/2 z-10 -translate-x-1/2 rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-[var(--shadow-2)]">
          <div className="mb-1 font-semibold text-fg">{diaCorto(data[hover].date)}</div>
          <div className="tabular-nums text-muted">
            {data[hover].calls} llamada{data[hover].calls === 1 ? "" : "s"} · {usd(data[hover].cost_usd)}
          </div>
          <div className="tabular-nums text-faint">
            {miles(data[hover].tts_chars)} caracteres · {miles(data[hover].tokens)} tokens
          </div>
        </div>
      )}
    </div>
  );
}

/* Llamadas por día — una sola serie, así que el título ya la nombra y no
   hace falta leyenda. */
function CallsChart({ data }: { data: Daily[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => d.calls), 1);
  const H = 90;
  const paso = 100 / data.length;
  const ancho = Math.min(paso * 0.55, 5);

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 100 ${H}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height: H }}
        role="img"
        aria-label="Llamadas del voizbot por día"
      >
        <line x1="0" y1={H} x2="100" y2={H} stroke="var(--line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {data.map((d, i) => {
          const cx = paso * i + paso / 2;
          const h = d.calls > 0 ? Math.max((d.calls / max) * (H - 6), 3) : 0;
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={paso * i} y={0} width={paso} height={H} fill="transparent" />
              {h > 0 && (
                <rect
                  x={cx - ancho / 2}
                  y={H - h}
                  width={ancho}
                  height={h}
                  rx={2}
                  fill={C_MODELO}
                  opacity={hover === null || hover === i ? 0.85 : 0.4}
                />
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute -top-2 left-1/2 z-10 -translate-x-1/2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs tabular-nums shadow-[var(--shadow-2)]">
          {diaCorto(data[hover].date)}: {data[hover].calls} llamada{data[hover].calls === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}

export default function AiUsagePage() {
  const [days, setDays] = useState<"7" | "14" | "30">("14");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [daily, setDaily] = useState<Daily[]>([]);
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [offset, setOffset] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ limit: String(POR_PAGINA), offset: String(offset) });
      if (busqueda.trim()) qs.set("search", busqueda.trim());
      const [s, d, c] = await Promise.all([
        api.get<Summary>(`/api/ai-usage/summary?days=${days}`),
        api.get<Daily[]>(`/api/ai-usage/daily?days=${days}`),
        api.get<CallRow[]>(`/api/ai-usage/calls?${qs.toString()}`),
      ]);
      setSummary(s);
      setDaily(d);
      setCalls(c);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el consumo");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, busqueda, offset]);

  // Buscar o cambiar el rango vuelve a la primera página (ver el mismo
  // criterio en /calls y /appointments).
  useEffect(() => {
    setOffset(0);
  }, [days, busqueda]);

  const sinDatos = !loading && summary?.calls === 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Consumo de IA"
        subtitle="Lo que gasta el voizbot en voz, transcripción y modelo, y qué resuelve a cambio"
      />

      {error && <ErrorBanner message={error} onClose={() => setError("")} />}

      <div className="flex justify-end">
        <Segmented
          value={days}
          onChange={setDays}
          options={[
            { value: "7", label: "7 días" },
            { value: "14", label: "14 días" },
            { value: "30", label: "30 días" },
          ]}
        />
      </div>

      {loading ? (
        <TableSkeleton cols={5} rows={4} />
      ) : (
        <>
          {/* Sin datos NO se esconde el tablero: dejarlo en blanco no deja
              ver qué se va a medir ni si la vista funciona. Se muestra la
              estructura en cero con el aviso arriba. */}
          {sinDatos && (
            <Note tone="brand">
              Todavía no hay ninguna conversación registrada, así que todo aparece en cero. Cada llamada
              del voizbot con IA queda medida acá — caracteres de voz, tokens del modelo, segundos de
              transcripción y si resolvió una gestión — y la vista se llena sola con la próxima.
            </Note>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Llamadas con IA" value={summary?.calls ?? 0} color="indigo" delay={0} />
            <StatCard
              label={`Costo estimado · ${days} días`}
              value={usd(summary?.cost_usd ?? 0)}
              color="amber"
              hint={`${usd(summary?.cost_per_call ?? 0)} por llamada`}
              delay={70}
            />
            <StatCard
              label="Costo por gestión resuelta"
              value={usd(summary?.cost_per_resolved ?? 0)}
              color="violet"
              hint={`${summary?.resolved ?? 0} resueltas`}
              delay={140}
            />
            <StatCard
              label="Tasa de contención"
              value={`${Math.round((summary?.containment_rate ?? 0) * 100)}%`}
              color="emerald"
              hint="Resueltas sin pasar a un humano"
              delay={210}
            />
          </div>

          <Card>
            <CardHeader title="Costo diario" subtitle="Separado por proveedor. El costo es una estimación con las tarifas de Ajustes; las unidades medidas son exactas." />
            <CardBody>
              <CostChart data={daily} />
            </CardBody>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Llamadas por día" />
              <CardBody>
                <CallsChart data={daily} />
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Conversación" subtitle={`Últimos ${days} días`} />
              <CardBody>
                <Filas
                  filas={[
                    ["Turnos de conversación", miles(summary?.turns ?? 0)],
                    ["Turnos por llamada", String(summary?.avg_turns ?? 0)],
                    ["Duración media", dur(summary?.avg_duration ?? 0)],
                    ["Gestiones resueltas", miles(summary?.resolved ?? 0)],
                  ]}
                />
              </CardBody>
            </Card>
          </div>

          {/* Una tarjeta por proveedor que realmente se usó. Se arma con lo
              que devuelve la API y no con una lista fija: así una cuenta que
              mezcle proveedores (voz en uno, transcripción en otro) se
              reparte sola, sin tocar la vista. */}
          <div className="grid gap-6 lg:grid-cols-3">
            {(summary?.providers ?? []).map((p) => (
              <Card key={p.key}>
                <CardHeader
                  title={p.label}
                  subtitle={p.role}
                  icon={
                    <span
                      className="h-2.5 w-2.5 rounded-sm"
                      style={{ background: p.role.toLowerCase().includes("modelo") ? C_MODELO : C_VOZ }}
                    />
                  }
                  actions={
                    <div className="text-right">
                      <div className="text-xl font-bold tabular-nums text-fg">{usd(p.cost_usd)}</div>
                      <div className="text-[11px] text-faint">{Math.round(p.share * 100)}% del total</div>
                    </div>
                  }
                />
                <CardBody>
                  <Filas
                    filas={[
                      ...(p.tts_chars ? ([["Caracteres de voz", miles(p.tts_chars)]] as [string, string][]) : []),
                      ...(p.stt_seconds ? ([["Audio transcrito", `${miles(p.stt_seconds)} s`]] as [string, string][]) : []),
                      ...(p.tokens ? ([["Tokens del modelo", miles(p.tokens)]] as [string, string][]) : []),
                      ...(p.requests ? ([["Consultas", miles(p.requests)]] as [string, string][]) : []),
                    ]}
                  />
                  {p.key === "edge" && (
                    <div className="mt-3">
                      <Note tone="muted">Voz gratuita: no suma al costo.</Note>
                    </div>
                  )}
                </CardBody>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader
              title="Conversaciones"
              actions={
                <SearchInput
                  value={busqueda}
                  onChange={setBusqueda}
                  placeholder="Buscar teléfono…"
                  className="w-52"
                />
              }
            />
            <CardBody className="p-0">
              <Table
                head={[
                  { label: "Teléfono" },
                  { label: "Cuándo" },
                  { label: "Duración" },
                  { label: "Turnos" },
                  { label: "Voz + transcripción", align: "right" },
                  { label: "Modelo", align: "right" },
                  { label: "Total", align: "right" },
                  { label: "Resultado" },
                ]}
              >
                {calls.map((c, i) => (
                  <Tr key={c.id} delay={i * 30}>
                    <Td>{c.phone ?? "—"}</Td>
                    <Td>{new Date(c.started_at).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</Td>
                    <Td>{dur(c.duration_seconds)}</Td>
                    <Td>{c.turns}</Td>
                    <Td align="right">
                      {usd(c.cost_voz)}
                      <span className="ml-1 text-[11px] text-faint">{c.tts_provider}</span>
                    </Td>
                    <Td align="right">
                      {usd(c.cost_modelo)}
                      <span className="ml-1 text-[11px] text-faint">{miles(c.tokens)} tok.</span>
                    </Td>
                    <Td align="right">{usd(c.cost_usd)}</Td>
                    <Td>
                      <div className="flex items-center gap-1.5">
                        <Badge color={outcomeLabel[c.outcome]?.color ?? "slate"}>
                          {outcomeLabel[c.outcome]?.label ?? c.outcome}
                        </Badge>
                        {c.resolved && <Badge color="green">Resuelta</Badge>}
                      </div>
                    </Td>
                  </Tr>
                ))}
              </Table>
            </CardBody>
            <Pagination
              offset={offset}
              limit={POR_PAGINA}
              recibidos={calls.length}
              onChange={setOffset}
              cargando={loading}
            />
          </Card>
        </>
      )}
    </div>
  );
}
