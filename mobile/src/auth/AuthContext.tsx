import { getVoIPPushToken } from "expo-callkit-telecom";
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppState } from "react-native";

import {
  ApiError,
  cargarSesionGuardada,
  cerrarSesion as cerrarSesionApi,
  iniciarSesion,
  onSesionExpirada,
  peticion,
  servidorConfigurado,
  verificarSoloContrasena,
} from "@/src/api/client";
import type { SesionOut, UsuarioOut } from "@/src/api/types";
import { vaciarCache } from "@/src/datos";
import {
  activarBiometria as guardarBiometria,
  autenticar,
  biometriaActiva,
  biometriaDisponible,
  desactivarBiometria as borrarBiometria,
  leerCredenciales,
  nombreGuardado,
  recordarUsuario,
} from "@/src/seguridad/biometria";

/** Tiempo en segundo plano tras el cual la app vuelve a pedir la huella. */
const BLOQUEO_TRAS_MS = 30_000;

interface AuthCtx {
  cargando: boolean;
  usuario: UsuarioOut | null;
  permisos: string[];
  puede: (permiso: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;

  // Acceso con huella
  bioDisponible: boolean;
  bioActiva: boolean;
  bloqueada: boolean;
  nombreBio: string;
  /** Mensaje para el login cuando se salió del bloqueo por un motivo (sesión vencida, etc.). */
  avisoAcceso: string;
  limpiarAvisoAcceso: () => void;
  /** Pide la huella. Devuelve null si entró, o el mensaje a mostrar si no. */
  desbloquear: () => Promise<string | null>;
  activarBiometria: (username: string, password: string, verificar?: boolean) => Promise<void>;
  desactivarBiometria: () => Promise<void>;
  /** "Usar mi contraseña": cierra la sesión guardada y muestra el login. */
  omitirBloqueo: () => Promise<void>;
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
  const [bioDisponible, setBioDisponible] = useState(false);
  const [bioActiva, setBioActiva] = useState(false);
  const [bloqueada, setBloqueada] = useState(false);
  const [nombreBio, setNombreBio] = useState("");
  const [avisoAcceso, setAvisoAcceso] = useState("");

  const usuarioRef = useRef<UsuarioOut | null>(null);
  usuarioRef.current = usuario;
  const bioActivaRef = useRef(false);
  bioActivaRef.current = bioActiva;

  const aplicarSesion = (sesion: SesionOut) => {
    setUsuario(sesion.usuario);
    setPermisos(sesion.permisos);
    setAvisoAcceso("");
  };

  const quitarSesion = () => {
    vaciarCache(); // nada del usuario anterior (listas, conversación del asistente) debe verse en la sesión siguiente
    setUsuario(null);
    setPermisos([]);
  };

  // Si el servidor rechaza renovar la sesión, se vuelve al login en lugar de
  // quedar "dentro" con un token muerto (cada pantalla fallaría en silencio).
  // Con huella activa se deja el bloqueo puesto: al desbloquear, la
  // contraseña guardada vuelve a iniciar sesión sola.
  useEffect(() => {
    onSesionExpirada(() => {
      quitarSesion();
      if (bioActivaRef.current) setBloqueada(true);
      else setAvisoAcceso("Tu sesión venció. Inicia sesión de nuevo.");
    });
    return () => onSesionExpirada(null);
  }, []);

  // Al abrir la app: si hay token guardado, se revalida contra /api/auth/me
  // en vez de confiar ciegamente en lo que quedó en el teléfono — un rol
  // cambiado o una cuenta desactivada se refleja al instante, igual que en
  // el panel web (ver frontend/lib/auth.tsx).
  //
  // Con la huella activada la sesión igual se restaura (para que las
  // llamadas sigan entrando), pero la pantalla queda bloqueada hasta que
  // se autentique quien tiene el teléfono en la mano.
  useEffect(() => {
    (async () => {
      const [activa, disponible] = await Promise.all([biometriaActiva(), biometriaDisponible()]);
      setBioDisponible(disponible);
      // Si la huella se borró del teléfono, no dejar la app bloqueada para siempre.
      const usaHuella = activa && disponible;
      if (usaHuella) {
        setBioActiva(true);
        setBloqueada(true);
        setNombreBio(await nombreGuardado());
      } else if (activa) {
        await borrarBiometria();
      }

      const haySesion = await cargarSesionGuardada();
      if (haySesion) {
        try {
          aplicarSesion(await peticion<SesionOut>("/api/auth/me"));
        } catch {
          // Sin red o sesión inválida: queda sin usuario. Los tokens que
          // sigan cargados se descartan al elegir "Usar mi contraseña".
        }
      }
      setCargando(false);
    })();
  }, []);

  // Vuelve a bloquear si la app estuvo un rato en segundo plano. Solo cuenta
  // `background`: en iOS `inactive` también ocurre con el diálogo del
  // micrófono, el lector de huella o el centro de notificaciones, y contarlo
  // volvía a bloquear al terminar de contestar un permiso.
  const enFondoDesdeRef = useRef<number | null>(null);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (estado) => {
      if (estado === "background") {
        if (enFondoDesdeRef.current === null) enFondoDesdeRef.current = Date.now();
      } else if (estado === "active") {
        const desde = enFondoDesdeRef.current;
        enFondoDesdeRef.current = null;
        if (bioActivaRef.current && desde && Date.now() - desde > BLOQUEO_TRAS_MS) setBloqueada(true);
      }
    });
    return () => sub.remove();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const servidor = await servidorConfigurado();
    const sesion = await iniciarSesion(servidor, username, password);
    aplicarSesion(sesion);
    recordarUsuario(username).catch(() => {});
  }, []);

  const desbloquear = useCallback(async (): Promise<string | null> => {
    // Sesión vigente: basta con confirmar quién tiene el teléfono.
    if (usuarioRef.current) {
      if (await autenticar("Desbloquea NSPBX")) {
        setBloqueada(false);
        return null;
      }
      return "No se pudo verificar tu huella.";
    }

    // Sin sesión (venció): la huella libera la contraseña guardada y se entra sola.
    const lectura = await leerCredenciales();
    if (lectura.estado === "cancelado") return "Cancelaste la verificación. Toca para intentarlo de nuevo.";
    if (lectura.estado === "invalidada") {
      await borrarBiometria();
      setBioActiva(false);
      setBloqueada(false);
      setAvisoAcceso("Cambiaron las huellas del teléfono. Inicia sesión con tu contraseña.");
      return null;
    }

    const servidor = await servidorConfigurado();
    try {
      aplicarSesion(await iniciarSesion(servidor, lectura.cred.username, lectura.cred.password));
      setBloqueada(false);
      return null;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        // La contraseña cambió en el panel: la guardada ya no sirve.
        await borrarBiometria();
        setBioActiva(false);
        setBloqueada(false);
        setAvisoAcceso("Tu contraseña cambió. Inicia sesión de nuevo para volver a activar la huella.");
        return null;
      }
      return "No se pudo conectar con el servidor. Revisa tu conexión.";
    }
  }, []);

  const activarBiometria = useCallback(async (username: string, password: string, verificar = false) => {
    if (verificar) {
      const servidor = await servidorConfigurado();
      // Se comprueba la contraseña ANTES de guardarla: si estuviera mal, la
      // huella dejaría al usuario fuera sin saber por qué. No toca la sesión
      // activa (ver verificarSoloContrasena).
      await verificarSoloContrasena(servidor, username, password);
    }
    await guardarBiometria({ username, password }, usuarioRef.current?.full_name ?? username);
    setNombreBio(usuarioRef.current?.full_name ?? username);
    setBioActiva(true);
  }, []);

  const desactivarBiometria = useCallback(async () => {
    await borrarBiometria();
    setBioActiva(false);
    setBloqueada(false);
  }, []);

  // "Usar mi contraseña" no puede ser una puerta trasera: si la sesión seguía
  // cargada, quitar el bloqueo dejaba la app abierta sin huella. Se cierra la
  // sesión (tokens) y se pasa al login; la contraseña guardada se conserva
  // para reintentar la huella más tarde.
  const omitirBloqueo = useCallback(async () => {
    await cerrarSesionApi();
    quitarSesion();
    setBloqueada(false);
  }, []);

  const logout = useCallback(async () => {
    // Antes de cerrar sesión: si no se borra el token de push del
    // backend, alguien que cerró sesión seguiría recibiendo el push de
    // "te está entrando una llamada" — sin sesión para hacer nada con él.
    let voip: ReturnType<typeof getVoIPPushToken> = null;
    try {
      voip = getVoIPPushToken();
    } catch {
      // sin Firebase/push configurado: no hay token que borrar
    }
    try {
      if (voip) {
        const platform = voip.type === "APNS_VOIP" ? "ios" : "android";
        await peticion(`/api/auth/dispositivo/${platform}`, { method: "DELETE" }).catch(() => {});
      }
    } finally {
      // Pase lo que pase con la red o el almacenamiento, el estado local se
      // limpia: cerrar sesión no puede quedar a medias.
      // El nombre de usuario se conserva (no es secreto y ahorra escribir); la
      // contraseña guardada NO: cerrar sesión tiene que dejar el teléfono sin acceso.
      await cerrarSesionApi().catch(() => {});
      await borrarBiometria().catch(() => {});
      setBioActiva(false);
      setBloqueada(false);
      quitarSesion();
    }
  }, []);

  const puede = useCallback((permiso: string) => permisos.includes(permiso), [permisos]);

  const value = useMemo(
    () => ({
      cargando,
      usuario,
      permisos,
      puede,
      login,
      logout,
      bioDisponible,
      bioActiva,
      bloqueada,
      nombreBio,
      avisoAcceso,
      limpiarAvisoAcceso: () => setAvisoAcceso(""),
      desbloquear,
      activarBiometria,
      desactivarBiometria,
      omitirBloqueo,
    }),
    [
      cargando,
      usuario,
      permisos,
      puede,
      login,
      logout,
      bioDisponible,
      bioActiva,
      bloqueada,
      nombreBio,
      avisoAcceso,
      desbloquear,
      activarBiometria,
      desactivarBiometria,
      omitirBloqueo,
    ]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
