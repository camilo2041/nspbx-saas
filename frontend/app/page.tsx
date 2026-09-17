"use client";

import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";

import {
  Card,
  CardBody,
  CardHeader,
  ErrorBanner,
  PageHeader,
  Skeleton,
  StatCard,
  StatusDot,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Campaign, CallStats, Extension, PERMISOS, Recursos, Trunk, VoiceBot } from "@/lib/types";

interface FsStatus {
  version?: string;
  current_sessions?: number;
  max_sessions?: number;
  sessions_per_sec?: number;
  uptime?: string;
}

const icons = {
  trunks: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 2v6M12 16v6M4.93 4.93l4.24 4.24M14.83 14.83l4.24 4.24M2 12h6M16 12h6M4.93 19.07l4.24-4.24M14.83 9.17l4.24-4.24"
      />
    </svg>
  ),
  extensions: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.362 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0122 16.92z"
      />
    </svg>
  ),
  bots: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <path strokeLinecap="round" d="M12 8V4m0 0a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM8 13v2M16 13v2" />
    </svg>
  ),
  campaigns: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </svg>
  ),
  calls: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
      />
    </svg>
  ),
  talk: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3M12 3a9 9 0 100 18 9 9 0 000-18z" />
    </svg>
  ),
};

const QUICK_LINKS = [
  { href: "/softphone", label: "Abrir softphone", hint: "Llamar desde el navegador", permiso: PERMISOS.softphone },
  { href: "/extensions", label: "Nueva extensión", hint: "Dar de alta un teléfono", permiso: PERMISOS.telefonia },
  { href: "/calls", label: "Ver llamadas", hint: "Historial y grabaciones", permiso: PERMISOS.llamadasPropias },
  { href: "/appointments", label: "Agenda", hint: "Citas del consultorio", permiso: PERMISOS.citas },
  { href: "/campaigns", label: "Campañas", hint: "Marcación masiva", permiso: PERMISOS.campanas },
  { href: "/settings", label: "Ajustes", hint: "Dominio SIP, ESL, API keys", permiso: PERMISOS.ajustes },
];

type Tono = "ok" | "warn" | "danger";

/**
 * Medidor circular tipo panel de monitoreo (CPU/RAM/disco), en vez de
 * barras planas — mismo dato, look de sala de control. El arco se dibuja
 * con el truco clásico de stroke-dasharray/offset sobre un <circle>
 * rotado -90° para que el 0% arranque arriba, como cualquier gauge.
 */
function GaugeRing({
  value,
  tono,
  size = 108,
  grosor = 9,
  children,
}: {
  value: number;
  tono: Tono;
  size?: number;
  grosor?: number;
  children?: ReactNode;
}) {
  const radio = (size - grosor) / 2;
  const circunferencia = 2 * Math.PI * radio;
  const pct = Math.max(0, Math.min(100, value));
  const offset = circunferencia * (1 - pct / 100);
  const colorClase = tono === "danger" ? "text-danger" : tono === "warn" ? "text-warn" : "text-brand";

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radio} strokeWidth={grosor} className="fill-none stroke-surface-3" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radio}
          strokeWidth={grosor}
          strokeDasharray={circunferencia}
          strokeDashoffset={offset}
          strokeLinecap="round"
          stroke="currentColor"
          className={`fill-none ${colorClase} drop-shadow-[0_0_6px_currentColor] transition-[stroke-dashoffset,color] duration-700 ease-out`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div>
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[86px] rounded-2xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Skeleton className="h-48 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { puede, usuario } = useAuth();
  const [counts, setCounts] = useState({ trunks: 0, extensions: 0, bots: 0, campaigns: 0, running: 0 });
  const [callStats, setCallStats] = useState<CallStats | null>(null);
  const [fs, setFs] = useState<FsStatus | null>(null);
  const [recursos, setRecursos] = useState<Recursos | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // Ve telefonía/campañas/voizbots/ESL solo quien tiene permiso para
  // gestionarlos: son las mismas rutas que el backend le negaría con 403,
  // así que pedirlas para un asesor solo generaba errores en la consola
  // y una tarjeta que igual no iba a poder abrir.
  const veInfra = puede(PERMISOS.telefonia);
  const veBots = puede(PERMISOS.voizbotsVer);
  const veCampanas = puede(PERMISOS.campanas);
  const veAjustes = puede(PERMISOS.ajustes);
  const veLlamadas = puede(PERMISOS.llamadasPropias);

  useEffect(() => {
    (async () => {
      try {
        const [trunks, extensions, bots, campaigns] = await Promise.all([
          veInfra ? api.get<Trunk[]>("/api/trunks") : Promise.resolve([]),
          veInfra ? api.get<Extension[]>("/api/extensions") : Promise.resolve([]),
          veBots ? api.get<VoiceBot[]>("/api/voicebots") : Promise.resolve([]),
          veCampanas ? api.get<Campaign[]>("/api/campaigns") : Promise.resolve([]),
        ]);
        setCounts({
          trunks: trunks.length,
          extensions: extensions.length,
          bots: bots.length,
          campaigns: campaigns.length,
          running: campaigns.filter((c) => c.status === "running").length,
        });
        if (veAjustes) {
          try {
            setFs(await api.get<Record<string, string>>("/api/system/status"));
          } catch {
            setFs(null);
          }
          try {
            setRecursos(await api.get<Recursos>("/api/system/recursos"));
          } catch {
            setRecursos(null);
          }
        }
        if (veLlamadas) {
          try {
            setCallStats(await api.get<CallStats>("/api/calls/stats"));
          } catch {
            setCallStats(null);
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error de conexión");
      } finally {
        setLoading(false);
      }
    })();
  }, [veInfra, veBots, veCampanas, veAjustes, veLlamadas]);

  // CPU/RAM cambian rápido — el resto del dashboard se pide una sola vez,
  // pero esta tarjeta se queda vieja en segundos si no se refresca sola.
  useEffect(() => {
    if (!veAjustes) return;
    const t = setInterval(() => {
      api
        .get<Recursos>("/api/system/recursos")
        .then(setRecursos)
        .catch(() => {});
    }, 8000);
    return () => clearInterval(t);
  }, [veAjustes]);

  const stats = [
    veInfra && { label: "Troncales", value: counts.trunks, href: "/trunks", color: "sky" as const, icon: icons.trunks },
    veInfra && {
      label: "Extensiones",
      value: counts.extensions,
      href: "/extensions",
      color: "emerald" as const,
      icon: icons.extensions,
    },
    veBots && { label: "Voizbots", value: counts.bots, href: "/voicebots", color: "violet" as const, icon: icons.bots },
    veCampanas && {
      label: "Campañas",
      value: counts.campaigns,
      href: "/campaigns",
      color: "amber" as const,
      icon: icons.campaigns,
    },
    // Sin infraestructura que administrar (el caso del asesor), las
    // tarjetas de arriba quedan vacías. Se completa con lo que sí le
    // pertenece: sus propias llamadas — el mismo filtro que ya aplica
    // /api/calls/stats según el rol.
    veLlamadas &&
      !veInfra &&
      callStats && { label: "Mis llamadas", value: callStats.total, href: "/calls", color: "sky" as const, icon: icons.calls },
    veLlamadas &&
      !veInfra &&
      callStats && {
        label: "Minutos hablados",
        value: callStats.talk_minutes,
        href: "/calls",
        color: "emerald" as const,
        icon: icons.talk,
      },
  ].filter((s): s is Exclude<typeof s, false | null | undefined> => Boolean(s));

  const muestraMotor = veAjustes;
  const muestraCampanas = veCampanas;
  const muestraRecursos = veAjustes;
  const muestraAccesos = QUICK_LINKS.some((q) => puede(q.permiso));

  // >=90% ya es motivo de alarma real (disco a punto de llenarse, RAM al
  // límite); 70-90% es "andá mirando". Mismos cortes para las cuatro
  // barras (CPU, RAM, swap, disco) para no inventar una escala distinta
  // por métrica.
  const tonoUso = (pct: number) => (pct >= 90 ? "danger" : pct >= 70 ? "warn" : "ok");

  return (
    <div>
      <PageHeader
        title={`Hola, ${(usuario?.full_name ?? "bienvenido").split(" ")[0]}`}
        subtitle="Resumen de tu central telefónica"
      />

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} />
        </div>
      )}

      {loading ? (
        <DashboardSkeleton />
      ) : (
        <>
          {stats.length > 0 && (
            <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
              {stats.map((s, i) => (
                <StatCard
                  key={s.label}
                  label={s.label}
                  value={s.value}
                  color={s.color}
                  icon={s.icon}
                  href={s.href}
                  delay={i * 70}
                />
              ))}
            </div>
          )}

          {(muestraMotor || muestraCampanas || muestraRecursos || muestraAccesos) && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {muestraMotor && (
                <Card delay={280} className={muestraCampanas ? "lg:col-span-2" : "lg:col-span-3"}>
                  <CardHeader title="Motor telefónico" subtitle="Estado de FreeSWITCH vía ESL" />
                  <CardBody>
                    {fs ? (
                      <>
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                          {[
                            { label: "Versión", value: fs.version ?? "N/D" },
                            {
                              label: "Sesiones",
                              value: `${fs.current_sessions ?? "N/D"} / ${fs.max_sessions ?? "N/D"}`,
                            },
                            { label: "Tiempo activo", value: fs.uptime ?? "N/D" },
                          ].map((row) => (
                            <div key={row.label} className="rounded-xl border border-line bg-surface-2 px-3.5 py-3">
                              <div className="text-[11px] uppercase tracking-wide text-faint">{row.label}</div>
                              <div className="mt-1 truncate text-sm font-medium text-fg" title={String(row.value)}>
                                {row.value}
                              </div>
                            </div>
                          ))}
                        </div>
                        <div className="mt-4 flex items-center gap-2 text-xs text-muted">
                          <StatusDot color="ok" />
                          Conectado vía ESL
                        </div>
                      </>
                    ) : (
                      <div className="flex items-center gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3 text-sm text-danger-text">
                        <StatusDot color="danger" pulse={false} />
                        FreeSWITCH no responde vía ESL. Revisa host/puerto/password en Ajustes.
                      </div>
                    )}
                  </CardBody>
                </Card>
              )}

              {muestraCampanas && (
                <Card delay={350}>
                  <CardHeader title="Campañas activas" subtitle="Marcación masiva en curso" />
                  <CardBody>
                    {counts.running > 0 ? (
                      <Link
                        href="/campaigns"
                        className="flex items-center gap-3 rounded-xl border border-ok/25 bg-ok-soft px-3.5 py-3 text-sm text-ok-text transition-transform duration-200 hover:translate-x-0.5"
                      >
                        <StatusDot color="ok" />
                        <span className="font-medium">{counts.running} campaña(s) en curso</span>
                      </Link>
                    ) : (
                      <p className="rounded-xl border border-line bg-surface-2 px-3.5 py-3 text-sm text-muted">
                        No hay campañas en curso.
                      </p>
                    )}
                  </CardBody>
                </Card>
              )}

              {muestraRecursos && (
                <Card delay={390} className="lg:col-span-3 overflow-hidden">
                  <CardHeader
                    title="Recursos del servidor"
                    subtitle="CPU, memoria y disco de la máquina que hospeda todo esto"
                    actions={
                      recursos && (
                        <span className="flex items-center gap-1.5 rounded-full border border-ok/25 bg-ok-soft px-2.5 py-1 text-[11px] font-medium text-ok-text">
                          <StatusDot color="ok" />
                          En vivo
                        </span>
                      )
                    }
                  />
                  {/* Fondo con una cuadrícula fina y un resplandor de marca en
                      la esquina — el mismo dato en una tarjeta plana se lee
                      como una hoja de cálculo; esto se lee como un panel de
                      control. */}
                  <CardBody className="relative bg-surface-2/40">
                    <div
                      className="pointer-events-none absolute inset-0 opacity-[0.05]"
                      style={{
                        backgroundImage:
                          "linear-gradient(currentColor 1px, transparent 1px), linear-gradient(90deg, currentColor 1px, transparent 1px)",
                        backgroundSize: "22px 22px",
                      }}
                    />
                    <div className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full bg-brand/20 blur-3xl" />

                    {recursos ? (
                      <div className="relative flex flex-wrap gap-3">
                        <div className="flex min-w-[180px] flex-1 flex-col items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-5 shadow-[var(--shadow-1)]">
                          <GaugeRing value={recursos.cpu.porcentaje} tono={tonoUso(recursos.cpu.porcentaje)}>
                            <span className="font-mono text-2xl font-bold tabular-nums text-fg">
                              {recursos.cpu.porcentaje.toFixed(0)}
                              <span className="text-xs text-faint">%</span>
                            </span>
                          </GaugeRing>
                          <div className="text-center">
                            <div className="text-xs font-semibold text-fg">CPU</div>
                            <div className="text-[11px] text-faint">{recursos.cpu.nucleos} núcleos</div>
                          </div>
                          {/* Un núcleo a tope no se ve si solo se muestra el
                              promedio (8 núcleos al 12% de media parece
                              tranquilo aunque uno esté ahogado) — se
                              muestran todos, chiquitos, tipo ecualizador,
                              para que salte a la vista cuál. */}
                          <div className="flex h-6 w-full gap-[3px]">
                            {recursos.cpu.por_nucleo.map((n, i) => (
                              <div
                                key={i}
                                className="flex h-full flex-1 items-end overflow-hidden rounded-[2px] bg-surface-3"
                                title={`Núcleo ${i + 1}: ${n.toFixed(0)}%`}
                              >
                                <div
                                  className={`w-full rounded-[2px] transition-[height] duration-500 ${
                                    n >= 90 ? "bg-danger" : n >= 70 ? "bg-warn" : "bg-brand"
                                  }`}
                                  style={{ height: `${Math.max(8, Math.min(100, n))}%` }}
                                />
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="flex min-w-[180px] flex-1 flex-col items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-5 shadow-[var(--shadow-1)]">
                          <GaugeRing value={recursos.memoria.porcentaje} tono={tonoUso(recursos.memoria.porcentaje)}>
                            <span className="font-mono text-2xl font-bold tabular-nums text-fg">
                              {recursos.memoria.porcentaje.toFixed(0)}
                              <span className="text-xs text-faint">%</span>
                            </span>
                          </GaugeRing>
                          <div className="text-center">
                            <div className="text-xs font-semibold text-fg">Memoria</div>
                            <div className="font-mono text-[11px] text-faint">
                              {recursos.memoria.usado_gb} / {recursos.memoria.total_gb} GB
                            </div>
                          </div>
                        </div>

                        {recursos.swap.total_gb > 0 && (
                          <div className="flex min-w-[180px] flex-1 flex-col items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-5 shadow-[var(--shadow-1)]">
                            <GaugeRing value={recursos.swap.porcentaje} tono={tonoUso(recursos.swap.porcentaje)}>
                              <span className="font-mono text-2xl font-bold tabular-nums text-fg">
                                {recursos.swap.porcentaje.toFixed(0)}
                                <span className="text-xs text-faint">%</span>
                              </span>
                            </GaugeRing>
                            <div className="text-center">
                              <div className="text-xs font-semibold text-fg">Swap</div>
                              <div className="font-mono text-[11px] text-faint">
                                {recursos.swap.usado_gb} / {recursos.swap.total_gb} GB
                              </div>
                            </div>
                          </div>
                        )}

                        {recursos.discos.map((d) => (
                          <div
                            key={d.punto}
                            className="flex min-w-[180px] flex-1 flex-col items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-5 shadow-[var(--shadow-1)]"
                          >
                            <GaugeRing value={d.porcentaje} tono={tonoUso(d.porcentaje)}>
                              <span className="font-mono text-2xl font-bold tabular-nums text-fg">
                                {d.porcentaje.toFixed(0)}
                                <span className="text-xs text-faint">%</span>
                              </span>
                            </GaugeRing>
                            <div className="text-center">
                              <div className="truncate text-xs font-semibold text-fg" title={d.nombre}>
                                {d.nombre}
                              </div>
                              <div className="font-mono text-[11px] text-faint">
                                {d.usado_gb} / {d.total_gb} GB · {d.libre_gb} libres
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="relative flex items-center gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3 text-sm text-danger-text">
                        <StatusDot color="danger" pulse={false} />
                        No se pudieron leer los recursos del servidor.
                      </div>
                    )}
                  </CardBody>
                </Card>
              )}

              {muestraAccesos && (
                <Card delay={420} className="lg:col-span-3">
                  <CardHeader title="Accesos rápidos" />
                  <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {QUICK_LINKS.filter((q) => puede(q.permiso)).map((q) => (
                      <Link
                        key={q.href}
                        href={q.href}
                        className="group flex items-center justify-between gap-2 rounded-xl border border-line bg-surface-2 px-3.5 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand/40 hover:bg-surface hover:shadow-[var(--shadow-2)]"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-fg">{q.label}</span>
                          <span className="block truncate text-xs text-muted">{q.hint}</span>
                        </span>
                        <svg
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          className="h-4 w-4 shrink-0 text-faint transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-brand"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 6l6 6-6 6" />
                        </svg>
                      </Link>
                    ))}
                  </CardBody>
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
