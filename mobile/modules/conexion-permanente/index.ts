/**
 * Conexión permanente con la central en Android (sin push): un servicio en
 * primer plano mantiene viva la app y su registro SIP con la pantalla
 * apagada. Ver android/.../ServicioConexion.kt. En iOS no existe: Apple solo
 * permite despertar la app por PushKit.
 */
import { Platform } from "react-native";
import { requireOptionalNativeModule, type NativeModule } from "expo";

type Eventos = { latido: () => void };

declare class ModuloConexion extends NativeModule<Eventos> {
  iniciar(titulo: string, texto: string, despierto: boolean): void;
  actualizar(titulo: string, texto: string): void;
  detener(): void;
  activa(): boolean;
  sinRestriccionBateria(): boolean;
  pedirSinRestriccionBateria(): void;
  abrirAjustesApp(): void;
}

// Opcional: una compilación vieja de la app (sin el módulo) no se cae.
const nativo = Platform.OS === "android" ? requireOptionalNativeModule<ModuloConexion>("ConexionPermanente") : null;

export const disponible = !!nativo;

export function iniciar(titulo: string, texto: string, despierto: boolean): boolean {
  if (!nativo) return false;
  try {
    nativo.iniciar(titulo, texto, despierto);
    return true;
  } catch {
    // Android 12+ lo rechaza si la app no está en pantalla: se reintenta al volver.
    return false;
  }
}

export function actualizar(titulo: string, texto: string): void {
  try {
    nativo?.actualizar(titulo, texto);
  } catch {
    // sin servicio, nada que actualizar
  }
}

export function detener(): void {
  try {
    nativo?.detener();
  } catch {
    // ya estaba detenido
  }
}

export function activa(): boolean {
  return !!nativo?.activa();
}

export function sinRestriccionBateria(): boolean {
  return nativo ? nativo.sinRestriccionBateria() : true;
}

export function pedirSinRestriccionBateria(): void {
  nativo?.pedirSinRestriccionBateria();
}

export function abrirAjustesApp(): void {
  nativo?.abrirAjustesApp();
}

/** Cada ~9 min, incluso con el teléfono en reposo. */
export function alLatido(fn: () => void): { remove: () => void } {
  if (!nativo) return { remove: () => {} };
  return nativo.addListener("latido", fn);
}
