"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Modal,
  Note,
  Pagination,
  SearchInput,
  Select,
  Spinner,
  StatCard,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { useOffsetPorFiltro } from "@/lib/paginacion";
import { api } from "@/lib/api";
import { LlamadasEnVivo } from "@/components/llamadas-en-vivo";
import { useAuth } from "@/lib/auth";
import { CallLog, CallStats, PERMISOS } from "@/lib/types";
import { tiempoCorto } from "@/lib/utils";

const estados: Record<string, { label: string; color: string }> = {
  answered: { label: "Contestada", color: "green" },
  voicemail: { label: "Dejó mensaje", color: "blue" },
  no_answer: { label: "Sin respuesta", color: "amber" },
  busy: { label: "Ocupado", color: "amber" },
  rejected: { label: "Rechazada", color: "red" },
  cancelled: { label: "Cancelada", color: "slate" },
  failed: { label: "Fallida", color: "red" },
};

type ResumenLlamada = {
  available: boolean;
  reason?: string;
  turns: number;
  outcome?: string;
  resolved: boolean;
  duration_seconds: number;
  transcript: { rol: string; texto: string; inicio?: number }[];
  summary: string | null;
  // Resumen armado con los datos del registro porque no hubo audio que
  // analizar (nadie contestó, colgaron enseguida, o el archivo ya no está).
  from_cdr?: boolean;
  note?: string;
};

/** "15/08/26, 16:03". Sin segundos ni "p. m.": el formato largo se comía
 *  207 px de la fila y empujaba la tabla al scroll horizontal. */
function fechaCorta(iso: string) {
  return new Date(iso + "Z").toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** "domingo, 17 de agosto de 2026" — encabezado de cada grupo de día. */
function fechaLarga(iso: string) {
  const texto = new Date(iso + "Z").toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** Clave estable para agrupar por día en la zona horaria local (no UTC,
 *  para que una llamada de las 11pm no se cuente en el día siguiente). */
function claveDia(iso: string) {
  const d = new Date(iso + "Z");
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** Agrupa la lista (ya viene ordenada por fecha desc del backend) en
 *  bloques consecutivos por día — misma organización que las carpetas
 *  AAAA/MM/DD donde se guardan las grabaciones, para que la tabla se
 *  navegue igual de fácil que el disco. Las llamadas sin fecha (no
 *  debería pasar, pero por si acaso) van todas juntas al final. */
function agruparPorDia(items: CallLog[]) {
  const grupos: { clave: string; fecha: string | null; llamadas: CallLog[] }[] = [];
  for (const c of items) {
    const clave = c.started_at ? claveDia(c.started_at) : "sin-fecha";
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.clave === clave) {
      ultimo.llamadas.push(c);
    } else {
      grupos.push({ clave, fecha: c.started_at, llamadas: [c] });
    }
  }
  return grupos;
}

// 25 y no 100: cada fila trae reproductor de audio y botón de resumen,
// así que cien filas eran varias pantallas de scroll. Con 25 la página
// entra de una sin desbordarse.
const POR_PAGINA = 25;

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

interface NodoDia {
  /** "2026-08-17" — mismo formato que devuelve /api/calls/dias y que
   *  espera el parámetro ?day= de /api/calls, así no hace falta
   *  convertir nada entre elegir un día y pedirlo. */
  clave: string;
  dia: number;
  total: number;
}
interface NodoMes {
  clave: string;
  mes: number;
  total: number;
  dias: NodoDia[];
}
interface NodoAnio {
  anio: number;
  total: number;
  meses: NodoMes[];
}

/** Arma el árbol Año > Mes > Día a partir de /api/calls/dias (conteos
 *  reales en la base) y NO de las llamadas ya cargadas en el navegador:
 *  con /api/calls limitado a un puñado de filas por página, un solo día
 *  activo (una campaña corriendo) ya llenaba esa página entera y los
 *  días anteriores desaparecían del árbol aunque sí tuvieran datos —
 *  confirmado comparando contra las carpetas reales en disco. */
function construirArbol(diasCount: { dia: string; total: number }[]): NodoAnio[] {
  const anios = new Map<number, Map<number, NodoDia[]>>();
  for (const { dia, total } of diasCount) {
    const [anioStr, mesStr, diaStr] = dia.split("-");
    const anio = Number(anioStr);
    const mes = Number(mesStr) - 1; // a índice 0 para MESES[]
    if (!anios.has(anio)) anios.set(anio, new Map());
    const meses = anios.get(anio)!;
    if (!meses.has(mes)) meses.set(mes, []);
    meses.get(mes)!.push({ clave: dia, dia: Number(diaStr), total });
  }
  return Array.from(anios.entries())
    .sort((a, b) => b[0] - a[0])
    .map(([anio, meses]) => {
      const mesesArr: NodoMes[] = Array.from(meses.entries())
        .sort((a, b) => b[0] - a[0])
        .map(([mes, dias]) => ({
          clave: `${anio}-${mes}`,
          mes,
          total: dias.reduce((s, d) => s + d.total, 0),
          dias: [...dias].sort((a, b) => b.dia - a.dia),
        }));
      return { anio, total: mesesArr.reduce((s, m) => s + m.total, 0), meses: mesesArr };
    });
}

function duracion(seg: number) {
  if (!seg) return "—";
  const m = Math.floor(seg / 60);
  const s = seg % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Mismo criterio que `_call_out` en backend/app/api/calls.py: "YYYYMMDD-HHMM". */
function nombreArchivo(c: CallLog) {
  const fecha = c.started_at
    ? new Date(c.started_at + "Z")
        .toISOString()
        .slice(0, 16)
        .replace(/[-:]/g, "")
        .replace("T", "-")
    : String(c.id);
  const numero = c.callee_number || c.caller_number || c.id;
  return `llamada-${fecha}-${numero}.wav`;
}

/**
 * Reproductor y descarga de la grabación.
 *
 * Un <audio src=...> o un <a href=... download> nativos nunca mandan el
 * header Authorization: el navegador hace esa petición por su cuenta, sin
 * pasar por `fetch`. Como /api/calls/{id}/recording ahora exige sesión
 * (igual que el resto de la API), esos dos elementos recibían 401 en
 * silencio — el reproductor no sonaba y el botón de descarga no hacía
 * nada, sin ningún error visible para quien hacía clic.
 *
 * La solución: traer el archivo con `api.getBlob` (que sí manda el
 * token) y dárselo al navegador como blob: URL, que sí puede usar
 * cualquier elemento nativo. Se pide una sola vez y se reutiliza tanto
 * para reproducir como para descargar.
 */
function Grabacion({ call }: { call: CallLog }) {
  const [estado, setEstado] = useState<"inicial" | "cargando" | "listo" | "error">("inicial");
  const [error, setError] = useState("");
  const blobUrlRef = useRef<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
    };
  }, []);

  const cargar = useCallback(async () => {
    if (blobUrlRef.current) return blobUrlRef.current;
    setEstado("cargando");
    setError("");
    try {
      const blob = await api.getBlob(`/api/calls/${call.id}/recording`);
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      setBlobUrl(url);
      setEstado("listo");
      return url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la grabación");
      setEstado("error");
      return null;
    }
  }, [call.id]);

  const descargar = async () => {
    const url = await cargar();
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = nombreArchivo(call);
    a.click();
  };

  if (estado === "error") {
    return (
      <span className="text-xs text-danger-text" title={error}>
        Error al cargar
      </span>
    );
  }

  return (
    <>
      {blobUrl ? (
        <audio controls autoPlay src={blobUrl} className="h-8 w-44" />
      ) : (
        <button
          type="button"
          onClick={cargar}
          disabled={estado === "cargando"}
          data-guia="llamadas:reproducir"
          title="Reproducir grabación"
          aria-label="Reproducir grabación"
          className="press inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2 disabled:opacity-50"
        >
          {estado === "cargando" ? (
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
      )}
      <button
        type="button"
        onClick={descargar}
        title="Descargar grabación"
        aria-label="Descargar grabación"
        className="press inline-flex shrink-0 items-center rounded-lg border border-line p-1.5 text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 19h16" />
        </svg>
      </button>
    </>
  );
}

function Chevron({ abierto }: { abierto: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      className={`h-3 w-3 shrink-0 text-faint transition-transform ${abierto ? "rotate-90" : ""}`}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  );
}

/**
 * Panel lateral tipo explorador de archivos: Año > Mes > Día, plegable.
 * Refleja la misma organización que las carpetas donde se guardan las
 * grabaciones (AAAA/MM/DD) — pedido explícito para navegar la tabla igual
 * de fácil que el disco, en vez de un simple separador de fecha.
 */
function ArbolFechas({
  arbol,
  diaSeleccionado,
  onSeleccionarDia,
  expandedAnios,
  expandedMeses,
  onToggleAnio,
  onToggleMes,
}: {
  arbol: NodoAnio[];
  diaSeleccionado: string | null;
  onSeleccionarDia: (clave: string | null) => void;
  expandedAnios: Set<number>;
  expandedMeses: Set<string>;
  onToggleAnio: (anio: number) => void;
  onToggleMes: (clave: string) => void;
}) {
  const totalGeneral = arbol.reduce((s, a) => s + a.total, 0);
  return (
    <nav className="max-h-[70vh] w-60 shrink-0 overflow-y-auto border-r border-line py-2 text-sm">
      <button
        type="button"
        onClick={() => onSeleccionarDia(null)}
        className={`flex w-full items-center justify-between gap-2 px-4 py-1.5 text-left transition-colors hover:bg-surface-2 ${
          diaSeleccionado === null ? "bg-brand-soft font-medium text-brand-text" : "text-fg-soft"
        }`}
      >
        <span className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5 shrink-0">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7l2-3h5l2 2h9v11a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
          </svg>
          Todas
        </span>
        <span className="text-xs text-faint">{totalGeneral}</span>
      </button>

      {arbol.map((nodoAnio) => {
        const anioAbierto = expandedAnios.has(nodoAnio.anio);
        return (
          <div key={nodoAnio.anio}>
            <button
              type="button"
              onClick={() => onToggleAnio(nodoAnio.anio)}
              className="flex w-full items-center justify-between gap-2 px-4 py-1.5 text-left font-medium text-fg-soft transition-colors hover:bg-surface-2"
            >
              <span className="flex items-center gap-1.5">
                <Chevron abierto={anioAbierto} />
                {nodoAnio.anio}
              </span>
              <span className="text-xs text-faint">{nodoAnio.total}</span>
            </button>
            {anioAbierto &&
              nodoAnio.meses.map((nodoMes) => {
                const mesAbierto = expandedMeses.has(nodoMes.clave);
                return (
                  <div key={nodoMes.clave}>
                    <button
                      type="button"
                      onClick={() => onToggleMes(nodoMes.clave)}
                      className="flex w-full items-center justify-between gap-2 py-1.5 pl-8 pr-4 text-left text-fg-soft transition-colors hover:bg-surface-2"
                    >
                      <span className="flex items-center gap-1.5 capitalize">
                        <Chevron abierto={mesAbierto} />
                        {MESES[nodoMes.mes]}
                      </span>
                      <span className="text-xs text-faint">{nodoMes.total}</span>
                    </button>
                    {mesAbierto &&
                      nodoMes.dias.map((nodoDia) => (
                        <button
                          key={nodoDia.clave}
                          type="button"
                          onClick={() => onSeleccionarDia(nodoDia.clave)}
                          className={`flex w-full items-center justify-between gap-2 py-1.5 pl-14 pr-4 text-left transition-colors hover:bg-surface-2 ${
                            diaSeleccionado === nodoDia.clave
                              ? "bg-brand-soft font-medium text-brand-text"
                              : "text-muted"
                          }`}
                        >
                          <span>{nodoDia.dia}</span>
                          <span className="text-xs text-faint">{nodoDia.total}</span>
                        </button>
                      ))}
                  </div>
                );
              })}
          </div>
        );
      })}
    </nav>
  );
}

export default function CallsPage() {
  const { puede } = useAuth();
  const [items, setItems] = useState<CallLog[]>([]);
  const [stats, setStats] = useState<CallStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [resumenDe, setResumenDe] = useState<CallLog | null>(null);
  const [resumen, setResumen] = useState<ResumenLlamada | null>(null);
  const [cargandoResumen, setCargandoResumen] = useState(false);

  // Árbol de fechas (panel izquierdo). `null` en diaSeleccionado = "Todas".
  const [diaSeleccionado, setDiaSeleccionado] = useState<string | null>(null);
  const [offset, setOffset] = useOffsetPorFiltro([direction, status, search, diaSeleccionado]);
  const [diasCount, setDiasCount] = useState<{ dia: string; total: number }[]>([]);
  const [expandedAnios, setExpandedAnios] = useState<Set<number>>(new Set());
  const [expandedMeses, setExpandedMeses] = useState<Set<string>>(new Set());
  // Para abrir el año/mes más reciente y seleccionar su día una sola vez,
  // al llegar los primeros datos — sin este flag, el refresco automático
  // cada 15s reventaba la selección/expansión que el usuario ya había
  // hecho a mano cada vez que `diasCount` cambiaba de referencia.
  const inicializadoRef = useRef(false);

  const loadDias = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (direction) qs.set("direction", direction);
      if (status) qs.set("status", status);
      if (search.trim()) qs.set("search", search.trim());
      const conteos = await api.get<{ dia: string; total: number }[]>(`/api/calls/dias?${qs.toString()}`);
      setDiasCount(conteos);

      if (!inicializadoRef.current && conteos.length > 0) {
        inicializadoRef.current = true;
        const arbol = construirArbol(conteos);
        const primerAnio = arbol[0];
        const primerMes = primerAnio?.meses[0];
        if (primerAnio) setExpandedAnios(new Set([primerAnio.anio]));
        if (primerMes) {
          setExpandedMeses(new Set([primerMes.clave]));
          if (primerMes.dias[0]) setDiaSeleccionado(primerMes.dias[0].clave);
        }
      }
    } catch {
      // El árbol es un plus visual — si falla, la tabla de abajo (con
      // "Todas") sigue funcionando igual.
    }
  }, [direction, status, search]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar o al cambiar los filtros
    loadDias();
  }, [loadDias]);

  const toggleAnio = (anio: number) => {
    setExpandedAnios((prev) => {
      const next = new Set(prev);
      if (next.has(anio)) next.delete(anio);
      else next.add(anio);
      return next;
    });
  };
  const toggleMes = (clave: string) => {
    setExpandedMeses((prev) => {
      const next = new Set(prev);
      if (next.has(clave)) next.delete(clave);
      else next.add(clave);
      return next;
    });
  };

  const verResumen = async (c: CallLog) => {
    setResumenDe(c);
    setResumen(null);
    setCargandoResumen(true);
    try {
      setResumen(await api.get<ResumenLlamada>(`/api/calls/${c.id}/summary`));
    } catch (e) {
      setResumen({
        available: false,
        reason: e instanceof Error ? e.message : "No se pudo cargar el resumen",
        turns: 0,
        resolved: false,
        duration_seconds: 0,
        transcript: [],
        summary: null,
      });
    } finally {
      setCargandoResumen(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (direction) qs.set("direction", direction);
      if (status) qs.set("status", status);
      if (search.trim()) qs.set("search", search.trim());
      // El día elegido se manda como filtro al backend (?day=), no se
      // recorta del lado del cliente: eso era lo que hacía desaparecer
      // días del árbol cuando uno solo pasaba del tope de la página.
      if (diaSeleccionado) qs.set("day", diaSeleccionado);
      // Se pagina SIEMPRE, también dentro de un día. Se había excluido
      // el día puntual dando por hecho que "un día ya está acotado por
      // naturaleza" — falso: con una campaña corriendo, un solo día son
      // 150+ llamadas y la vista se iba de largo sin forma de navegarla.
      qs.set("limit", String(POR_PAGINA));
      qs.set("offset", String(offset));
      const [calls, s] = await Promise.all([
        api.get<CallLog[]>(`/api/calls?${qs.toString()}`),
        api.get<CallStats>("/api/calls/stats"),
      ]);
      setItems(calls);
      setStats(s);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [direction, status, search, diaSeleccionado, offset]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar o al cambiar los filtros
    load();
  }, [load]);

  // Refresco automático: las llamadas entran solas mientras se mira la pantalla.
  useEffect(() => {
    const t = setInterval(() => {
      load();
      loadDias();
    }, 15000);
    return () => clearInterval(t);
  }, [load, loadDias]);

  const arbol = construirArbol(diasCount);

  // Total de la selección actual, sacado de /api/calls/dias (que ya
  // viene filtrado por los mismos criterios). Hace falta porque
  // items.length ahora es solo la página visible: decir "25 mostradas"
  // sin el total no dice si faltan 3 o 3000.
  const totalSeleccion =
    diaSeleccionado === null
      ? diasCount.reduce((s, d) => s + d.total, 0)
      : (diasCount.find((d) => d.dia === diaSeleccionado)?.total ?? items.length);

  return (
    <div>
      <PageHeader title="Llamadas" subtitle="Historial de todas las llamadas entrantes y salientes" />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Llamadas totales" value={stats.total} color="sky" delay={0} />
          <StatCard
            label="Contestadas"
            value={stats.answered}
            color="emerald"
            delay={70}
            hint={stats.ring_promedio_s !== null ? `Ring promedio ${tiempoCorto(stats.ring_promedio_s)}` : undefined}
          />
          <StatCard
            label="Sin respuesta / ocupado"
            value={stats.no_answer + stats.busy}
            color="amber"
            delay={140}
          />
          <StatCard
            label="Minutos hablados"
            value={stats.talk_minutes}
            color="violet"
            delay={210}
            hint={stats.hablado_promedio_s !== null ? `Promedio ${tiempoCorto(stats.hablado_promedio_s)} por llamada` : undefined}
          />
        </div>
      )}

      {puede(PERMISOS.llamadasTodas) && <LlamadasEnVivo />}

      <Card>
        <CardHeader
          title="Registro de llamadas"
          subtitle={`${totalSeleccion} llamada(s) en la selección — se actualiza solo cada 15s`}
          actions={
            <div className="flex flex-wrap items-end gap-2">
              <SearchInput value={search} onChange={setSearch} placeholder="Buscar número…" className="w-48" />
              <div className="w-40">
                <Select
                  label=""
                  value={direction}
                  onChange={setDirection}
                  placeholder="Todas"
                  options={[
                    { value: "inbound", label: "Entrantes" },
                    { value: "outbound", label: "Salientes" },
                  ]}
                />
              </div>
              <div className="w-44">
                <Select
                  label=""
                  value={status}
                  onChange={setStatus}
                  placeholder="Cualquier estado"
                  options={Object.entries(estados).map(([v, m]) => ({ value: v, label: m.label }))}
                />
              </div>
            </div>
          }
        />
        {loading && diasCount.length === 0 ? (
          <TableSkeleton cols={8} />
        ) : diasCount.length === 0 ? (
          <EmptyState
            title="No hay llamadas registradas"
            hint="El historial se llena solo con cada llamada que entra o sale del sistema."
          />
        ) : (
          <div className="flex">
            <ArbolFechas
              arbol={arbol}
              diaSeleccionado={diaSeleccionado}
              onSeleccionarDia={setDiaSeleccionado}
              expandedAnios={expandedAnios}
              expandedMeses={expandedMeses}
              onToggleAnio={toggleAnio}
              onToggleMes={toggleMes}
            />
            <div className="min-w-0 flex-1 overflow-x-auto">
              {items.length === 0 ? (
                <div className="p-8">
                  <EmptyState title="Sin llamadas ese día" hint="Elegí otro día del panel, o «Todas» para ver el historial completo." />
                </div>
              ) : (
          <Table
            head={["Fecha", "Tipo", "Origen", "Destino", "Total", "Hablado", "Estado", "Grabación"]}
          >
            {agruparPorDia(items).map((grupo, gi) => (
              <Fragment key={grupo.clave}>
                <tr className="sticky top-0 z-10 bg-surface-2/95 backdrop-blur">
                  <td colSpan={8} className="px-5 py-2 text-xs font-semibold text-muted">
                    {grupo.fecha ? fechaLarga(grupo.fecha) : "Sin fecha"}
                    <span className="ml-2 font-normal text-faint">
                      {grupo.llamadas.length} llamada{grupo.llamadas.length === 1 ? "" : "s"}
                    </span>
                  </td>
                </tr>
                {grupo.llamadas.map((c, i) => {
                  const e = estados[c.status] ?? { label: c.status, color: "slate" };
                  return (
                    <Tr key={c.id} delay={gi === 0 ? Math.min(i, 12) * 30 : 0}>
                      <Td className="whitespace-nowrap">
                        {c.started_at ? fechaCorta(c.started_at) : "—"}
                      </Td>
                      <Td>
                        <Badge color={c.direction === "inbound" ? "blue" : "violet"}>
                          {c.direction === "inbound" ? "Entrante" : "Saliente"}
                        </Badge>
                      </Td>
                      <Td mono>
                        {c.caller_number || "—"}
                        {c.caller_name && c.caller_name !== c.caller_number && (
                          <span className="ml-1 font-sans text-xs text-faint">({c.caller_name})</span>
                        )}
                      </Td>
                      <Td mono>{c.callee_number || "—"}</Td>
                      <Td muted>
                        {duracion(c.duration)}
                        {/* El timbre va bajo el total y no en columna aparte:
                            la tabla ya está al límite de ancho. */}
                        {c.ring_ms !== null && (
                          <span className="block text-[11px] text-faint" title="Tiempo de timbre">
                            ring {tiempoCorto(c.ring_ms / 1000)}
                          </span>
                        )}
                      </Td>
                      <Td muted>{duracion(c.billsec)}</Td>
                      <Td>
                        <Badge color={e.color} dot>
                          {e.label}
                        </Badge>
                      </Td>
                      <Td>
                        <div className="flex items-center gap-2">
                          {/* El resumen va junto a la grabación y no en una
                              columna aparte: con nueve columnas y un
                              reproductor de 176 px, la tabla se desbordaba. */}
                          <button
                            type="button"
                            onClick={() => verResumen(c)}
                            title="Ver qué pasó en la llamada"
                            className="press inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-xs font-medium text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h8M8 14h5M4 5h16v12H9l-5 4z" />
                            </svg>
                            Resumen
                          </button>
                          {c.audio_mos != null && (
                            <span
                              title={`Calidad del audio: MOS ${c.audio_mos.toFixed(2)} de 5${c.audio_perdida != null ? `, ${c.audio_perdida}% de paquetes perdidos` : ""}${c.troncal ? ` · ${c.troncal}` : ""}`}
                              aria-label={`Calidad del audio ${c.audio_mos.toFixed(1)} de 5`}
                              className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${c.audio_mos >= 4 ? "bg-ok" : c.audio_mos >= 3.5 ? "bg-warn" : "bg-danger"}`}
                            />
                          )}
                          {c.has_recording && puede(PERMISOS.llamadasTodas) && (
                            <button
                              type="button"
                              onClick={async () => {
                                const r = await api.put<CallLog>(`/api/calls/${c.id}/conservar`, { conservar: !c.conservar }).catch(() => null);
                                if (r) setItems((xs) => xs.map((x) => (x.id === c.id ? { ...x, conservar: r.conservar } : x)));
                              }}
                              title={c.conservar ? "Se conserva aunque pase la retención. Clic para quitar." : "Conservar: no se borra con la retención (un reclamo, una auditoría)"}
                              aria-pressed={!!c.conservar}
                              className={`press shrink-0 rounded-lg border px-2 py-1 text-xs font-medium transition-colors ${
                                c.conservar ? "border-brand bg-brand-soft text-brand-text" : "border-line text-fg-soft hover:border-line-strong"
                              }`}
                            >
                              {c.conservar ? "Conservada" : "Conservar"}
                            </button>
                          )}
                          {c.has_recording ? (
                            <Grabacion call={c} />
                          ) : (
                            <span className="text-faint">Sin grabación</span>
                          )}
                        </div>
                      </Td>
                    </Tr>
                  );
                })}
              </Fragment>
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
            </div>
          </div>
        )}
      </Card>

      <Modal
        open={!!resumenDe}
        onClose={() => setResumenDe(null)}
        title={`Llamada con ${resumenDe?.callee_number || resumenDe?.caller_number || ""}`}
      >
        {cargandoResumen ? (
          <div className="flex items-center gap-3 py-8 text-sm text-muted">
            <Spinner /> Leyendo la conversación…
          </div>
        ) : !resumen?.available ? (
          <Note tone="muted">{resumen?.reason ?? "No hay información de esta llamada."}</Note>
        ) : (
          <div className="flex flex-col gap-4">
            {resumen.summary ? (
              <div className="rounded-xl border border-brand/25 bg-brand-soft p-3.5 text-sm leading-relaxed text-brand-text">
                {resumen.summary}
              </div>
            ) : (
              <Note tone="warn">{resumen.reason ?? "No se pudo generar el resumen."}</Note>
            )}

            {resumen.note && <Note tone="muted">{resumen.note}</Note>}

            {/* Las etiquetas de turnos y gestión solo tienen sentido si la
                llamada pasó por el bot. En una que nadie contestó, mostrar
                "0 turnos · sin gestión" no informa nada y confunde. */}
            <div className="flex flex-wrap gap-2 text-xs">
              {resumen.turns > 0 && (
                <>
                  <Badge color={resumen.resolved ? "green" : "slate"}>
                    {resumen.resolved ? "Gestión resuelta" : "Sin gestión"}
                  </Badge>
                  <Badge color="blue">{resumen.turns} turnos</Badge>
                </>
              )}
              {resumen.duration_seconds > 0 && (
                <Badge color="slate">{duracion(resumen.duration_seconds)} hablados</Badge>
              )}
              {resumen.from_cdr && <Badge color="amber">Sin grabación que analizar</Badge>}
            </div>

            {resumen.transcript.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-medium text-muted">Conversación</div>
              <div className="flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
                {/* La transcripción viene con los hablantes numerados por
                    diarización. El 0 suele ser quien habla primero (el
                    bot); se alinean a lados distintos para poder seguir
                    el ida y vuelta sin leer cada línea. */}
                {resumen.transcript.map((t, i) => (
                  <div
                    key={i}
                    className={
                      t.rol.endsWith("0")
                        ? "self-start max-w-[85%] rounded-xl rounded-bl-sm bg-surface-3 px-3 py-2 text-sm text-fg-soft"
                        : "self-end max-w-[85%] rounded-xl rounded-br-sm bg-brand-soft px-3 py-2 text-sm text-brand-text"
                    }
                  >
                    {t.inicio !== undefined && (
                      <span className="mr-1.5 text-[10px] tabular-nums opacity-60">
                        {Math.floor(t.inicio / 60)}:{String(Math.round(t.inicio % 60)).padStart(2, "0")}
                      </span>
                    )}
                    {t.texto}
                  </div>
                ))}
              </div>
            </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
