import * as SecureStore from "expo-secure-store";

/**
 * Todo lo que persiste entre aperturas de la app vive en SecureStore
 * (Keychain en iOS, EncryptedSharedPreferences en Android) — incluye la
 * URL del panel porque identifica a qué empresa entra cada quien, y no
 * solo el token, que es lo obviamente sensible. Un solo mecanismo de
 * guardado en vez de mezclar AsyncStorage + SecureStore evita el error
 * más común de estas apps: el token queda cifrado pero la URL del
 * servidor no, y un volcado del teléfono revela igual contra qué
 * empresa se puede probar ese token.
 */
const CLAVES = {
  apiBase: "nspbx_api_base",
  subdomain: "nspbx_subdomain",
  token: "nspbx_token",
  refreshToken: "nspbx_refresh_token",
} as const;

export async function guardar(clave: keyof typeof CLAVES, valor: string): Promise<void> {
  await SecureStore.setItemAsync(CLAVES[clave], valor);
}

export async function leer(clave: keyof typeof CLAVES): Promise<string | null> {
  return SecureStore.getItemAsync(CLAVES[clave]);
}

export async function borrar(clave: keyof typeof CLAVES): Promise<void> {
  await SecureStore.deleteItemAsync(CLAVES[clave]);
}

export async function borrarSesion(): Promise<void> {
  await Promise.all([borrar("token"), borrar("refreshToken")]);
}
