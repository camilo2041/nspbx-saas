"use client";

import { useEffect, useState } from "react";

import { Note } from "@/components/ui";
import { api } from "@/lib/api";

// Si las campañas no pueden marcar ahora (franja de Ajustes; Ley 2300 para
// cobranza), se dice y desde cuándo: si no, una campaña iniciada de noche
// parece rota. Ver backend/app/services/horario_marcacion.py.

interface Estado {
  puede_marcar: boolean;
  proxima_apertura: string | null;
}

interface Respuesta {
  cobranza: Estado;
  otras: Estado;
  festivo_hoy: boolean;
}

function cuando(iso: string | null): string {
  if (!iso) return "sin franja en los próximos días (revisa Ajustes)";
  return new Date(iso).toLocaleString(undefined, { weekday: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function AvisoHorarioCampanas() {
  const [estado, setEstado] = useState<Respuesta | null>(null);

  useEffect(() => {
    api.get<Respuesta>("/api/campaigns/horario").then(setEstado).catch(() => setEstado(null));
  }, []);

  if (!estado || (estado.cobranza.puede_marcar && estado.otras.puede_marcar)) return null;
  return (
    <div className="mb-4">
      <Note tone="warn">
        {estado.festivo_hoy ? "Hoy es festivo. " : ""}
        {!estado.otras.puede_marcar
          ? `Fuera del horario de marcación: las campañas retoman ${cuando(estado.otras.proxima_apertura)}.`
          : `Las campañas de cobranza esperan a la franja de la Ley 2300: retoman ${cuando(estado.cobranza.proxima_apertura)}.`}
      </Note>
    </div>
  );
}
