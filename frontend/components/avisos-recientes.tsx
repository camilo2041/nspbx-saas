"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { AlertaTrafico } from "@/lib/types";

/** Título y a dónde ir para resolver cada tipo de aviso (services/alertas.py). */
export const AVISOS: Record<string, { titulo: string; enlace?: string; accion?: string }> = {
  pico: { titulo: "Pico de llamadas salientes", enlace: "/calls", accion: "Ver llamadas" },
  madrugada: { titulo: "Llamadas salientes de madrugada", enlace: "/calls", accion: "Ver llamadas" },
  destino_nuevo: { titulo: "Destino internacional nuevo", enlace: "/calls", accion: "Ver llamadas" },
  cupo: { titulo: "Cerca del cupo diario de minutos" },
  troncal_caida: { titulo: "Proveedor de telefonía desconectado", enlace: "/trunks", accion: "Revisar el proveedor" },
  licencia_vence: { titulo: "La licencia está por vencer" },
  licencia_vencida: { titulo: "La licencia venció" },
  abandono_alto: { titulo: "Muchas llamadas colgaron esperando", enlace: "/reportes", accion: "Ver el reporte" },
};

const HORAS = 48;

/**
 * Avisos de las últimas 48 h en el Inicio: proveedor caído, licencia, mucha
 * gente colgando en la fila, tráfico raro. También llegan por correo a los
 * administradores (si el servidor tiene correo configurado).
 */
export function AvisosRecientes({ delay = 0 }: { delay?: number }) {
  const [avisos, setAvisos] = useState<AlertaTrafico[] | null>(null);

  useEffect(() => {
    const leer = () =>
      api
        .get<AlertaTrafico[]>("/api/security/alertas")
        .then((todas) => {
          const corte = Date.now() - HORAS * 3600 * 1000;
          setAvisos(todas.filter((a) => new Date(a.cuando.endsWith("Z") ? a.cuando : `${a.cuando}Z`).getTime() >= corte));
        })
        .catch(() => setAvisos([]));
    leer();
    const t = setInterval(leer, 60000);
    return () => clearInterval(t);
  }, []);

  if (!avisos || avisos.length === 0) return null;
  return (
    <Card delay={delay} className="mb-4 border-warn/40 p-5">
      <h2 className="text-base font-semibold text-fg">Avisos</h2>
      <ul className="mt-3 space-y-2">
        {avisos.slice(0, 5).map((a) => {
          const info = AVISOS[a.tipo] ?? { titulo: "Aviso" };
          return (
            <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-line p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-fg">
                  <span aria-hidden className="mr-1.5 text-warn">⚠</span>
                  {info.titulo}
                </p>
                <p className="mt-0.5 text-xs text-fg-soft">{a.detalle}</p>
                <p className="mt-0.5 text-[11px] text-muted">
                  {new Date(a.cuando.endsWith("Z") ? a.cuando : `${a.cuando}Z`).toLocaleString("es-CO", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </p>
              </div>
              {info.enlace && (
                <Link href={info.enlace} className="shrink-0 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-fg-soft hover:bg-surface-2">
                  {info.accion}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
