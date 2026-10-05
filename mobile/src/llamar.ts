import { useRouter } from "expo-router";
import { useCallback } from "react";

import { impacto } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";

/**
 * Marca un número desde cualquier pantalla y lleva al teléfono, donde se ve
 * la llamada (o el motivo si no pudo salir).
 */
export function useLlamar() {
  const router = useRouter();
  const { call } = useSoftphone();
  return useCallback(
    (numero: string | null | undefined) => {
      const limpio = (numero ?? "").replace(/[^0-9+*#]/g, "");
      if (!limpio) return;
      impacto();
      call(limpio);
      router.navigate("/");
    },
    [call, router]
  );
}
