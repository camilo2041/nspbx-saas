"use client";

import { useCallback, useEffect, useState } from "react";

import { Check } from "@/components/ui";
import { api } from "@/lib/api";
import { AgenteCampana } from "@/lib/types";

/** Quién trabaja la campaña: usuarios con extensión y permiso de agente. */
export function AgentesCampana({ campaignId }: { campaignId: number }) {
  const [agentes, setAgentes] = useState<AgenteCampana[] | null>(null);
  const [elegidos, setElegidos] = useState<number[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [guardado, setGuardado] = useState(false);
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

  // Se guarda al marcar o desmarcar: con un botón aparte («Guardar
  // agentes») se cerraba el formulario sin pulsarlo y la asignación se perdía.
  const cambiar = async (id: number, marcado: boolean) => {
    const nuevos = marcado ? [...elegidos, id] : elegidos.filter((x) => x !== id);
    setElegidos(nuevos);
    setGuardando(true);
    setGuardado(false);
    setError("");
    try {
      const lista = await api.put<AgenteCampana[]>(`/api/campaigns/${campaignId}/agentes`, { user_ids: nuevos });
      setAgentes(lista);
      setElegidos(lista.filter((a) => a.asignado).map((a) => a.id));
      setGuardado(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
      setElegidos(elegidos);
    } finally {
      setGuardando(false);
    }
  };

  if (!agentes) return null;
  return (
    <section className="mb-5">
      <h4 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        Agentes que trabajan esta campaña
        {guardando && <span className="font-normal normal-case tracking-normal text-faint">Guardando…</span>}
        {!guardando && guardado && <span className="font-normal normal-case tracking-normal text-ok-text">Guardado</span>}
      </h4>
      {error && <p className="mb-2 text-xs text-danger-text">{error}</p>}
      {agentes.length === 0 ? (
        <p className="text-xs text-faint">
          Nadie puede trabajar como agente todavía. Hace falta un usuario con extensión: en Usuarios, edita a la persona y
          asígnale una extensión (los roles asesor, coordinador, supervisor y admin pueden ser agentes).
        </p>
      ) : (
        <div className="rounded-xl border border-line px-2 py-1">
          {agentes.map((a) => (
            <Check
              key={a.id}
              checked={elegidos.includes(a.id)}
              onChange={(v) => cambiar(a.id, v)}
              label={`${a.nombre}${a.extension ? ` · ext. ${a.extension}` : " · sin extensión"}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
