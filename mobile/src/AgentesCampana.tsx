import { useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { FilaSwitch } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, Seccion, Tarjeta } from "@/src/ui";

interface Agente {
  id: number;
  nombre: string;
  extension: string | null;
  asignado: boolean;
}

/** Quién trabaja la campaña (igual que en el panel). */
export function AgentesCampana({ campaignId }: { campaignId: string }) {
  const c = useColores();
  const ruta = `/api/campaigns/${campaignId}/agentes`;
  const { datos, recargar } = useDatos<Agente[]>(ruta, { ttl: 10_000 });
  const [elegidos, setElegidos] = useState<number[]>([]);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    // Se sincroniza con lo que dice el servidor cada vez que llega.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (datos) setElegidos(datos.filter((a) => a.asignado).map((a) => a.id));
  }, [datos]);

  if (!datos) return null;
  const cambiado = datos.some((a) => a.asignado !== elegidos.includes(a.id));

  const guardar = async () => {
    setGuardando(true);
    try {
      await peticion(ruta, { method: "PUT", body: { user_ids: elegidos } });
      exito();
      invalidar(ruta);
      recargar();
    } catch (err) {
      fallo();
      Alert.alert("No se pudo guardar", err instanceof Error ? err.message : "Error");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Seccion titulo="Agentes" sinTarjeta>
      <Tarjeta style={{ gap: 12 }}>
        {datos.length === 0 ? (
          <Text style={{ fontSize: 13, color: c.textoSecundario }}>
            Nadie puede trabajar como agente todavía: hace falta un usuario con extensión asignada.
          </Text>
        ) : (
          datos.map((a) => (
            <FilaSwitch
              key={a.id}
              titulo={a.nombre}
              ayuda={a.extension ? `Extensión ${a.extension}` : "Sin extensión"}
              valor={elegidos.includes(a.id)}
              onChange={(v) => setElegidos(v ? [...elegidos, a.id] : elegidos.filter((x) => x !== a.id))}
            />
          ))
        )}
        {cambiado ? <Boton titulo="Guardar agentes" cargando={guardando} onPress={guardar} /> : null}
        <View />
      </Tarjeta>
    </Seccion>
  );
}
