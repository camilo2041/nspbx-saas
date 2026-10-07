"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

export interface GrupoEnVivo {
  id: number;
  nombre: string;
  numero: string;
  esperando: number;
  espera_max_s: number;
  agentes: { libres: number; ocupados: number; pausa: number; total: number };
  devoluciones_pendientes: number;
  ultima_hora: { ofrecidas: number; atendidas: number; abandonadas: number; nivel_servicio_pct: number | null };
}

/** Espera más larga a partir de la cual la tarjeta se pone en rojo. */
export const ESPERA_ALERTA_S = 120;

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Cifra({ etiqueta, valor, tono = "text-fg" }: { etiqueta: string; valor: React.ReactNode; tono?: string }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">{etiqueta}</p>
      <p className={`text-2xl font-bold tabular-nums ${tono}`}>{valor}</p>
    </div>
  );
}

/**
 * Tarjetas de los grupos de atención: quién espera ahora y cómo va la última
 * hora (services/vigia_colas.py, cada 5 s). En Supervisión y en el wallboard.
 */
export function GruposEnVivo({ grupos, grande = false }: { grupos: GrupoEnVivo[]; grande?: boolean }) {
  if (!grupos.length) return null;
  return (
    <div className={`grid gap-4 ${grande ? "md:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2 xl:grid-cols-3"}`}>
      {grupos.map((g) => {
        const alerta = g.esperando > 0 && g.espera_max_s >= ESPERA_ALERTA_S;
        const sl = g.ultima_hora.nivel_servicio_pct;
        return (
          <Card key={g.id} className={alerta ? "ring-2 ring-danger/60" : undefined}>
            <div className="space-y-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate font-semibold text-fg">
                  {g.nombre} <span className="text-xs font-normal text-muted">· {g.numero}</span>
                </p>
                {alerta ? (
                  <Badge color="red" dot pulse>
                    Esperando mucho
                  </Badge>
                ) : g.esperando > 0 ? (
                  <Badge color="amber" dot>
                    En fila
                  </Badge>
                ) : (
                  <Badge color="green" dot>
                    Al día
                  </Badge>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Cifra etiqueta="Esperando" valor={g.esperando} tono={g.esperando ? "text-warn-text" : "text-fg"} />
                <Cifra
                  etiqueta="Espera más larga"
                  valor={g.esperando ? mmss(g.espera_max_s) : "—"}
                  tono={alerta ? "text-danger-text" : "text-fg"}
                />
                <Cifra etiqueta="Agentes libres" valor={`${g.agentes.libres}/${g.agentes.total}`} tono={g.agentes.libres ? "text-ok-text" : "text-fg"} />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-2 text-xs text-muted">
                <span>Hablando: {g.agentes.ocupados}</span>
                <span>En pausa: {g.agentes.pausa}</span>
                {g.devoluciones_pendientes > 0 && <span>Devoluciones pendientes: {g.devoluciones_pendientes}</span>}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                <span>Última hora:</span>
                <span>{g.ultima_hora.atendidas} atendidas</span>
                <span>{g.ultima_hora.abandonadas} colgaron</span>
                <span>Nivel de servicio {sl === null ? "—" : `${sl}%`}</span>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

interface Devolucion {
  id: number;
  grupo: string | null;
  numero: string;
  estado: "pendiente" | "llamando" | "hecha" | "fallida" | "cancelada";
  intentos: number;
  pedida_at: string;
  hecha_at: string | null;
  detalle: string | null;
}

const ESTADOS: Record<Devolucion["estado"], { texto: string; color: "amber" | "blue" | "green" | "red" | "gray" }> = {
  pendiente: { texto: "Pendiente", color: "amber" },
  llamando: { texto: "Llamando", color: "blue" },
  hecha: { texto: "Hecha", color: "green" },
  fallida: { texto: "No contestó", color: "red" },
  cancelada: { texto: "Cancelada", color: "gray" },
};

/** Devoluciones de llamada de las últimas 24 h (Supervisión). */
export function Devoluciones({ interviene }: { interviene: boolean }) {
  const [datos, setDatos] = useState<{ cifras: Record<string, number | null>; lista: Devolucion[] } | null>(null);

  const cargar = useCallback(() => {
    api.get<{ cifras: Record<string, number | null>; lista: Devolucion[] }>("/api/supervision/devoluciones").then(setDatos, () => undefined);
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 10_000);
    return () => clearInterval(t);
  }, [cargar]);

  if (!datos || datos.lista.length === 0) return null;
  const c = datos.cifras;
  const espera = c.espera_promedio_s;
  return (
    <Card className="mb-4">
      <CardHeader
        title="Devoluciones de llamada"
        subtitle={`Últimas 24 h: ${c.total ?? 0} pedidas, ${c.hecha ?? 0} hechas, ${c.fallida ?? 0} sin contestar${
          espera ? ` · se devolvieron en ${Math.round(espera / 60)} min en promedio` : ""
        }`}
      />
      <Table head={["Pedida", "Grupo", "Número", "Estado", "Detalle", ""]}>
        {datos.lista.slice(0, 20).map((d) => (
          <Tr key={d.id}>
            <Td muted>{new Date(d.pedida_at + "Z").toLocaleTimeString()}</Td>
            <Td>{d.grupo ?? "—"}</Td>
            <Td strong>{d.numero}</Td>
            <Td>
              <Badge color={ESTADOS[d.estado].color}>{ESTADOS[d.estado].texto}</Badge>
            </Td>
            <Td muted>{d.detalle ?? (d.intentos ? `${d.intentos} intento(s)` : "")}</Td>
            <Td>
              {interviene && d.estado === "pendiente" && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => api.post(`/api/supervision/devoluciones/${d.id}/cancelar`, {}).then(cargar, cargar)}
                >
                  Cancelar
                </Button>
              )}
            </Td>
          </Tr>
        ))}
      </Table>
    </Card>
  );
}
