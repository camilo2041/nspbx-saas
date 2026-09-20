import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";
import { useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, EstadoVacio, Fila, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { Pildora } from "@/src/ui";
import { Text, View } from "react-native";
import { colores } from "@/src/tema";

interface Bot {
  id: number;
  name: string;
  bot_type: string;
  enabled: boolean;
  welcome_message: string | null;
}

export default function Bots() {
  const router = useRouter();
  const { puede } = useAuth();
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Bot[]>("/api/voicebots");
  const puedeProbar = puede("voizbots:gestionar");

  return (
    <Pantalla refrescando={refrescando} onRefrescar={recargar}>
      <Aviso
        tono="ok"
        texto="Toca un bot para probarlo: conversas con él como un cliente, sin llamar y sin tocar la agenda ni la cobranza reales."
      />
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
      {datos && datos.length === 0 ? (
        <EstadoVacio icono="🤖" titulo="Aún no hay bots" texto="Créalos desde el panel web; aquí podrás probarlos." />
      ) : null}
      {(datos ?? []).map((b) => (
        <Fila
          key={b.id}
          titulo={b.name}
          subtitulo={b.welcome_message ? b.welcome_message.slice(0, 70) : b.bot_type === "ai" ? "Asistente con IA" : "Menú de voz"}
          izquierda={
            <View style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: colores.marcaSuave, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ fontSize: 20 }}>{b.bot_type === "ai" ? "🧠" : "🔢"}</Text>
            </View>
          }
          derecha={<Pildora texto={b.enabled ? (b.bot_type === "ai" ? "IA" : "Menú") : "Apagado"} tono={b.enabled ? "ok" : "neutro"} />}
          onPress={() => {
            if (!puedeProbar) return;
            router.push({ pathname: "/administrar/probar-bot", params: { id: String(b.id), nombre: b.name, tipo: b.bot_type } });
          }}
        />
      ))}
      {!puedeProbar && datos?.length ? (
        <Aviso tono="aviso" texto="Tu rol puede ver los bots pero no probarlos (la prueba usa el modelo de IA de la empresa)." />
      ) : null}
    </Pantalla>
  );
}
