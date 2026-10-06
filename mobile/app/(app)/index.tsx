import { useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";

import { ControlesLlamada } from "@/src/ControlesLlamada";
import { Avatar } from "@/src/gestion";
import { toque } from "@/src/haptico";
import { Icono } from "@/src/Icono";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { crearEstilos, radios, sombraDe, useColores } from "@/src/tema";
import { BotonIcono, CajaIcono, Pildora, Tarjeta } from "@/src/ui";

const TECLAS: [string, string][] = [
  ["1", ""],
  ["2", "ABC"],
  ["3", "DEF"],
  ["4", "GHI"],
  ["5", "JKL"],
  ["6", "MNO"],
  ["7", "PQRS"],
  ["8", "TUV"],
  ["9", "WXYZ"],
  ["*", ""],
  ["0", "+"],
  ["#", ""],
];

function formatoTiempo(segundos: number): string {
  const m = Math.floor(segundos / 60).toString().padStart(2, "0");
  const s = (segundos % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function Teclado({ onTecla, compacto }: { onTecla: (t: string) => void; compacto?: boolean }) {
  const e = useEstilos();
  return (
    <View style={[e.teclado, compacto && { gap: 10 }]}>
      {TECLAS.map(([tecla, letras]) => (
        <Pressable
          key={tecla}
          accessibilityRole="button"
          accessibilityLabel={tecla}
          onPress={() => {
            toque();
            onTecla(tecla);
          }}
          // Mantener el 0 escribe "+" para marcar números internacionales (solo al
          // marcar: en llamada no hay tono DTMF "+").
          onLongPress={tecla === "0" && !compacto ? () => onTecla("+") : undefined}
          style={({ pressed }) => [e.tecla, compacto && e.teclaCompacta, pressed && e.teclaPresionada]}
        >
          <Text style={e.teclaTexto}>{tecla}</Text>
          {letras ? <Text style={e.teclaLetras}>{letras}</Text> : null}
        </Pressable>
      ))}
    </View>
  );
}

function Control({
  icono,
  etiqueta,
  activo,
  onPress,
}: {
  icono: Parameters<typeof BotonIcono>[0]["icono"];
  etiqueta: string;
  activo?: boolean;
  onPress: () => void;
}) {
  const e = useEstilos();
  return (
    <View style={e.controlCol}>
      <BotonIcono icono={icono} etiqueta={etiqueta} activo={activo} onPress={onPress} tam={64} />
      <Text style={e.controlEtiqueta}>{etiqueta}</Text>
    </View>
  );
}

export default function TelefonoScreen() {
  const c = useColores();
  const e = useEstilos();
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
      <View style={e.vacio}>
        <Tarjeta style={{ alignItems: "center", gap: 10, paddingVertical: 28 }}>
          <CajaIcono icono="extension" tono="neutro" tam={60} />
          <Text style={e.vacioTitulo}>Sin extensión</Text>
          <Text style={e.vacioTexto}>
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

  // --- Llamada entrante ------------------------------------------------------
  if (phase === "incoming") {
    return (
      <View style={e.llamada}>
        <View style={e.llamadaCabeza}>
          <Pildora texto="Llamada entrante" tono="aviso" icono="entrante" />
          <Avatar nombre={remoteParty || "?"} tam={96} />
          <Text style={e.quien} numberOfLines={1}>
            {remoteParty}
          </Text>
        </View>
        <View style={e.entranteBotones}>
          <View style={e.controlCol}>
            <BotonIcono icono="colgar" etiqueta="Rechazar" tono="peligro" relleno tam={72} onPress={reject} />
            <Text style={e.controlEtiqueta}>Rechazar</Text>
          </View>
          <View style={e.controlCol}>
            <BotonIcono icono="telefono" etiqueta="Contestar" tono="ok" relleno tam={72} onPress={answer} />
            <Text style={e.controlEtiqueta}>Contestar</Text>
          </View>
        </View>
      </View>
    );
  }

  // --- En llamada o llamando ---------------------------------------------------
  if (phase !== "idle") {
    return (
      <View style={e.llamada}>
        <View style={e.llamadaCabeza}>
          <Text style={e.mini}>{phase === "in-call" ? "En llamada" : "Llamando"}</Text>
          {tecladoAbierto ? null : <Avatar nombre={remoteParty || "?"} tam={96} />}
          <Text style={e.quien} numberOfLines={1}>
            {remoteParty}
          </Text>
          <Text style={e.tiempo}>{phase === "in-call" ? formatoTiempo(callSeconds) : "Timbrando…"}</Text>
        </View>

        {tecladoAbierto ? <Teclado onTecla={sendDtmf} compacto /> : null}

        <View style={{ gap: 18 }}>
          <View style={e.controles}>
            <Control icono={muted ? "silenciado" : "microfono"} etiqueta={muted ? "Activar" : "Silenciar"} activo={muted} onPress={toggleMute} />
            <Control icono="teclado" etiqueta="Teclado" activo={tecladoAbierto} onPress={() => setTecladoAbierto((v) => !v)} />
            <Control icono="altavoz" etiqueta="Altavoz" activo={speaker} onPress={toggleSpeaker} />
          </View>
          {/* Espera y transferir, con la llamada ya contestada. Con el teclado abierto
              se oculta sin desmontarse: no se pierde una consulta en curso. */}
          {phase === "in-call" ? (
            <View style={tecladoAbierto ? { display: "none" } : undefined}>
              <ControlesLlamada />
            </View>
          ) : null}
        </View>

        <BotonIcono icono="colgar" etiqueta="Colgar" tono="peligro" relleno tam={72} onPress={hangup} style={{ alignSelf: "center" }} />
      </View>
    );
  }

  // --- Marcador ----------------------------------------------------------------
  const listo = connState === "registered";
  return (
    <ScrollView style={{ backgroundColor: c.fondo }} contentContainerStyle={e.contenido}>
      <Tarjeta style={{ gap: 12, padding: 14 }}>
        <View style={e.fila}>
          <CajaIcono icono="extension" tono="marca" tam={44} />
          <View style={{ flex: 1 }}>
            <Text style={e.extension}>Ext. {ext.number}</Text>
            {ext.caller_id_name ? (
              <Text style={e.nombre} numberOfLines={1}>
                {ext.caller_id_name}
              </Text>
            ) : null}
          </View>
          <Pildora texto={estado.texto} tono={estado.tono} />
        </View>

        {connError ? (
          <View style={e.aviso}>
            <Icono nombre="alerta" tam={18} color={c.peligroTexto} />
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={e.avisoTexto}>{connError}</Text>
              {connState === "error" ? (
                <Pressable onPress={() => connect()} hitSlop={8}>
                  <Text style={e.reintentar}>Reintentar ahora</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        <View style={[e.fila, e.separador]}>
          <Icono nombre="notificaciones" tam={20} color={ext.dnd ? c.peligroTexto : c.textoSecundario} />
          <View style={{ flex: 1 }}>
            <Text style={e.dndTitulo}>No molestar</Text>
            <Text style={e.dndDetalle}>{ext.dnd ? "Las llamadas entrantes se rechazan" : "Recibes llamadas normalmente"}</Text>
          </View>
          <Switch
            value={Boolean(ext.dnd)}
            onValueChange={(v) => activarDnd(v).catch(() => {})}
            trackColor={{ false: c.bordeFuerte, true: c.peligro }}
            thumbColor="#fff"
          />
        </View>
      </Tarjeta>

      <View style={e.pantalla}>
        <Text
          style={[e.numero, !destination && { color: c.placeholder, fontSize: 22, fontWeight: "500" }]}
          numberOfLines={1}
          adjustsFontSizeToFit
        >
          {destination || "Ingresa un número"}
        </Text>
      </View>

      <Teclado onTecla={sendDtmf} />

      <View style={e.accionesMarcar}>
        <View style={{ width: 56 }} />
        <BotonIcono
          icono="telefono"
          etiqueta="Llamar"
          tono="ok"
          relleno
          tam={72}
          onPress={call}
          deshabilitado={!destination || !listo}
        />
        {destination ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Borrar"
            onPress={() => {
              toque();
              setDestination(destination.slice(0, -1));
            }}
            onLongPress={() => setDestination("")}
            hitSlop={12}
            style={e.borrar}
          >
            <Icono nombre="borrar" tam={26} color={c.textoSecundario} />
          </Pressable>
        ) : (
          <View style={{ width: 56 }} />
        )}
      </View>
      {!listo ? <Text style={e.ayuda}>Espera a que la extensión diga “Conectado” para llamar.</Text> : null}
    </ScrollView>
  );
}

const TAM_TECLA = 74;

const useEstilos = crearEstilos((c) => ({
  contenido: { padding: 16, gap: 14, paddingBottom: 110 },
  vacio: { flex: 1, justifyContent: "center", padding: 20, backgroundColor: c.fondo },
  vacioTitulo: { fontSize: 18, fontWeight: "700", color: c.texto },
  vacioTexto: { textAlign: "center", color: c.textoSecundario, fontSize: 14, lineHeight: 20 },
  fila: { flexDirection: "row", alignItems: "center", gap: 12 },
  separador: { borderTopWidth: 1, borderTopColor: c.borde, paddingTop: 12 },
  mini: { fontSize: 12, fontWeight: "700", color: c.textoSecundario, letterSpacing: 0.8, textTransform: "uppercase" },
  extension: { fontSize: 18, fontWeight: "800", color: c.texto, letterSpacing: -0.2 },
  nombre: { fontSize: 13, color: c.textoSecundario },
  aviso: { flexDirection: "row", gap: 8, backgroundColor: c.peligroSuave, borderRadius: radios.chico, padding: 10 },
  avisoTexto: { color: c.peligroTexto, fontSize: 13, lineHeight: 18 },
  reintentar: { color: c.marcaTexto, fontWeight: "700", fontSize: 13 },
  dndTitulo: { fontSize: 15, fontWeight: "600", color: c.texto },
  dndDetalle: { fontSize: 12, color: c.textoSecundario },

  pantalla: { minHeight: 56, alignItems: "center", justifyContent: "center", paddingHorizontal: 12 },
  numero: { fontSize: 34, fontWeight: "600", textAlign: "center", color: c.texto, letterSpacing: 1 },
  teclado: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 16,
    alignSelf: "center",
    maxWidth: TAM_TECLA * 3 + 32 + 4,
  },
  tecla: {
    width: TAM_TECLA,
    height: TAM_TECLA,
    borderRadius: TAM_TECLA / 2,
    backgroundColor: c.superficie,
    borderWidth: 1,
    borderColor: c.borde,
    alignItems: "center",
    justifyContent: "center",
    ...sombraDe(c, 1),
  },
  teclaCompacta: { width: 62, height: 62, borderRadius: 31 },
  teclaPresionada: { backgroundColor: c.marcaSuave, borderColor: c.marca },
  teclaTexto: { fontSize: 28, fontWeight: "500", color: c.texto, lineHeight: 32 },
  teclaLetras: { fontSize: 9.5, fontWeight: "700", color: c.textoSecundario, letterSpacing: 1.2 },
  accionesMarcar: { flexDirection: "row", alignItems: "center", justifyContent: "space-evenly", marginTop: 4 },
  borrar: { width: 56, height: 56, alignItems: "center", justifyContent: "center" },
  ayuda: { textAlign: "center", fontSize: 12, color: c.textoSecundario },

  llamada: { flex: 1, backgroundColor: c.fondo, padding: 24, paddingBottom: 40, justifyContent: "space-between" },
  llamadaCabeza: { alignItems: "center", gap: 12, marginTop: 24 },
  quien: { fontSize: 28, fontWeight: "800", color: c.texto, letterSpacing: -0.4 },
  tiempo: { fontSize: 18, color: c.textoSecundario, fontVariant: ["tabular-nums"] },
  entranteBotones: { flexDirection: "row", justifyContent: "space-around" },
  controles: { flexDirection: "row", justifyContent: "space-evenly" },
  controlCol: { alignItems: "center", gap: 8 },
  controlEtiqueta: { fontSize: 12.5, fontWeight: "500", color: c.textoSuave },
}));
