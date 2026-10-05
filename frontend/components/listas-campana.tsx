"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { ListaCampana } from "@/lib/types";

const ORIGEN: Record<ListaCampana["origen"], string> = { manual: "Carga manual", csv: "CSV", api: "API" };

/**
 * Las cargas de una campaña: se pausan (sus números esperan sin marcarse) o
 * se priorizan (las de prioridad más alta salen primero) sin tocar los
 * números. `version` cambia cuando se cargan números nuevos.
 */
export function ListasCampana({ campaignId, version, onCambio }: { campaignId: number; version: number; onCambio: () => void }) {
  const [listas, setListas] = useState<ListaCampana[] | null>(null);
  const [error, setError] = useState("");

  const cargar = useCallback(async () => {
    try {
      setListas(await api.get<ListaCampana[]>(`/api/campaigns/${campaignId}/listas`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las listas");
    }
  }, [campaignId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar, version]);

  const cambiar = async (l: ListaCampana, cambios: Partial<Pick<ListaCampana, "activa" | "prioridad">>) => {
    try {
      await api.put(`/api/campaigns/${campaignId}/listas/${l.id}`, cambios);
      await cargar();
      onCambio();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar la lista");
    }
  };

  if (!listas || listas.length === 0) return null;
  return (
    <section className="mb-5">
      <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Listas</h4>
      {error && <p className="mb-2 text-xs text-danger-text">{error}</p>}
      <div className="divide-y divide-line rounded-xl border border-line">
        {listas.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-3 px-3.5 py-2.5 text-[13px]">
            <Toggle checked={l.activa} onChange={(v) => cambiar(l, { activa: v })} />
            <div className="min-w-0 flex-1">
              <div className={`truncate font-medium ${l.activa ? "text-fg" : "text-faint line-through"}`}>{l.nombre}</div>
              <div className="text-[11px] text-faint">
                {ORIGEN[l.origen]} · {l.total} número(s) · {l.pendientes} pendiente(s)
              </div>
            </div>
            {!l.activa && <Badge color="amber">En pausa</Badge>}
            <label className="flex items-center gap-1.5 text-[11px] text-muted" title="Las de prioridad más alta se marcan primero">
              Prioridad
              <select
                value={l.prioridad}
                onChange={(e) => cambiar(l, { prioridad: Number(e.target.value) })}
                className="rounded-lg border border-line bg-surface px-1.5 py-1 text-xs text-fg"
              >
                {[-5, -1, 0, 1, 5, 10].map((p) => (
                  <option key={p} value={p}>
                    {p > 0 ? `+${p}` : p}
                  </option>
                ))}
                {![-5, -1, 0, 1, 5, 10].includes(l.prioridad) && <option value={l.prioridad}>{l.prioridad}</option>}
              </select>
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}
