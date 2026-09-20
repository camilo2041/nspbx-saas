import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, peticion } from "@/src/api/client";

/**
 * Datos del servidor con caché en memoria ("mostrar lo último que hay y
 * actualizar en segundo plano"), como hacen las apps que se sienten rápidas:
 * al volver a una pantalla la lista aparece al instante y se refresca sola.
 *
 * - `ttl`: hasta cuándo se considera fresco un dato (no se vuelve a pedir).
 * - Si la red falla y hay datos guardados, se siguen mostrando y se marca
 *   `sinConexion` (en vez de dejar la pantalla en blanco con un error).
 */
interface Entrada {
  datos: unknown;
  ts: number;
}

const cache = new Map<string, Entrada>();
const enVuelo = new Map<string, Promise<unknown>>();

/** Olvida lo guardado de las rutas que empiezan por `prefijo` (tras crear/editar/borrar). */
export function invalidar(prefijo: string): void {
  for (const k of [...cache.keys()]) if (k.startsWith(prefijo)) cache.delete(k);
}

/** Conversación del asistente: vive mientras la app está abierta y se borra al cerrar sesión. */
export const conversacionAsistente: { lista: { role: "user" | "assistant"; content: string; error?: boolean }[] } = { lista: [] };

/** Vacía toda la caché (al cerrar sesión: no debe quedar nada de otro usuario). */
export function vaciarCache(): void {
  cache.clear();
  enVuelo.clear();
  conversacionAsistente.lista = [];
}

async function pedir<T>(path: string): Promise<T> {
  // Dos pantallas que piden lo mismo a la vez comparten UNA petición.
  const previa = enVuelo.get(path);
  if (previa) return previa as Promise<T>;
  const p = peticion<T>(path).then(
    (d) => {
      cache.set(path, { datos: d, ts: Date.now() });
      enVuelo.delete(path);
      return d;
    },
    (e) => {
      enVuelo.delete(path);
      throw e;
    }
  );
  enVuelo.set(path, p);
  return p;
}

export function useDatos<T>(path: string | null, opciones: { ttl?: number } = {}) {
  const ttl = opciones.ttl ?? 20_000;
  const inicial = path ? (cache.get(path)?.datos as T | undefined) : undefined;
  const [datos, setDatos] = useState<T | undefined>(inicial);
  const [cargando, setCargando] = useState(inicial === undefined && !!path);
  const [refrescando, setRefrescando] = useState(false);
  const [error, setError] = useState("");
  const [sinConexion, setSinConexion] = useState(false);
  const vivo = useRef(true);

  useEffect(() => {
    vivo.current = true;
    return () => {
      vivo.current = false;
    };
  }, []);

  const cargar = useCallback(
    async (forzar = false) => {
      if (!path) return;
      const previo = cache.get(path);
      if (previo && !forzar && Date.now() - previo.ts < ttl) {
        setDatos(previo.datos as T);
        setCargando(false);
        return;
      }
      if (previo) setDatos(previo.datos as T);
      if (forzar) setRefrescando(true);
      else if (!previo) setCargando(true);
      try {
        const d = await pedir<T>(path);
        if (!vivo.current) return;
        setDatos(d);
        setError("");
        setSinConexion(false);
      } catch (e) {
        if (!vivo.current) return;
        if (e instanceof ApiError) {
          setError(e.message);
          setSinConexion(false);
        } else if (previo) {
          setSinConexion(true); // sin red pero con datos viejos: se siguen mostrando
        } else {
          setError("No hay conexión con el servidor. Revisa tu internet e inténtalo de nuevo.");
        }
      } finally {
        if (vivo.current) {
          setCargando(false);
          setRefrescando(false);
        }
      }
    },
    [path, ttl]
  );

  // Al abrir la ruta y cada vez que la pantalla vuelve a estar a la vista.
  useFocusEffect(
    useCallback(() => {
      cargar(false);
    }, [cargar])
  );

  const mutar = useCallback(
    (fn: (actual: T | undefined) => T | undefined) => {
      setDatos((actual) => {
        const nuevo = fn(actual);
        if (path && nuevo !== undefined) cache.set(path, { datos: nuevo, ts: Date.now() });
        return nuevo;
      });
    },
    [path]
  );

  return { datos, cargando, refrescando, error, sinConexion, recargar: () => cargar(true), mutar };
}
