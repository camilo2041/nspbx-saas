/**
 * Preferencia de este teléfono para la conexión permanente con la central
 * (Android, sin push). Ver modules/conexion-permanente.
 *
 * - "normal": servicio con notificación fija + latido cada ~9 min. Gasta poca batería.
 * - "maxima": además el procesador nunca duerme. Para los teléfonos que con
 *   "normal" igual pierden llamadas; gasta bastante más batería.
 * - "apagada": las llamadas entran solo con la app abierta (o por push, si está configurado).
 */
import * as SecureStore from "expo-secure-store";

import { disponible } from "@/modules/conexion-permanente";

export type ModoConexion = "apagada" | "normal" | "maxima";

const CLAVE = "nspbx_conexion_permanente";

export async function leerModo(): Promise<ModoConexion> {
  if (!disponible) return "apagada";
  try {
    const v = await SecureStore.getItemAsync(CLAVE);
    if (v === "apagada" || v === "normal" || v === "maxima") return v;
  } catch {
    // sin almacenamiento: el valor por defecto
  }
  // Por defecto encendida: recibir llamadas es para lo que está la app.
  return "normal";
}

export async function guardarModo(modo: ModoConexion): Promise<void> {
  try {
    await SecureStore.setItemAsync(CLAVE, modo);
  } catch {
    // se usa igual en esta sesión
  }
}
