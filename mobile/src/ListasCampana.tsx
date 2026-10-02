import { useEffect } from "react";
import { ActionSheetIOS, Alert, Platform, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { FilaSwitch } from "@/src/gestion";
import { fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, Seccion, Tarjeta } from "@/src/ui";

interface Lista {
  id: number;
  nombre: string;
  activa: boolean;
  prioridad: number;
  origen: "manual" | "csv" | "api";
  total: number;
  pendientes: number;
}

const ORIGEN: Record<Lista["origen"], string> = { manual: "Carga manual", csv: "CSV", api: "API" };
const PRIORIDADES = [10, 5, 1, 0, -1, -5];

/**
 * Las cargas de una campaña (igual que en el panel): pausar una lista deja
 * sus números esperando; la prioridad decide cuál se marca primero.
 * `version` cambia al cargar números nuevos.
 */
export function ListasCampana({ campaignId, version, onCambio }: { campaignId: string; version: number; onCambio: () => void }) {
  const c = useColores();
  const ruta = `/api/campaigns/${campaignId}/listas`;
  const { datos, recargar } = useDatos<Lista[]>(ruta, { ttl: 5_000 });

  useEffect(() => {
    if (version) recargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const cambiar = async (l: Lista, cambios: Partial<Pick<Lista, "activa" | "prioridad">>) => {
    try {
      await peticion(`${ruta}/${l.id}`, { method: "PUT", body: cambios });
      invalidar(ruta);
      recargar();
      onCambio();
    } catch (err) {
      fallo();
      Alert.alert("No se pudo actualizar la lista", err instanceof Error ? err.message : "Error");
    }
  };

  const elegirPrioridad = (l: Lista) => {
    const etiquetas = PRIORIDADES.map((p) => (p > 0 ? `+${p}` : String(p)));
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        { title: "Prioridad", message: "Las de prioridad más alta se marcan primero", options: [...etiquetas, "Cancelar"], cancelButtonIndex: etiquetas.length },
        (i) => {
          if (i < PRIORIDADES.length) cambiar(l, { prioridad: PRIORIDADES[i] });
        }
      );
      return;
    }
    Alert.alert("Prioridad", "Las de prioridad más alta se marcan primero", [
      ...PRIORIDADES.slice(0, 3).map((p) => ({ text: p > 0 ? `+${p}` : String(p), onPress: () => cambiar(l, { prioridad: p }) })),
      { text: "Cancelar", style: "cancel" as const },
    ]);
  };

  if (!datos || datos.length === 0) return null;
  return (
    <Seccion titulo="Listas" sinTarjeta>
      <View style={{ gap: 8 }}>
        {datos.map((l) => (
          <Tarjeta key={l.id} style={{ gap: 8 }}>
            <FilaSwitch
              titulo={l.nombre}
              ayuda={`${ORIGEN[l.origen]} · ${l.total} número(s) · ${l.pendientes} pendiente(s)${l.activa ? "" : " · en pausa"}`}
              valor={l.activa}
              onChange={(v) => cambiar(l, { activa: v })}
            />
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={{ fontSize: 12.5, color: c.textoSecundario }}>Prioridad {l.prioridad > 0 ? `+${l.prioridad}` : l.prioridad}</Text>
              <Boton titulo="Cambiar" variante="texto" chico onPress={() => elegirPrioridad(l)} />
            </View>
          </Tarjeta>
        ))}
      </View>
    </Seccion>
  );
}
