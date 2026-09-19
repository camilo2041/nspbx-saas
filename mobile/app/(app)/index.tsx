import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";

import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { colores, radios, sombra } from "@/src/tema";
import { Boton, Pildora, Tarjeta } from "@/src/ui";

const TECLAS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

function formatoTiempo(segundos: number): string {
  const m = Math.floor(segundos / 60).toString().padStart(2, "0");
  const s = (segundos % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function Teclado({ onTecla }: { onTecla: (t: string) => void }) {
  return (
    <View style={estilos.teclado}>
      {TECLAS.map((tecla) => (
        <Pressable
          key={tecla}
          onPress={() => onTecla(tecla)}
          style={({ pressed }) => [estilos.tecla, pressed && { backgroundColor: colores.marcaSuave, borderColor: colores.marca }]}
        >
          <Text style={estilos.teclaTexto}>{tecla}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function BotonControl({
  icono,
  etiqueta,
  activo,
  onPress,
}: {
  icono: string;
  etiqueta: string;
  activo?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={estilos.controlCol}>
      <View style={[estilos.control, activo && { backgroundColor: colores.marca, borderColor: colores.marca }]}>
        <Text style={{ fontSize: 24 }}>{icono}</Text>
      </View>
      <Text style={estilos.controlEtiqueta}>{etiqueta}</Text>
    </Pressable>
  );
}

export default function TelefonoScreen() {
  const {
    entorno,
    connState,
    connError,
    phase,
    destination,
    remoteParty,
    muted,
    speaker,
    callSeconds,
    setDestination,
    connect,
    call,
    answer,
    reject,
    hangup,
    toggleMute,
    toggleSpeaker,
    sendDtmf,
    activarDnd,
  } = useSoftphone();
  const [tecladoAbierto, setTecladoAbierto] = useState(false);

  if (!entorno?.extension) {
    return (
      <View style={estilos.vacio}>
        <Tarjeta style={{ alignItems: "center", gap: 8 }}>
          <Text style={{ fontSize: 32 }}>📵</Text>
          <Text style={estilos.vacioTitulo}>Sin extensión</Text>
          <Text style={estilos.vacioTexto}>
            Tu usuario no tiene una extensión asignada o su rol no usa el teléfono. Pídele a un administrador que te
            asigne una.
          </Text>
        </Tarjeta>
      </View>
    );
  }

  const ext = entorno.extension;
  const estado =
    connState === "registered"
      ? { texto: "Conectado", tono: "ok" as const }
      : connState === "connecting"
        ? { texto: "Conectando…", tono: "aviso" as const }
        : connState === "error"
          ? { texto: "Sin conexión", tono: "peligro" as const }
          : { texto: "Desconectado", tono: "neutro" as const };

  return (
    <ScrollView style={{ backgroundColor: colores.fondo }} contentContainerStyle={estilos.contenido}>
      <Tarjeta style={{ gap: 12 }}>
        <View style={estilos.fila}>
          <View style={{ flex: 1 }}>
            <Text style={estilos.mini}>Mi extensión</Text>
            <Text style={estilos.extension}>{ext.number}</Text>
            {ext.caller_id_name ? <Text style={estilos.nombre}>{ext.caller_id_name}</Text> : null}
          </View>
          <Pildora texto={estado.texto} tono={estado.tono} />
        </View>

        {connError ? (
          <View style={estilos.aviso}>
            <Text style={estilos.avisoTexto}>{connError}</Text>
            {connState === "error" ? (
              <Pressable onPress={() => connect()}>
                <Text style={estilos.reintentar}>Reintentar ahora</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        <View style={[estilos.fila, estilos.separador]}>
          <View style={{ flex: 1 }}>
            <Text style={estilos.dndTitulo}>No molestar</Text>
            <Text style={estilos.dndDetalle}>Rechaza las llamadas entrantes</Text>
          </View>
          <Switch
            value={Boolean(ext.dnd)}
            onValueChange={(v) => activarDnd(v).catch(() => {})}
            trackColor={{ false: colores.bordeFuerte, true: colores.marca }}
            thumbColor="#fff"
          />
        </View>
      </Tarjeta>

      {phase === "incoming" ? (
        <View style={estilos.entrante}>
          <View style={estilos.entranteCabecera}>
            <Text style={estilos.entranteMini}>LLAMADA ENTRANTE</Text>
            <Text style={estilos.entranteQuien} numberOfLines={1}>
              {remoteParty}
            </Text>
          </View>
          <View style={estilos.entranteBotones}>
            <Boton titulo="Rechazar" variante="peligro" onPress={reject} style={{ flex: 1 }} />
            <Boton titulo="Contestar" variante="ok" onPress={answer} style={{ flex: 1 }} />
          </View>
        </View>
      ) : phase === "idle" ? (
        <>
          <Tarjeta style={estilos.pantalla}>
            <Text style={[estilos.numero, !destination && { color: colores.placeholder }]} numberOfLines={1}>
              {destination || "Número a marcar"}
            </Text>
            {destination ? (
              <Pressable
                onPress={() => setDestination(destination.slice(0, -1))}
                onLongPress={() => setDestination("")}
                hitSlop={12}
              >
                <Text style={estilos.borrar}>⌫</Text>
              </Pressable>
            ) : null}
          </Tarjeta>

          <Teclado onTecla={sendDtmf} />

          <Boton
            titulo="Llamar"
            variante="ok"
            onPress={call}
            deshabilitado={!destination || connState !== "registered"}
            style={estilos.llamar}
          />
          {connState !== "registered" ? (
            <Text style={estilos.ayuda}>Espera a que la extensión diga “Conectado” para llamar.</Text>
          ) : null}
        </>
      ) : (
        <Tarjeta style={{ alignItems: "center", gap: 6, paddingVertical: 22 }}>
          <Text style={estilos.mini}>{phase === "in-call" ? "EN LLAMADA" : "LLAMANDO"}</Text>
          <Text style={estilos.enLlamadaQuien} numberOfLines={1}>
            {remoteParty}
          </Text>
          <Text style={estilos.tiempo}>{phase === "in-call" ? formatoTiempo(callSeconds) : "Timbrando…"}</Text>

          {tecladoAbierto ? <Teclado onTecla={sendDtmf} /> : null}

          <View style={estilos.controles}>
            <BotonControl icono={muted ? "🔇" : "🎙️"} etiqueta={muted ? "Activar" : "Silenciar"} activo={muted} onPress={toggleMute} />
            <BotonControl icono="🔊" etiqueta="Altavoz" activo={speaker} onPress={toggleSpeaker} />
            <BotonControl
              icono="⌨️"
              etiqueta="Teclado"
              activo={tecladoAbierto}
              onPress={() => setTecladoAbierto((v) => !v)}
            />
          </View>

          <Boton titulo="Colgar" variante="peligro" onPress={hangup} style={{ alignSelf: "stretch", marginTop: 8 }} />
        </Tarjeta>
      )}
    </ScrollView>
  );
}

const TAM_TECLA = 76;

const estilos = StyleSheet.create({
  contenido: { padding: 16, gap: 14 },
  vacio: { flex: 1, justifyContent: "center", padding: 20, backgroundColor: colores.fondo },
  vacioTitulo: { fontSize: 17, fontWeight: "700", color: colores.texto },
  vacioTexto: { textAlign: "center", color: colores.textoSecundario, fontSize: 14, lineHeight: 20 },
  fila: { flexDirection: "row", alignItems: "center", gap: 12 },
  separador: { borderTopWidth: 1, borderTopColor: colores.borde, paddingTop: 12 },
  mini: { fontSize: 11, fontWeight: "700", color: colores.textoSecundario, letterSpacing: 0.6, textTransform: "uppercase" },
  extension: { fontSize: 30, fontWeight: "800", color: colores.texto, letterSpacing: -0.5 },
  nombre: { fontSize: 14, color: colores.textoSecundario },
  aviso: { backgroundColor: colores.peligroSuave, borderRadius: 10, padding: 10, gap: 4 },
  avisoTexto: { color: colores.peligroTexto, fontSize: 13 },
  reintentar: { color: colores.marcaTexto, fontWeight: "700", fontSize: 13 },
  dndTitulo: { fontSize: 15, fontWeight: "600", color: colores.texto },
  dndDetalle: { fontSize: 12, color: colores.textoSecundario },

  pantalla: { flexDirection: "row", alignItems: "center", justifyContent: "center", minHeight: 64, paddingVertical: 10 },
  numero: { flex: 1, fontSize: 30, fontWeight: "600", textAlign: "center", color: colores.texto },
  borrar: { fontSize: 24, color: colores.textoSecundario, paddingHorizontal: 6 },
  teclado: { flexDirection: "row", flexWrap: "wrap", justifyContent: "center", gap: 14, alignSelf: "center", maxWidth: TAM_TECLA * 3 + 28 + 4 },
  tecla: {
    width: TAM_TECLA,
    height: TAM_TECLA,
    borderRadius: TAM_TECLA / 2,
    backgroundColor: colores.superficie,
    borderWidth: 1,
    borderColor: colores.borde,
    alignItems: "center",
    justifyContent: "center",
    ...sombra,
  },
  teclaTexto: { fontSize: 28, fontWeight: "500", color: colores.texto },
  llamar: { minHeight: 56, borderRadius: 28 },
  ayuda: { textAlign: "center", fontSize: 12, color: colores.textoSecundario },

  entrante: {
    backgroundColor: colores.superficie,
    borderRadius: radios.grande,
    borderWidth: 2,
    borderColor: colores.aviso,
    overflow: "hidden",
    ...sombra,
  },
  entranteCabecera: { backgroundColor: colores.avisoSuave, padding: 16, gap: 2 },
  entranteMini: { fontSize: 11, fontWeight: "700", color: colores.avisoTexto, letterSpacing: 0.6 },
  entranteQuien: { fontSize: 24, fontWeight: "800", color: colores.texto },
  entranteBotones: { flexDirection: "row", gap: 10, padding: 12 },

  enLlamadaQuien: { fontSize: 26, fontWeight: "800", color: colores.texto },
  tiempo: { fontSize: 20, color: colores.textoSecundario, marginBottom: 6, fontVariant: ["tabular-nums"] },
  controles: { flexDirection: "row", justifyContent: "space-evenly", alignSelf: "stretch", marginTop: 10 },
  controlCol: { alignItems: "center", gap: 6 },
  control: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: colores.superficie3,
    borderWidth: 1,
    borderColor: colores.borde,
    alignItems: "center",
    justifyContent: "center",
  },
  controlEtiqueta: { fontSize: 12, color: colores.textoSuave },
});
