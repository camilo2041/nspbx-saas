import { EstadoAgente } from "@/lib/types";

// Compartido por la pantalla de supervisión y el wallboard.

export const ESTADOS: Record<EstadoAgente, { label: string; color: string }> = {
  LISTO: { label: "Listo", color: "green" },
  PAUSA: { label: "En pausa", color: "amber" },
  PREVIA: { label: "Vista previa", color: "violet" },
  TIMBRANDO: { label: "Timbrando", color: "blue" },
  EN_LLAMADA: { label: "En llamada", color: "indigo" },
  DISPO: { label: "Disposición", color: "slate" },
};

export function reloj(s: number | null | undefined): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return m >= 60
    ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${m}:${String(s % 60).padStart(2, "0")}`;
}
