"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge, Card, CardHeader, StatusDot } from "@/components/ui";
import { WS_URL, getToken } from "@/lib/api";
import { LlamadaEnVivo } from "@/lib/types";

type Conexion = "conectando" | "conectado" | "reconectando" | "sin_acceso";

type Mensaje =
  | { tipo: "inicial" | "reinicio"; llamadas: LlamadaEnVivo[] }
  | { tipo: "llamada"; evento: string; llamada: LlamadaEnVivo }
  | { tipo: "ping" };

const ESTADO: Record<LlamadaEnVivo["estado"], { label: string; color: string }> = {
  iniciando: { label: "Marcando", color: "slate" },
  timbrando: { label: "Timbrando", color: "amber" },
  hablando: { label: "Hablando", color: "green" },
  espera: { label: "En espera", color: "blue" },
  colgada: { label: "Colgada", color: "slate" },
};

function cronometro(desde: number, ahora: number): string {
  const s = Math.max(0, Math.floor(ahora - desde));
  const m = Math.floor(s / 60);
  return m >= 60
    ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Une las dos patas de una llamada puenteada en una sola fila. */
function agrupar(canales: Map<string, LlamadaEnVivo>): LlamadaEnVivo[] {
  const filas: LlamadaEnVivo[] = [];
  const vistos = new Set<string>();
  const orden = [...canales.values()].sort((a, b) => a.inicio_at - b.inicio_at);
  for (const c of orden) {
    if (vistos.has(c.uuid)) continue;
    vistos.add(c.uuid);
    const otra = c.otra_pata ? canales.get(c.otra_pata) : undefined;
    if (otra) {
      vistos.add(otra.uuid);
      filas.push({ ...c, a: otra.a || c.a, ring_ms: c.ring_ms ?? otra.ring_ms });
    } else {
      filas.push(c);
    }
  }
  return filas;
}

/**
 * Llamadas en curso de la empresa, por WebSocket (/ws/tiempo-real).
 * Solo para quien puede ver todas las llamadas; el servidor filtra por
 * empresa y corta el socket si la sesión deja de valer.
 */
export function LlamadasEnVivo({ delay = 0 }: { delay?: number }) {
  const [canales, setCanales] = useState<Map<string, LlamadaEnVivo>>(new Map());
  const [conexion, setConexion] = useState<Conexion>("conectando");
  const [ahora, setAhora] = useState(() => Date.now() / 1000);

  useEffect(() => {
    let cerrado = false;
    let socket: WebSocket | null = null;
    let reintento: ReturnType<typeof setTimeout> | null = null;

    const conectar = () => {
      if (cerrado) return;
      const ws = new WebSocket(`${WS_URL}/ws/tiempo-real?token=${encodeURIComponent(getToken() ?? "")}`);
      socket = ws;
      ws.onopen = () => setConexion("conectado");
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data) as Mensaje;
        if (m.tipo === "inicial" || m.tipo === "reinicio") {
          setCanales(new Map(m.llamadas.map((l) => [l.uuid, l])));
        } else if (m.tipo === "llamada") {
          setCanales((prev) => {
            const sig = new Map(prev);
            if (m.evento === "cuelga") sig.delete(m.llamada.uuid);
            else sig.set(m.llamada.uuid, m.llamada);
            return sig;
          });
        }
      };
      ws.onclose = (e) => {
        if (cerrado) return;
        if (e.code === 4401 || e.code === 4403) {
          setConexion("sin_acceso");
          return;
        }
        setConexion("reconectando");
        reintento = setTimeout(conectar, 3000);
      };
      ws.onerror = () => ws.close();
    };

    conectar();
    const reloj = setInterval(() => setAhora(Date.now() / 1000), 1000);
    return () => {
      cerrado = true;
      if (reintento) clearTimeout(reintento);
      clearInterval(reloj);
      socket?.close();
    };
  }, []);

  const filas = useMemo(() => agrupar(canales), [canales]);
  if (conexion === "sin_acceso") return null;

  const hablando = filas.filter((f) => f.estado === "hablando" || f.estado === "espera").length;
  const timbrando = filas.filter((f) => f.estado === "timbrando" || f.estado === "iniciando").length;
  const estadoConexion =
    conexion === "conectado"
      ? { texto: "En vivo", color: "ok" as const, pulso: true }
      : { texto: conexion === "conectando" ? "Conectando…" : "Reconectando…", color: "warn" as const, pulso: false };

  return (
    <Card delay={delay} className="mb-4">
      <CardHeader
        title="Llamadas en vivo"
        subtitle={`${hablando} hablando · ${timbrando} timbrando`}
        actions={
          <span className="flex items-center gap-1.5 text-[11px] text-faint">
            <StatusDot color={estadoConexion.color} pulse={estadoConexion.pulso} />
            {estadoConexion.texto}
          </span>
        }
      />
      {filas.length === 0 ? (
        <div className="px-5 py-6 text-center text-sm text-muted">No hay llamadas en curso.</div>
      ) : (
        <div className="divide-y divide-line">
          {filas.map((f) => {
            const e = ESTADO[f.estado];
            const desde = f.contesta_at ?? f.timbre_at ?? f.inicio_at;
            return (
              <div key={f.uuid} className="flex items-center gap-3 px-5 py-2.5">
                <Badge color={f.direccion === "entrante" ? "blue" : "violet"}>
                  {f.direccion === "entrante" ? "Entrante" : "Saliente"}
                </Badge>
                <div className="min-w-0 flex-1 font-mono text-[13px] text-fg">
                  <span className="truncate">{f.nombre && f.nombre !== f.de ? `${f.nombre} ` : ""}{f.de || "—"}</span>
                  <span className="mx-1.5 text-faint">→</span>
                  <span className="truncate">{f.a || "—"}</span>
                </div>
                {f.ring_ms !== null && (
                  <span className="hidden text-[11px] text-faint sm:inline" title="Tiempo de timbre hasta que contestaron">
                    ring {(f.ring_ms / 1000).toLocaleString("es-CO", { maximumFractionDigits: 1 })} s
                  </span>
                )}
                <span className="w-14 text-right font-mono text-[12px] tabular-nums text-fg-soft">{cronometro(desde, ahora)}</span>
                <Badge color={e.color} dot>
                  {e.label}
                </Badge>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
