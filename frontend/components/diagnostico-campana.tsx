"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

interface ItemDiagnostico {
  clave: string;
  ok: boolean;
  grave: boolean;
  titulo: string;
  detalle: string;
}

export interface DiagnosticoCampana {
  metodo: string;
  listo: boolean;
  resumen: string;
  items: ItemDiagnostico[];
  agentes: { conectados: number; con_audio: number; listos: number } | null;
}

/**
 * Lo que tiene que estar listo para que la campaña llame, con lo que falta y
 * dónde se arregla (backend/app/services/diagnostico_campana.py). Se
 * refresca solo: los agentes entran y salen mientras se mira.
 */
export function DiagnosticoCampana({ campaignId, version }: { campaignId: number; version: number | string }) {
  const [d, setD] = useState<DiagnosticoCampana | null>(null);
  const [verTodo, setVerTodo] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setD(await api.get<DiagnosticoCampana>(`/api/campaigns/${campaignId}/diagnostico`));
    } catch {
      // Sin diagnóstico no se bloquea nada: el resto del detalle sigue.
    }
  }, [campaignId]);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 5000);
    return () => clearInterval(t);
  }, [cargar, version]);

  if (!d) return null;
  const pendientes = d.items.filter((i) => !i.ok);
  const visibles = verTodo ? d.items : pendientes;

  return (
    <section
      className={`mb-5 rounded-xl border p-4 ${d.listo ? "border-ok/30 bg-ok-soft" : "border-danger/25 bg-danger-soft"}`}
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-sm font-semibold ${d.listo ? "text-ok-text" : "text-danger-text"}`}>
            {d.listo ? "Lista para llamar" : "Esta campaña no está llamando"}
          </p>
          <p className="mt-0.5 text-xs text-fg-soft">{d.resumen}</p>
          {d.agentes && (
            <p className="mt-1 text-xs text-muted">
              Agentes ahora: {d.agentes.conectados} dentro · {d.agentes.con_audio} con audio · {d.agentes.listos} listos
            </p>
          )}
        </div>
        <button type="button" className="shrink-0 text-xs font-medium text-brand underline" onClick={() => setVerTodo(!verTodo)}>
          {verTodo ? "Ver solo lo que falta" : "Ver todo"}
        </button>
      </div>
      {visibles.length > 0 && (
        <ul className="mt-3 space-y-2">
          {visibles.map((i) => (
            <li key={i.clave} className="flex items-start gap-2 text-sm">
              <span
                aria-hidden
                className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${
                  i.ok ? "bg-ok" : i.grave ? "bg-danger" : "bg-warn"
                }`}
              >
                {i.ok ? "✓" : "!"}
              </span>
              <span>
                <span className="font-medium text-fg">{i.titulo}</span>
                {!i.ok && i.detalle && <span className="block text-xs text-fg-soft">{i.detalle}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
