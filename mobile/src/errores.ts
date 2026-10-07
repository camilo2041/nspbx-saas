import Constants from "expo-constants";

import { peticion } from "@/src/api/client";

/**
 * Errores de la app que llegan a Plataforma (backend/app/api/errores.py),
 * igual que los del panel. Nunca lanza: si no se puede reportar, se pierde.
 */
const vistos = new Map<string, number>();
const CADA_MS = 60_000;

export function reportarError(error: unknown, contexto?: string): void {
  try {
    const e = error instanceof Error ? error : new Error(typeof error === "string" ? error : JSON.stringify(error));
    const mensaje = `${contexto ? `${contexto}: ` : ""}${e.message}`.slice(0, 2000);
    const ahora = Date.now();
    if ((vistos.get(mensaje) ?? 0) > ahora - CADA_MS) return;
    vistos.set(mensaje, ahora);
    peticion("/api/errores", {
      method: "POST",
      body: { origen: "app", mensaje, pila: (e.stack || "").slice(0, 20000), version: Constants.expoConfig?.version ?? null },
    }).catch(() => undefined);
  } catch {
    /* reportar nunca debe romper nada */
  }
}

type Manejador = (error: Error, fatal?: boolean) => void;
interface ErrorUtilsGlobal {
  getGlobalHandler: () => Manejador;
  setGlobalHandler: (m: Manejador) => void;
}

let instalado = false;

/** Los errores de JS que no atrapa nadie. El manejador anterior sigue corriendo. */
export function escucharErroresGlobales(): void {
  const utils = (globalThis as unknown as { ErrorUtils?: ErrorUtilsGlobal }).ErrorUtils;
  if (instalado || !utils) return;
  instalado = true;
  const anterior = utils.getGlobalHandler();
  utils.setGlobalHandler((error, fatal) => {
    reportarError(error, fatal ? "Fatal" : undefined);
    anterior(error, fatal);
  });
}
