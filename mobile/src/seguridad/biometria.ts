import * as LocalAuthentication from "expo-local-authentication";
import * as SecureStore from "expo-secure-store";

/**
 * Acceso con huella (o rostro / PIN del teléfono), como las apps bancarias.
 *
 * La contraseña se guarda con `requireAuthentication: true`: queda cifrada con
 * una llave del Keystore (Android) / Keychain (iOS) que el sistema solo libera
 * tras una autenticación biométrica. Dos consecuencias buscadas:
 *  - Leerla exige la huella en ese momento; no basta con tener el teléfono
 *    desbloqueado ni con tener acceso root a los archivos de la app.
 *  - Si se registran huellas nuevas en el teléfono, el sistema invalida la
 *    llave y la contraseña deja de poder leerse (alguien que agrega su huella
 *    con el teléfono desbloqueado no hereda el acceso).
 *
 * Nada de esto sale del teléfono: la contraseña solo se usa para volver a
 * iniciar sesión contra el servidor de la empresa.
 *
 * Alcance del BLOQUEO (para no prometer de más): la pantalla de bloqueo impide
 * ver y usar la app, pero la sesión (token) sigue cargada por debajo a
 * propósito, para que las llamadas entrantes se sigan atendiendo con la app
 * bloqueada. Lo que solo se libera con huella es la CONTRASEÑA guardada.
 */
const K_CREDENCIALES = "nspbx_credenciales";
const K_ACTIVA = "nspbx_bio_activa";
const K_NOMBRE = "nspbx_bio_nombre";
const K_ULTIMO_USUARIO = "nspbx_ultimo_usuario";

export interface Credenciales {
  username: string;
  password: string;
}

export async function biometriaDisponible(): Promise<boolean> {
  try {
    return (await LocalAuthentication.hasHardwareAsync()) && (await LocalAuthentication.isEnrolledAsync());
  } catch {
    return false;
  }
}

/** Pide huella (o el PIN/patrón del teléfono si no hay huella disponible). */
export async function autenticar(motivo: string): Promise<boolean> {
  try {
    const r = await LocalAuthentication.authenticateAsync({
      promptMessage: motivo,
      cancelLabel: "Cancelar",
      fallbackLabel: "Usar PIN del teléfono",
    });
    return r.success;
  } catch {
    return false;
  }
}

export async function biometriaActiva(): Promise<boolean> {
  return (await SecureStore.getItemAsync(K_ACTIVA)) === "1";
}

export async function nombreGuardado(): Promise<string> {
  return (await SecureStore.getItemAsync(K_NOMBRE)) ?? "";
}

export async function ultimoUsuario(): Promise<string> {
  return (await SecureStore.getItemAsync(K_ULTIMO_USUARIO)) ?? "";
}

export async function recordarUsuario(username: string): Promise<void> {
  await SecureStore.setItemAsync(K_ULTIMO_USUARIO, username);
}

/** Guarda la contraseña protegida por huella. Lanza si el sistema la rechaza. */
export async function activarBiometria(cred: Credenciales, nombre: string): Promise<void> {
  await SecureStore.setItemAsync(K_CREDENCIALES, JSON.stringify(cred), {
    requireAuthentication: true,
    authenticationPrompt: "Confirma tu huella para guardar tu contraseña",
  });
  await SecureStore.setItemAsync(K_ACTIVA, "1");
  await SecureStore.setItemAsync(K_NOMBRE, nombre);
}

export type LecturaCredenciales =
  | { estado: "ok"; cred: Credenciales }
  /** La persona canceló el lector (o hubo demasiados intentos): NO se toca lo guardado. */
  | { estado: "cancelado" }
  /** La llave quedó invalidada (cambiaron las huellas) o el dato no existe. */
  | { estado: "invalidada" };

/** Lee la contraseña (el sistema pide la huella). */
export async function leerCredenciales(): Promise<LecturaCredenciales> {
  try {
    const v = await SecureStore.getItemAsync(K_CREDENCIALES, {
      requireAuthentication: true,
      authenticationPrompt: "Confirma tu huella para entrar",
    });
    if (!v) return { estado: "invalidada" };
    return { estado: "ok", cred: JSON.parse(v) as Credenciales };
  } catch (e) {
    // Cancelar el lector también lanza excepción; tratarlo como "huellas
    // cambiadas" borraba la contraseña guardada por un simple "Cancelar".
    const mensaje = e instanceof Error ? e.message : String(e);
    if (/cancel|lockout|too many|not authenticated|user.?cancel/i.test(mensaje)) return { estado: "cancelado" };
    return { estado: "invalidada" };
  }
}

/** Borra la contraseña guardada y apaga el acceso con huella. */
export async function desactivarBiometria(): Promise<void> {
  await SecureStore.deleteItemAsync(K_CREDENCIALES).catch(() => {});
  await SecureStore.deleteItemAsync(K_ACTIVA).catch(() => {});
  await SecureStore.deleteItemAsync(K_NOMBRE).catch(() => {});
}
