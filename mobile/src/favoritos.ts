import { File, Paths } from "expo-file-system";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/src/auth/AuthContext";

/** Un favorito guardado en el teléfono (no viaja al servidor). */
export interface Favorito {
  numero: string;
  nombre: string;
}

const soloDigitos = (s: string) => s.replace(/[^0-9+*#]/g, "");

/**
 * Favoritos de quien tiene la sesión abierta. Se guardan en un archivo POR
 * USUARIO: en un equipo compartido, la lista de un turno no aparece en el
 * siguiente.
 */
export function useFavoritos() {
  const { usuario } = useAuth();
  const archivo = usuario ? new File(Paths.document, `favoritos-${usuario.id}.json`) : null;
  const [lista, setLista] = useState<Favorito[]>([]);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        if (archivo && archivo.exists) {
          const datos = JSON.parse(await archivo.text());
          if (vivo && Array.isArray(datos)) setLista(datos.filter((f) => f && typeof f.numero === "string"));
        } else if (vivo) {
          setLista([]);
        }
      } catch {
        if (vivo) setLista([]);
      }
    })();
    return () => {
      vivo = false;
    };
    // el archivo depende solo del usuario
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usuario?.id]);

  const guardar = useCallback(
    (nueva: Favorito[]) => {
      setLista(nueva);
      try {
        if (!archivo) return;
        if (!archivo.exists) archivo.create();
        archivo.write(JSON.stringify(nueva));
      } catch {
        // sin disco no se persiste, pero la lista sigue viva en esta sesión
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [usuario?.id]
  );

  const esFavorito = useCallback((numero: string) => lista.some((f) => soloDigitos(f.numero) === soloDigitos(numero)), [lista]);

  const alternar = useCallback(
    (f: Favorito) => {
      const n = soloDigitos(f.numero);
      guardar(esFavorito(f.numero) ? lista.filter((x) => soloDigitos(x.numero) !== n) : [...lista, { ...f, numero: n }]);
    },
    [lista, esFavorito, guardar]
  );

  return { favoritos: lista, esFavorito, alternar };
}
