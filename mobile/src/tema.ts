/**
 * Tema de la app: los mismos colores del panel web (src/tokens.json, que
 * scripts/verificar-tokens.js compara con frontend/app/globals.css) en modo
 * claro y oscuro.
 *
 * Las pantallas nunca usan un color suelto: piden la paleta con `useColores()`
 * o arman sus estilos con `crearEstilos((c) => ({...}))`, así el cambio de
 * tema llega a todo sin reiniciar la app.
 *
 * Los colores de texto, placeholder y fondo de los campos se fijan siempre
 * explícitos: varios Android pintan el TextInput con los del sistema y, si no,
 * el placeholder queda invisible.
 */
import { File, Paths } from "expo-file-system";
import { createContext, createElement, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

import tokens from "./tokens.json";

export type Paleta = typeof tokens.claro;
export type Preferencia = "sistema" | "claro" | "oscuro";

export const paletas: { claro: Paleta; oscuro: Paleta } = { claro: tokens.claro, oscuro: tokens.oscuro };

export const radios = { chico: 10, medio: 14, grande: 20, pildora: 999 };
export const espacio = { xs: 4, s: 8, m: 12, l: 16, xl: 24, xxl: 32 };
export const texto = {
  titulo: { fontSize: 26, fontWeight: "800" as const, letterSpacing: -0.4 },
  subtitulo: { fontSize: 18, fontWeight: "700" as const },
  cuerpo: { fontSize: 15 },
  chico: { fontSize: 13 },
  mini: { fontSize: 11, fontWeight: "700" as const, letterSpacing: 0.6, textTransform: "uppercase" as const },
};

export function sombraDe(c: Paleta, nivel: 1 | 2 | 3 = 1) {
  const oscuro = c === paletas.oscuro;
  return {
    shadowColor: c.sombra,
    shadowOpacity: oscuro ? 0.5 : [0.05, 0.08, 0.16][nivel - 1],
    shadowRadius: [3, 10, 24][nivel - 1],
    shadowOffset: { width: 0, height: [1, 4, 12][nivel - 1] },
    elevation: oscuro ? 0 : [1, 2, 6][nivel - 1],
  };
}

interface Tema {
  c: Paleta;
  oscuro: boolean;
  preferencia: Preferencia;
  setPreferencia: (p: Preferencia) => void;
}

const archivo = () => new File(Paths.document, "tema.json");

function leerPreferencia(): Preferencia {
  try {
    const f = archivo();
    if (f.exists) {
      const p = JSON.parse(f.textSync()).preferencia;
      if (p === "claro" || p === "oscuro" || p === "sistema") return p;
    }
  } catch {
    // archivo dañado: se usa el del sistema
  }
  return "sistema";
}

const TemaCtx = createContext<Tema>({
  c: paletas.claro,
  oscuro: false,
  preferencia: "sistema",
  setPreferencia: () => {},
});

export function TemaProvider({ children }: { children: ReactNode }) {
  const sistema = useColorScheme();
  const [preferencia, setPref] = useState<Preferencia>(leerPreferencia);

  // Las vistas nativas (teclado, selector de fecha, diálogos) siguen al tema
  // elegido en la app y no al del sistema.
  useEffect(() => {
    Appearance.setColorScheme(preferencia === "sistema" ? "unspecified" : preferencia === "oscuro" ? "dark" : "light");
  }, [preferencia]);

  const setPreferencia = useCallback((p: Preferencia) => {
    setPref(p);
    try {
      archivo().write(JSON.stringify({ preferencia: p }));
    } catch {
      // sin disco: vale para esta sesión
    }
  }, []);

  const oscuro = preferencia === "sistema" ? sistema === "dark" : preferencia === "oscuro";
  const valor = useMemo(
    () => ({ c: oscuro ? paletas.oscuro : paletas.claro, oscuro, preferencia, setPreferencia }),
    [oscuro, preferencia, setPreferencia]
  );
  return createElement(TemaCtx.Provider, { value: valor }, children);
}

export const useTema = () => useContext(TemaCtx);
export const useColores = () => useContext(TemaCtx).c;

/**
 * Estilos que dependen del tema. Se calculan una vez por paleta:
 *
 *   const useEstilos = crearEstilos((c) => ({ caja: { backgroundColor: c.superficie } }));
 *   function Pantalla() { const e = useEstilos(); ... }
 */
export function crearEstilos<T extends StyleSheet.NamedStyles<T>>(fabrica: (c: Paleta) => T) {
  const cache = new Map<Paleta, T>();
  return function useEstilos(): T {
    const c = useColores();
    let e = cache.get(c);
    if (!e) {
      e = StyleSheet.create(fabrica(c));
      cache.set(c, e);
    }
    return e;
  };
}
