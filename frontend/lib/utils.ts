export function statusBadge(status: string): { label: string; color: string } {
  const map: Record<string, { label: string; color: string }> = {
    idle: { label: "Inactiva", color: "slate" },
    running: { label: "En curso", color: "green" },
    paused: { label: "Pausada", color: "amber" },
    done: { label: "Completada", color: "blue" },
    pending: { label: "Pendiente", color: "amber" },
    dialing: { label: "Marcando", color: "blue" },
    answered: { label: "Contestada", color: "green" },
    voicemail: { label: "Buzón de voz", color: "blue" },
    busy: { label: "Ocupado", color: "red" },
    noanswer: { label: "Sin respuesta", color: "slate" },
    failed: { label: "Falló", color: "red" },
    done_campaign: { label: "Completada", color: "blue" },
  };
  return map[status] ?? { label: status, color: "slate" };
}

/** Segundos como "4,2 s" o "1:05" (desde un minuto). null → "—". */
export function tiempoCorto(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "—";
  if (segundos < 60) return `${segundos.toLocaleString("es-CO", { maximumFractionDigits: 1 })} s`;
  const total = Math.round(segundos);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
