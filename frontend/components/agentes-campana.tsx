"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, Check } from "@/components/ui";
import { api } from "@/lib/api";
import { AgenteCampana } from "@/lib/types";

/** Quién trabaja la campaña: usuarios con extensión y permiso de agente. */
export function AgentesCampana({ campaignId }: { campaignId: number }) {
  const [agentes, setAgentes] = useState<AgenteCampana[] | null>(null);
  const [elegidos, setElegidos] = useState<number[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  const cargar = useCallback(async () => {
    try {
      const lista = await api.get<AgenteCampana[]>(`/api/campaigns/${campaignId}/agentes`);
      setAgentes(lista);
      setElegidos(lista.filter((a) => a.asignado).map((a) => a.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los agentes");
    }
  }, [campaignId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const guardar = async () => {
    setGuardando(true);
    setError("");
    try {
      const lista = await api.put<AgenteCampana[]>(`/api/campaigns/${campaignId}/agentes`, { user_ids: elegidos });
      setAgentes(lista);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  if (!agentes) return null;
  const cambiado =
    elegidos.length !== agentes.filter((a) => a.asignado).length || agentes.some((a) => a.asignado !== elegidos.includes(a.id));
  return (
    <section className="mb-5">
      <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Agentes</h4>
      {error && <p className="mb-2 text-xs text-danger-text">{error}</p>}
      {agentes.length === 0 ? (
        <p className="text-xs text-faint">Nadie puede trabajar como agente todavía: hace falta un usuario con extensión asignada.</p>
      ) : (
        <div className="rounded-xl border border-line px-2 py-1">
          {agentes.map((a) => (
            <Check
              key={a.id}
              checked={elegidos.includes(a.id)}
              onChange={(v) => setElegidos(v ? [...elegidos, a.id] : elegidos.filter((x) => x !== a.id))}
              label={`${a.nombre}${a.extension ? ` · ext. ${a.extension}` : " · sin extensión"}`}
            />
          ))}
        </div>
      )}
      {cambiado && (
        <div className="mt-2">
          <Button size="sm" onClick={guardar} loading={guardando}>
            Guardar agentes
          </Button>
        </div>
      )}
    </section>
  );
}
