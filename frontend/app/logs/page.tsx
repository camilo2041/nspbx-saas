"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Card, CardHeader, PageHeader, Select } from "@/components/ui";
import { getToken, WS_URL } from "@/lib/api";

const NIVELES = [
  { value: "debug", label: "Debug (todo)" },
  { value: "info", label: "Info" },
  { value: "notice", label: "Notice" },
  { value: "warning", label: "Warning" },
  { value: "err", label: "Error" },
  { value: "crit", label: "Crítico" },
];

// Tope de líneas retenidas en el navegador — sin esto, dejar la pestaña
// abierta un buen rato (sobre todo en "debug", que es MUY verboso) crece
// sin límite hasta comerse la memoria de la pestaña.
const MAX_LINEAS = 4000;

type Estado = "conectando" | "conectado" | "reconectando" | "sin_acceso";

/** Colorea por severidad, igual que uno lee `fs_cli` a simple vista. */
function claseLinea(linea: string): string {
  if (/\[(ERR|CRIT|ALERT)\]/.test(linea)) return "text-danger-text";
  if (/\[WARNING\]/.test(linea)) return "text-warn-text";
  if (/\[NOTICE\]/.test(linea)) return "text-brand-text";
  if (/\[DEBUG\]/.test(linea)) return "text-faint";
  return "text-fg-soft";
}

export default function LogsPage() {
  const [lineas, setLineas] = useState<string[]>([]);
  const [nivel, setNivel] = useState("info");
  const [estado, setEstado] = useState<Estado>("conectando");
  const [pausado, setPausado] = useState(false);
  const [filtro, setFiltro] = useState("");
  const [pendientes, setPendientes] = useState(0);

  const bufferRef = useRef<string[]>([]);
  const pausadoRef = useRef(false);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contenedorRef = useRef<HTMLDivElement | null>(null);
  const autoScrollRef = useRef(true);

  useEffect(() => {
    pausadoRef.current = pausado;
  }, [pausado]);

  // Vuelca el buffer a React cada ~200ms en vez de en cada mensaje: a
  // nivel "debug" FreeSWITCH puede mandar decenas de líneas por segundo
  // y renderizar una por una dejaba la pestaña sin aire.
  const flush = useCallback(() => {
    if (bufferRef.current.length === 0) return;
    if (pausadoRef.current) {
      setPendientes((p) => p + bufferRef.current.length);
      bufferRef.current = [];
      return;
    }
    setLineas((prev) => {
      const combinado = [...prev, ...bufferRef.current];
      bufferRef.current = [];
      return combinado.length > MAX_LINEAS ? combinado.slice(combinado.length - MAX_LINEAS) : combinado;
    });
  }, []);

  useEffect(() => {
    let cerrado = false;
    let reintentoTimer: ReturnType<typeof setTimeout> | null = null;

    const conectar = () => {
      if (cerrado) return;
      setEstado((prev) => (prev === "conectado" ? "reconectando" : "conectando"));
      const token = getToken() ?? "";
      const ws = new WebSocket(`${WS_URL}/ws/logs?token=${encodeURIComponent(token)}&level=${nivel}`);
      wsRef.current = ws;

      ws.onopen = () => setEstado("conectado");
      ws.onmessage = (ev) => {
        bufferRef.current.push(ev.data as string);
      };
      ws.onclose = (ev) => {
        if (cerrado) return;
        // 4401/4403: el backend NIEGA el acceso (sin permiso, o los logs son de toda
        // la plataforma y hay varias empresas). Reintentar cada 2 s no serviría de nada.
        if (ev.code === 4401 || ev.code === 4403) {
          setEstado("sin_acceso");
          return;
        }
        setEstado("reconectando");
        reintentoTimer = setTimeout(conectar, 2000);
      };
      ws.onerror = () => ws.close();
    };

    conectar();
    timerRef.current = setInterval(flush, 200);

    return () => {
      cerrado = true;
      if (reintentoTimer) clearTimeout(reintentoTimer);
      if (timerRef.current) clearInterval(timerRef.current);
      wsRef.current?.close();
    };
    // Cambiar de nivel reconecta desde cero: FreeSWITCH filtra en origen,
    // no tiene sentido pedir "info" y filtrar "debug" del lado del navegador.
  }, [nivel, flush]);

  // Autoscroll solo si ya se estaba al final — igual que una terminal:
  // si alguien subió a leer algo viejo, no se lo arrancamos de las manos
  // con cada línea nueva.
  useEffect(() => {
    const el = contenedorRef.current;
    if (el && autoScrollRef.current) el.scrollTop = el.scrollHeight;
  }, [lineas]);

  const alScrollear = () => {
    const el = contenedorRef.current;
    if (!el) return;
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const reanudar = () => {
    setPausado(false);
    setPendientes(0);
    autoScrollRef.current = true;
    flush();
  };

  const limpiar = () => {
    setLineas([]);
    bufferRef.current = [];
    setPendientes(0);
  };

  const estadoInfo: Record<Estado, { label: string; color: string }> = {
    conectado: { label: "En vivo", color: "green" },
    conectando: { label: "Conectando…", color: "amber" },
    reconectando: { label: "Reconectando…", color: "amber" },
    sin_acceso: { label: "Sin acceso", color: "red" },
  };
  const e = estadoInfo[estado];

  const visibles = filtro.trim()
    ? lineas.filter((l) => l.toLowerCase().includes(filtro.toLowerCase()))
    : lineas;

  return (
    <div>
      <PageHeader
        title="Logs"
        subtitle="Consola en vivo de FreeSWITCH — lo mismo que fs_cli con /log, pero en el navegador"
      />

      <Card>
        <CardHeader
          title="Consola"
          subtitle={`${visibles.length} línea${visibles.length === 1 ? "" : "s"} en pantalla`}
          actions={
            <div className="flex flex-wrap items-end gap-2">
              <Badge color={e.color} dot>
                {e.label}
              </Badge>
              <input
                placeholder="Filtrar…"
                value={filtro}
                onChange={(ev) => setFiltro(ev.target.value)}
                className="w-40 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand"
              />
              <div className="w-40">
                <Select label="" value={nivel} onChange={setNivel} options={NIVELES} />
              </div>
              {pausado ? (
                <button
                  type="button"
                  onClick={reanudar}
                  className="press rounded-lg border border-brand/40 bg-brand-soft px-2.5 py-1.5 text-xs font-medium text-brand-text transition-colors hover:border-brand"
                >
                  Reanudar{pendientes > 0 ? ` (${pendientes} nuevas)` : ""}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setPausado(true)}
                  className="press rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
                >
                  Pausar
                </button>
              )}
              <button
                type="button"
                onClick={limpiar}
                className="press rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
              >
                Limpiar
              </button>
            </div>
          }
        />
        <div
          ref={contenedorRef}
          onScroll={alScrollear}
          className="h-[65vh] overflow-y-auto bg-[#0b0f14] px-4 py-3 font-mono text-[12px] leading-relaxed"
        >
          {visibles.length === 0 ? (
            <div className="py-10 text-center text-faint">
              {estado === "conectado"
                ? "Esperando actividad…"
                : estado === "sin_acceso"
                  ? "Los logs de FreeSWITCH incluyen el tráfico de todas las empresas de la plataforma, por eso no están disponibles para una empresa."
                  : "Conectando con FreeSWITCH…"}
            </div>
          ) : (
            visibles.map((l, i) => (
              <div key={i} className={`whitespace-pre-wrap break-all ${claseLinea(l)}`}>
                {l}
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
