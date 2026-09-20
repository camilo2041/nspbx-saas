import { borrarSesion, guardar, leer } from "./storage";
import type { SesionOut } from "./types";

/**
 * El servidor de NSPBX es un dato INTERNO de la app: la persona solo ve
 * usuario y contraseña. Va fijo en el código (o en la variable de compilación
 * EXPO_PUBLIC_SERVIDOR para apuntar una compilación de pruebas a otro, sin
 * exponerlo en pantalla).
 *
 * `subdomain` va vacío a propósito: el usuario es único en toda la
 * plataforma y el backend lo ubica en su empresa por el nombre de usuario;
 * enviar un subdominio deducido del host podía rechazar el acceso si algún
 * día una empresa tomaba ese nombre (ver LoginRequest.subdomain).
 */
const SERVIDOR_PUBLICADO = "https://nspbx.nspbxdevelop.com";

function elegirServidor(): string {
  const configurado = (process.env.EXPO_PUBLIC_SERVIDOR || "").trim().replace(/\/+$/, "");
  if (!configurado) return SERVIDOR_PUBLICADO;
  // Sin https, usuario, contraseña y tokens viajarían en claro. Solo se
  // tolera http en desarrollo (Metro / red local); una compilación de
  // producción con http se ignora y usa el servidor publicado.
  if (/^http:\/\//i.test(configurado) && !__DEV__) return SERVIDOR_PUBLICADO;
  if (!/^https?:\/\//i.test(configurado)) return `https://${configurado}`;
  return configurado;
}

export interface ServidorConfigurado {
  apiBase: string;
  subdomain: string;
}

const SERVIDOR_FIJO: ServidorConfigurado = { apiBase: elegirServidor(), subdomain: "" };

export async function servidorConfigurado(): Promise<ServidorConfigurado> {
  return SERVIDOR_FIJO;
}

let token: string | null = null;
let refreshToken: string | null = null;

// AuthContext se entera cuando la sesión deja de servir (refresh rechazado),
// para volver al login en vez de quedar "logueado" con un token muerto.
let alExpirarSesion: (() => void) | null = null;
export function onSesionExpirada(cb: (() => void) | null): void {
  alExpirarSesion = cb;
}

export async function cargarSesionGuardada(): Promise<boolean> {
  token = await leer("token");
  refreshToken = await leer("refreshToken");
  return Boolean(token);
}

async function guardarSesion(sesion: SesionOut): Promise<void> {
  token = sesion.token;
  await guardar("token", sesion.token);
  if (sesion.refresh_token) {
    refreshToken = sesion.refresh_token;
    await guardar("refreshToken", sesion.refresh_token);
  }
}

async function limpiarSesionLocal(): Promise<void> {
  token = null;
  refreshToken = null;
  await borrarSesion();
}

/** Cabecera Authorization para pedir recursos que no pasan por `peticion` (audio, descargas). */
export function cabeceraAuth(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** URL absoluta de un recurso de la API. */
export function urlApi(path: string): string {
  return `${SERVIDOR_FIJO.apiBase}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

/** El backend responde `detail` como texto, o como lista en errores de validación (422). */
function mensajeDe(cuerpo: unknown, respaldo: string): string {
  const detalle = (cuerpo as { detail?: unknown } | null)?.detail;
  if (typeof detalle === "string" && detalle) return detalle;
  if (Array.isArray(detalle) && detalle.length) {
    const primero = detalle[0] as { msg?: string };
    if (primero?.msg) return primero.msg;
  }
  return respaldo;
}

/** fetch con tope de tiempo: sin él, una red colgada deja la pantalla en "cargando" para siempre. */
async function conTiempo(url: string, init: RequestInit, ms = 20_000): Promise<Response> {
  const controlador = new AbortController();
  const timer = setTimeout(() => controlador.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: controlador.signal });
  } finally {
    clearTimeout(timer);
  }
}

// Un solo refresco a la vez: varias peticiones que vencen juntas (pantalla
// que carga tres cosas) compartían el mismo refresh token; como el backend lo
// rota, la segunda usaba uno ya consumido, fallaba y dejaba la sesión rota.
let refrescando: Promise<"ok" | "rechazado" | "red"> | null = null;

async function refrescarSesion(): Promise<"ok" | "rechazado" | "red"> {
  if (!refreshToken) return "rechazado";
  if (refrescando) return refrescando;
  refrescando = (async () => {
    try {
      const resp = await conTiempo(`${SERVIDOR_FIJO.apiBase}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (resp.ok) {
        await guardarSesion((await resp.json()) as SesionOut);
        return "ok" as const;
      }
      if (resp.status === 401 || resp.status === 403) {
        // Revocado o vencido: la sesión ya no sirve, se limpia y se avisa.
        await limpiarSesionLocal();
        alExpirarSesion?.();
        return "rechazado" as const;
      }
      return "red" as const; // 5xx u otro: puede ser pasajero, no se cierra la sesión
    } catch {
      return "red" as const;
    } finally {
      refrescando = null;
    }
  })();
  return refrescando;
}

/** Petición autenticada. Si el token venció, refresca UNA vez y reintenta
 * — mismo criterio que el 401 global del panel web (frontend/lib/api.ts),
 * pero acá además hay refresh token (ver /api/auth/refresh) en vez de
 * mandar a la persona a loguearse de nuevo cada 8 horas. */
export async function peticion<T>(
  path: string,
  opciones: { method?: string; body?: unknown } = {}
): Promise<T> {
  const hacer = async (): Promise<Response> =>
    conTiempo(`${SERVIDOR_FIJO.apiBase}${path}`, {
      method: opciones.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: opciones.body !== undefined ? JSON.stringify(opciones.body) : undefined,
    });

  let resp = await hacer();
  if (resp.status === 401 && refreshToken) {
    const resultado = await refrescarSesion();
    if (resultado === "ok") resp = await hacer();
  }
  if (!resp.ok) {
    const cuerpo = await resp.json().catch(() => null);
    throw new ApiError(mensajeDe(cuerpo, `Error ${resp.status}`), resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

/**
 * Comprueba usuario y contraseña SIN tocar la sesión activa. Sirve para
 * confirmar una contraseña (activar la huella) sin reemplazar por accidente
 * los tokens de la sesión en curso. El refresh token que el backend emite en
 * esta comprobación se revoca de inmediato para no dejar sesiones huérfanas.
 */
export async function verificarCredenciales(
  servidor: ServidorConfigurado,
  username: string,
  password: string
): Promise<SesionOut> {
  const resp = await conTiempo(`${servidor.apiBase}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, subdomain: servidor.subdomain }),
  });
  const cuerpo = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(mensajeDe(cuerpo, "No se pudo iniciar sesión"), resp.status);
  return cuerpo as SesionOut;
}

async function revocarRefresh(refresh: string | null): Promise<void> {
  if (!refresh) return;
  try {
    await conTiempo(`${SERVIDOR_FIJO.apiBase}/api/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
  } catch {
    // best-effort
  }
}

export async function verificarSoloContrasena(servidor: ServidorConfigurado, username: string, password: string): Promise<void> {
  const sesion = await verificarCredenciales(servidor, username, password);
  await revocarRefresh(sesion.refresh_token);
}

export async function iniciarSesion(
  servidor: ServidorConfigurado,
  username: string,
  password: string
): Promise<SesionOut> {
  const sesion = await verificarCredenciales(servidor, username, password);
  await guardarSesion(sesion);
  return sesion;
}

export async function cerrarSesion(): Promise<void> {
  const refresh = refreshToken;
  // Primero se olvida todo localmente: si el backend no responde, el teléfono
  // igual queda sin sesión.
  await limpiarSesionLocal();
  await revocarRefresh(refresh);
}

/**
 * Dirección del WebSocket SIP a la que se conecta el softphone.
 *
 * Igual que `resolverServidorSip` del panel web (frontend/lib/softphone-context.tsx):
 * el valor guardado en Ajustes manda, pero viene de fábrica como
 * "wss://localhost:7443", que solo sirve en el mismo equipo que FreeSWITCH. En
 * un teléfono, `localhost` es el propio teléfono y la conexión muere con
 * "WebSocket closed (code: 1006)", un error que no sugiere que el problema sea
 * un ajuste sin actualizar. En ese caso (o si está vacío) se deduce del
 * dominio del panel: Traefik reenvía `/sip` a FreeSWITCH.
 *
 * Solo se acepta `wss://` (cifrado). La dirección viene del servidor; sin este
 * filtro, una respuesta manipulada podría mandar el registro SIP —con la
 * contraseña de la extensión— a un `ws://` ajeno y sin cifrar. En desarrollo
 * (`__DEV__`) se tolera `ws://`.
 */
export function resolverServidorSip(configurado: string | null | undefined, apiBase: string | null): string {
  const v = (configurado ?? "").trim();
  const esLocal = v === "" || /^wss?:\/\/(localhost|127\.0\.0\.1)/i.test(v);
  const esSeguro = /^wss:\/\//i.test(v) || (__DEV__ && /^ws:\/\//i.test(v));
  if (!esLocal && esSeguro) return v;
  if (!apiBase) return esSeguro ? v : "";
  const url = new URL(apiBase);
  return url.protocol === "https:" ? `wss://${url.host}/sip` : __DEV__ ? `ws://${url.hostname}:5066` : "";
}
