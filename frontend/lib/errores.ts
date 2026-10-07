import { api } from "@/lib/api";
import { esVersionVieja } from "@/lib/version-vieja";

/**
 * Manda al backend los errores del panel (api/errores.py) para que Plataforma
 * los vea agrupados. Nunca lanza ni reintenta: si no se puede reportar, se pierde.
 */
const vistos = new Map<string, number>();
const CADA_MS = 60_000;
// Ruido conocido que no es un fallo nuestro.
const IGNORAR = [/ResizeObserver loop/, /chrome-extension:\/\//, /moz-extension:\/\//, /^Script error\.?$/];

export function reportarError(error: unknown, contexto?: string): void {
  try {
    if (typeof window === "undefined") return;
    const e = error instanceof Error ? error : new Error(typeof error === "string" ? error : JSON.stringify(error));
    if (esVersionVieja(e)) return; // se resuelve recargando (lib/version-vieja.ts)
    const mensaje = `${contexto ? `${contexto}: ` : ""}${e.name !== "Error" ? `${e.name}: ` : ""}${e.message}`.slice(0, 2000);
    const pila = (e.stack || "").slice(0, 20000);
    if (IGNORAR.some((r) => r.test(mensaje) || r.test(pila))) return;
    const ahora = Date.now();
    if ((vistos.get(mensaje) ?? 0) > ahora - CADA_MS) return;
    vistos.set(mensaje, ahora);
    api
      .post("/api/errores", { origen: "panel", mensaje, pila, ruta: window.location.pathname, version: process.env.NEXT_PUBLIC_VERSION })
      .catch(() => undefined);
  } catch {
    /* reportar nunca debe romper nada */
  }
}

/** Errores que no atrapa ninguna pantalla (eventos, promesas sin catch). */
export function escucharErroresGlobales(): () => void {
  const alError = (ev: ErrorEvent) => reportarError(ev.error ?? ev.message);
  const alRechazo = (ev: PromiseRejectionEvent) => reportarError(ev.reason, "Promesa sin atrapar");
  window.addEventListener("error", alError);
  window.addEventListener("unhandledrejection", alRechazo);
  return () => {
    window.removeEventListener("error", alError);
    window.removeEventListener("unhandledrejection", alRechazo);
  };
}
