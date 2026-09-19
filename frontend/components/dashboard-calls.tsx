"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AnimatedNumber, Card, CardBody, CardHeader, Skeleton, StatusDot } from "@/components/ui";
import { api } from "@/lib/api";
import { CallLog, CallStats } from "@/lib/types";

interface Punto {
  dia: string;
  total: number;
  answered: number;
  missed: number;
}

type Serie = "total" | "answered" | "missed";

const REFRESCO_MS = 15000;
const RANGOS = [7, 14, 30] as const;
const SERIES: { id: Serie; label: string; color: string }[] = [
  { id: "total", label: "Todas", color: "var(--brand)" },
  { id: "answered", label: "Contestadas", color: "var(--ok)" },
  { id: "missed", label: "Perdidas", color: "var(--danger)" },
];

const ESTADO: Record<string, { label: string; tono: string }> = {
  answered: { label: "Contestada", tono: "bg-ok-soft text-ok-text" },
  no_answer: { label: "Sin respuesta", tono: "bg-warn-soft text-warn-text" },
  busy: { label: "Ocupado", tono: "bg-warn-soft text-warn-text" },
  failed: { label: "Fallida", tono: "bg-danger-soft text-danger-text" },
  rejected: { label: "Rechazada", tono: "bg-danger-soft text-danger-text" },
  cancelled: { label: "Cancelada", tono: "bg-surface-3 text-muted" },
};

const fechaCorta = (iso: string) => {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
};

function hace(iso: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime()) / 1000);
  if (s < 60) return "ahora";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

function Grafica({ datos, serie }: { datos: Punto[]; serie: Serie }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640;
  const H = 200;
  const P = { l: 30, r: 10, t: 14, b: 26 };
  const max = Math.max(4, ...datos.map((d) => d[serie]));
  const tope = Math.ceil(max / 4) * 4;
  const paso = (W - P.l - P.r) / datos.length;
  const color = SERIES.find((s) => s.id === serie)!.color;
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / tope);
  const cada = datos.length > 14 ? 5 : datos.length > 7 ? 2 : 1;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Llamadas por día">
        {[0, 1, 2, 3, 4].map((i) => {
          const v = (tope / 4) * i;
          return (
            <g key={i}>
              <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeDasharray={i ? "3 4" : undefined} />
              <text x={P.l - 6} y={y(v) + 3} textAnchor="end" fontSize="9" fill="var(--faint)">
                {Math.round(v)}
              </text>
            </g>
          );
        })}
        {datos.map((d, i) => {
          const alto = Math.max(0, (H - P.t - P.b) * (d[serie] / tope));
          const ancho = Math.min(28, paso * 0.62);
          const x = P.l + paso * i + (paso - ancho) / 2;
          return (
            <g key={d.dia} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0}>
              <rect x={P.l + paso * i} y={P.t} width={paso} height={H - P.t - P.b} fill="transparent" />
              <rect
                x={x}
                y={H - P.b - alto}
                width={ancho}
                height={alto}
                rx="4"
                fill={color}
                opacity={hover === null || hover === i ? 0.95 : 0.35}
                className="transition-[opacity,y,height] duration-500"
              />
              {i % cada === 0 && (
                <text x={P.l + paso * i + paso / 2} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--faint)">
                  {fechaCorta(d.dia)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-xl border border-line bg-surface px-3 py-2 text-[11px] shadow-[var(--shadow-2)]"
          style={{ left: `${((P.l + paso * hover + paso / 2) / W) * 100}%` }}
        >
          <div className="mb-1 font-semibold text-fg">{fechaCorta(datos[hover].dia)}</div>
          <div className="text-fg-soft">Total: <b>{datos[hover].total}</b></div>
          <div className="text-ok-text">Contestadas: <b>{datos[hover].answered}</b></div>
          <div className="text-danger-text">Perdidas: <b>{datos[hover].missed}</b></div>
        </div>
      )}
    </div>
  );
}

function Dona({ pct }: { pct: number }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-32 w-32 shrink-0">
      <svg viewBox="0 0 120 120" className="-rotate-90">
        <circle cx="60" cy="60" r={r} strokeWidth="11" className="fill-none stroke-surface-3" />
        <circle
          cx="60"
          cy="60"
          r={r}
          strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.max(0, Math.min(100, pct)) / 100)}
          className="fill-none stroke-ok transition-[stroke-dashoffset] duration-1000 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold tabular-nums text-fg">
          <AnimatedNumber value={Math.round(pct)} />
          <span className="text-xs text-faint">%</span>
        </span>
        <span className="text-[10px] uppercase tracking-wide text-faint">contestadas</span>
      </div>
    </div>
  );
}

export function DashboardCalls({ stats }: { stats: CallStats | null }) {
  const [dias, setDias] = useState<(typeof RANGOS)[number]>(7);
  const [serie, setSerie] = useState<Serie>("total");
  const [datos, setDatos] = useState<Punto[] | null>(null);
  const [recientes, setRecientes] = useState<CallLog[]>([]);
  const [actualizado, setActualizado] = useState<number | null>(null);
  const [cargando, setCargando] = useState(false);
  const [ahora, setAhora] = useState(0);

  const cargar = useCallback(async (d: number) => {
    try {
      const [s, r] = await Promise.all([
        api.get<Punto[]>(`/api/calls/serie?dias=${d}`),
        api.get<CallLog[]>("/api/calls?limit=6"),
      ]);
      setDatos(s);
      setRecientes(r);
      setActualizado(Date.now());
      setAhora(Date.now());
    } catch {
      /* el resto del dashboard sigue; la tarjeta conserva lo último que tuvo */
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    // Carga inicial y al cambiar el rango: sincroniza con la API (los setState ocurren tras el await).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar(dias);
  }, [cargar, dias]);

  // Refresco en vivo, solo con la pestaña visible (no gasta con la pestaña oculta).
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === "visible") cargar(dias);
      setAhora(Date.now());
    }, REFRESCO_MS);
    return () => clearInterval(t);
  }, [cargar, dias]);

  const total = datos?.reduce((a, d) => a + d.total, 0) ?? 0;
  const contestadas = datos?.reduce((a, d) => a + d.answered, 0) ?? 0;
  const pct = total ? (contestadas / total) * 100 : 0;
  const segs = actualizado && ahora ? Math.max(0, Math.round((ahora - actualizado) / 1000)) : null;

  return (
    <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card delay={120} className="lg:col-span-2">
        <CardHeader
          title="Llamadas"
          subtitle={`Últimos ${dias} días`}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-xl border border-line bg-surface-2 p-0.5" role="tablist" aria-label="Serie">
                {SERIES.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    role="tab"
                    aria-selected={serie === s.id}
                    onClick={() => setSerie(s.id)}
                    className={`press rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors ${
                      serie === s.id ? "bg-surface text-fg shadow-[var(--shadow-1)]" : "text-muted hover:text-fg"
                    }`}
                  >
                    <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: s.color }} />
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="flex rounded-xl border border-line bg-surface-2 p-0.5">
                {RANGOS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setDias(r)}
                    aria-pressed={dias === r}
                    className={`press rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors ${
                      dias === r ? "bg-surface text-fg shadow-[var(--shadow-1)]" : "text-muted hover:text-fg"
                    }`}
                  >
                    {r}d
                  </button>
                ))}
              </div>
            </div>
          }
        />
        <CardBody>
          {datos ? <Grafica datos={datos} serie={serie} /> : <Skeleton className="h-[200px] rounded-xl" />}
        </CardBody>
      </Card>

      <Card delay={180}>
        <CardHeader title="Atención" subtitle={`Tasa de respuesta · ${dias} días`} />
        <CardBody className="flex flex-col items-center gap-4">
          <Dona pct={pct} />
          <div className="grid w-full grid-cols-3 gap-2 text-center">
            {[
              { l: "Total", v: total, c: "text-fg" },
              { l: "Contestadas", v: contestadas, c: "text-ok-text" },
              { l: "Perdidas", v: total - contestadas, c: "text-danger-text" },
            ].map((k) => (
              <div key={k.l} className="rounded-xl border border-line bg-surface-2 px-2 py-2">
                <div className={`text-lg font-bold tabular-nums ${k.c}`}>
                  <AnimatedNumber value={k.v} />
                </div>
                <div className="text-[10px] uppercase tracking-wide text-faint">{k.l}</div>
              </div>
            ))}
          </div>
          {stats && (
            <div className="text-[11px] text-faint">
              Histórico: {stats.total} llamadas · {stats.talk_minutes} min hablados
            </div>
          )}
        </CardBody>
      </Card>

      <Card delay={240} className="lg:col-span-3">
        <CardHeader
          title="Actividad reciente"
          subtitle="Las últimas llamadas"
          actions={
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-[11px] text-faint">
                <StatusDot color={cargando ? "warn" : "ok"} pulse={cargando} />
                {segs === null ? "Cargando…" : segs < 5 ? "Actualizado ahora" : `Actualizado hace ${segs}s`}
              </span>
              <button
                type="button"
                onClick={() => {
                  setCargando(true);
                  cargar(dias);
                }}
                disabled={cargando}
                aria-label="Actualizar"
                title="Actualizar"
                className="press rounded-lg p-1.5 text-faint transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-4 w-4 ${cargando ? "animate-spin" : ""}`}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v6h6M20 20v-6h-6M20 10A8 8 0 006.3 6.3L4 10m16 4l-2.3 3.7A8 8 0 014 14" />
                </svg>
              </button>
            </div>
          }
        />
        <div className="divide-y divide-line">
          {recientes.length === 0 && (
            <div className="px-5 py-8 text-center text-sm text-muted">{datos ? "Aún no hay llamadas." : "Cargando…"}</div>
          )}
          {recientes.map((c) => {
            const e = ESTADO[c.status] ?? { label: c.status, tono: "bg-surface-3 text-muted" };
            const entrante = c.direction === "inbound";
            return (
              <Link
                key={c.id}
                href="/calls"
                className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-surface-2"
              >
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${entrante ? "bg-info-soft text-info-text" : "bg-brand-soft text-brand-text"}`}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d={entrante ? "M7 7l10 10M17 8v9H8" : "M17 17L7 7M8 7h9v9"} />
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-fg">
                    {entrante ? c.caller_name || c.caller_number || "Desconocido" : c.callee_number || "—"}
                  </div>
                  <div className="text-[11px] text-faint">
                    {entrante ? "Entrante" : "Saliente"} · {hace(c.started_at)}
                    {c.billsec > 0 && ` · ${Math.floor(c.billsec / 60)}:${String(c.billsec % 60).padStart(2, "0")}`}
                  </div>
                </div>
                <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${e.tono}`}>{e.label}</span>
              </Link>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
