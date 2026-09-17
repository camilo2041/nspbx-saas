import { borrar, borrarSesion, guardar, leer } from "./storage";
import type { SesionOut } from "./types";

/**
 * A diferencia del panel web (ver frontend/lib/api.ts), acá no existe
 * `window.location`: no hay forma de deducir contra qué empresa hablar
 * ni en qué host vive el backend. Por eso la app pide UNA vez, en el
 * login, la URL del panel de la empresa — y de ahí saca tanto la base de
 * la API como el subdominio que el backend necesita para saber a qué
 * tenant pertenece quien inicia sesión (ver LoginRequest.subdomain en
 * backend/app/schemas/schemas.py).
 */
export interface ServidorConfigurado {
  apiBase: string;
  subdomain: string;
}

/** "consultorio-andino.pbx.ejemplo.com" o "https://consultorio-andino.pbx.ejemplo.com"
 * → { apiBase: "https://consultorio-andino.pbx.ejemplo.com", subdomain: "consultorio-andino" } */
export function interpretarUrlEmpresa(entrada: string): ServidorConfigurado | null {
  const limpio = entrada.trim();
  if (!limpio) return null;
  const conProtocolo = /^https?:\/\//i.test(limpio) ? limpio : `https://${limpio}`;
  let url: URL;
  try {
    url = new URL(conProtocolo);
  } catch {
    return null;
  }
  const host = url.hostname;
  const primerLabel = host.split(".")[0];
  const subdomain = ["www", "localhost"].includes(primerLabel) ? "" : primerLabel;
  return { apiBase: `${url.protocol}//${host}${url.port ? `:${url.port}` : ""}`, subdomain };
}

let cache: ServidorConfigurado | null = null;

export async function configurarServidor(cfg: ServidorConfigurado): Promise<void> {
  cache = cfg;
  await guardar("apiBase", cfg.apiBase);
  await guardar("subdomain", cfg.subdomain);
}

export async function servidorConfigurado(): Promise<ServidorConfigurado | null> {
  if (cache) return cache;
  const apiBase = await leer("apiBase");
  if (!apiBase) return null;
  const subdomain = (await leer("subdomain")) || "";
  cache = { apiBase, subdomain };
  return cache;
}

let token: string | null = null;
let refreshToken: string | null = null;

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

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

async function urlBase(): Promise<string> {
  const cfg = await servidorConfigurado();
  if (!cfg) throw new Error("La app todavía no tiene configurado el servidor de tu empresa");
  return cfg.apiBase;
}

/** Petición autenticada. Si el token venció, refresca UNA vez y reintenta
 * — mismo criterio que el 401 global del panel web (frontend/lib/api.ts),
 * pero acá además hay refresh token (ver /api/auth/refresh) en vez de
 * mandar a la persona a loguearse de nuevo cada 8 horas. */
export async function peticion<T>(
  path: string,
  opciones: { method?: string; body?: unknown } = {}
): Promise<T> {
  const base = await urlBase();
  const hacer = async (): Promise<Response> =>
    fetch(`${base}${path}`, {
      method: opciones.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: opciones.body !== undefined ? JSON.stringify(opciones.body) : undefined,
    });

  let resp = await hacer();
  if (resp.status === 401 && refreshToken) {
    const refrescado = await intentarRefrescar();
    if (refrescado) resp = await hacer();
  }
  if (!resp.ok) {
    const cuerpo = await resp.json().catch(() => ({}) as { detail?: string });
    throw new ApiError(cuerpo.detail || `Error ${resp.status}`, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

async function intentarRefrescar(): Promise<boolean> {
  if (!refreshToken) return false;
  try {
    const base = await urlBase();
    const resp = await fetch(`${base}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!resp.ok) return false;
    const sesion = (await resp.json()) as SesionOut;
    await guardarSesion(sesion);
    return true;
  } catch {
    return false;
  }
}

export async function iniciarSesion(
  servidor: ServidorConfigurado,
  username: string,
  password: string
): Promise<SesionOut> {
  await configurarServidor(servidor);
  const resp = await fetch(`${servidor.apiBase}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, subdomain: servidor.subdomain }),
  });
  const cuerpo = await resp.json().catch(() => ({}) as { detail?: string });
  if (!resp.ok) {
    throw new ApiError((cuerpo as { detail?: string }).detail || "No se pudo iniciar sesión", resp.status);
  }
  const sesion = cuerpo as SesionOut;
  await guardarSesion(sesion);
  return sesion;
}

export async function cerrarSesion(): Promise<void> {
  if (refreshToken) {
    try {
      await peticion("/api/auth/logout", { method: "POST", body: { refresh_token: refreshToken } });
    } catch {
      // best-effort: si el backend no responde, igual se limpia localmente
    }
  }
  token = null;
  refreshToken = null;
  await borrarSesion();
}

export async function olvidarServidor(): Promise<void> {
  cache = null;
  await borrar("apiBase");
  await borrar("subdomain");
}
