import { StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { Pressable } from "react-native";

import { colores } from "@/src/tema";

import { useSoftphone } from "@/src/softphone/SoftphoneContext";

const TECLAS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

function formatoTiempo(segundos: number): string {
  const m = Math.floor(segundos / 60)
    .toString()
    .padStart(2, "0");
  const s = (segundos % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export default function DialScreen() {
  const {
    entorno,
    connState,
    connError,
    phase,
    destination,
    remoteParty,
    muted,
    callSeconds,
    setDestination,
    call,
    hangup,
    toggleMute,
    sendDtmf,
    activarDnd,
  } = useSoftphone();

  if (!entorno) {
    return (
      <View style={styles.centro}>
        <Text style={styles.info}>Tu usuario no tiene una extensión asignada o no tenés permiso para usar el teléfono.</Text>
      </View>
    );
  }

  const enLlamada = phase !== "idle";

  return (
    <View style={styles.contenedor}>
      <View style={styles.encabezado}>
        <Text style={styles.extension}>Extensión {entorno.extension?.number}</Text>
        <Text style={styles.estado}>
          {connState === "registered" ? "Conectado" : connState === "connecting" ? "Conectando…" : connState === "error" ? "Sin conexión" : "Desconectado"}
        </Text>
        {connError ? <Text style={styles.error}>{connError}</Text> : null}
        <View style={styles.dndFila}>
          <Text style={styles.dndTexto}>No molestar</Text>
          <Switch value={Boolean(entorno.extension?.dnd)} onValueChange={activarDnd} />
        </View>
      </View>

      {enLlamada ? (
        <View style={styles.enLlamada}>
          <Text style={styles.remoto}>{remoteParty}</Text>
          <Text style={styles.fase}>
            {phase === "outgoing" && "Llamando…"}
            {phase === "incoming" && "Llamada entrante…"}
            {phase === "in-call" && formatoTiempo(callSeconds)}
          </Text>
          <View style={styles.controles}>
            <Pressable style={styles.botonRedondo} onPress={toggleMute}>
              <Text style={styles.botonRedondoTexto}>{muted ? "🔇" : "🎙️"}</Text>
            </Pressable>
            <Pressable style={[styles.botonRedondo, styles.colgar]} onPress={hangup}>
              <Text style={styles.botonRedondoTexto}>📞</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <View style={styles.marcador}>
          <TextInput
            style={styles.pantalla}
            value={destination}
            onChangeText={setDestination}
            placeholder="Número a marcar"
            placeholderTextColor={colores.placeholder}
            keyboardType="phone-pad"
          />
          <View style={styles.teclado}>
            {TECLAS.map((tecla) => (
              <Pressable key={tecla} style={styles.tecla} onPress={() => sendDtmf(tecla)}>
                <Text style={styles.teclaTexto}>{tecla}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable
            style={[styles.botonRedondo, styles.llamar, !destination && styles.botonDeshabilitado]}
            onPress={call}
            disabled={!destination}
          >
            <Text style={styles.botonRedondoTexto}>📞</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  contenedor: { flex: 1, backgroundColor: colores.fondo, padding: 20 },
  centro: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  info: { textAlign: "center", color: colores.textoSecundario, fontSize: 15 },
  encabezado: { alignItems: "center", gap: 4, marginBottom: 24 },
  extension: { fontSize: 20, fontWeight: "700", color: colores.texto },
  estado: { color: colores.textoSecundario },
  error: { color: "#c0392b", fontSize: 13 },
  dndTexto: { color: colores.texto },
  dndFila: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8 },
  marcador: { flex: 1, alignItems: "center", justifyContent: "space-between", paddingBottom: 24 },
  pantalla: { fontSize: 28, textAlign: "center", width: "100%", paddingVertical: 12, color: colores.texto },
  teclado: { flexDirection: "row", flexWrap: "wrap", justifyContent: "center", gap: 16, maxWidth: 300 },
  tecla: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: "#f0f0f0",
    alignItems: "center",
    justifyContent: "center",
  },
  teclaTexto: { fontSize: 26, fontWeight: "600", color: colores.texto },
  botonRedondo: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#eee",
  },
  botonRedondoTexto: { fontSize: 30 },
  llamar: { backgroundColor: "#2ecc71" },
  colgar: { backgroundColor: "#e74c3c" },
  botonDeshabilitado: { opacity: 0.4 },
  enLlamada: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16 },
  remoto: { fontSize: 26, fontWeight: "700", color: colores.texto },
  fase: { fontSize: 18, color: colores.textoSecundario },
  controles: { flexDirection: "row", gap: 24, marginTop: 24 },
});
