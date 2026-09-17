import { getVoIPPushToken } from "expo-callkit-telecom";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  cargarSesionGuardada,
  cerrarSesion as cerrarSesionApi,
  iniciarSesion,
  interpretarUrlEmpresa,
  olvidarServidor,
  peticion,
  servidorConfigurado,
} from "@/src/api/client";
import type { SesionOut, UsuarioOut } from "@/src/api/types";

interface AuthCtx {
  cargando: boolean;
  usuario: UsuarioOut | null;
  permisos: string[];
  puede: (permiso: string) => boolean;
  login: (urlEmpresa: string, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [cargando, setCargando] = useState(true);
  const [usuario, setUsuario] = useState<UsuarioOut | null>(null);
  const [permisos, setPermisos] = useState<string[]>([]);

  const aplicarSesion = (sesion: SesionOut) => {
    setUsuario(sesion.usuario);
    setPermisos(sesion.permisos);
  };

  // Al abrir la app: si hay token guardado, se revalida contra /api/auth/me
  // en vez de confiar ciegamente en lo que quedó en el teléfono — un rol
  // cambiado o una cuenta desactivada se refleja al instante, igual que en
  // el panel web (ver frontend/lib/auth.tsx).
  useEffect(() => {
    (async () => {
      const hayServidor = await servidorConfigurado();
      const haySesion = hayServidor && (await cargarSesionGuardada());
      if (haySesion) {
        try {
          const sesion = await peticion<SesionOut>("/api/auth/me");
          aplicarSesion(sesion);
        } catch {
          // token vencido/revocado y sin refresh posible: queda deslogueado
        }
      }
      setCargando(false);
    })();
  }, []);

  const login = useCallback(async (urlEmpresa: string, username: string, password: string) => {
    const servidor = interpretarUrlEmpresa(urlEmpresa);
    if (!servidor) {
      throw new ApiError("La dirección de tu empresa no es válida", 0);
    }
    const sesion = await iniciarSesion(servidor, username, password);
    aplicarSesion(sesion);
  }, []);

  const logout = useCallback(async () => {
    // Antes de cerrar sesión: si no se borra el token de push del
    // backend, alguien que cerró sesión seguiría recibiendo el push de
    // "te está entrando una llamada" — sin sesión para hacer nada con él.
    const voip = getVoIPPushToken();
    if (voip) {
      const platform = voip.type === "APNS_VOIP" ? "ios" : "android";
      await peticion(`/api/auth/dispositivo/${platform}`, { method: "DELETE" }).catch(() => {});
    }
    await cerrarSesionApi();
    await olvidarServidor();
    setUsuario(null);
    setPermisos([]);
  }, []);

  const puede = useCallback((permiso: string) => permisos.includes(permiso), [permisos]);

  const value = useMemo(
    () => ({ cargando, usuario, permisos, puede, login, logout }),
    [cargando, usuario, permisos, puede, login, logout]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
