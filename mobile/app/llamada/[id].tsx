import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { GestureResponderEvent, LayoutChangeEvent, Pressable, ScrollView, Text, View } from "react-native";

import { ApiError, cabeceraAuth, peticion, urlApi } from "@/src/api/client";
import type { CallLogOut } from "@/src/api/types";
import { useDatos } from "@/src/datos";
import { Aviso, Avatar, Esqueleto } from "@/src/gestion";
import { exito, fallo, impacto } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { colores, radios } from "@/src/tema";
import { Boton, Pildora, Tarjeta } from "@/src/ui";

interface Detalle extends CallLogOut {
  has_recording?: boolean;
  hangup_cause?: string | null;
  answered_at?: string | null;
  ended_at?: string | null;
}

const ESTADOS: Record<string, { texto: string; tono: "ok" | "aviso" | "peligro" | "neutro" }> = {
  answered: { texto: "Contestada", tono: "ok" },
  no_answer: { texto: "Sin respuesta", tono: "aviso" },
  busy: { texto: "Ocupado", tono: "aviso" },
  failed: { texto: "Fallida", tono: "peligro" },
  cancelled: { texto: "Cancelada", tono: "neutro" },
  rejected: { texto: "Rechazada", tono: "peligro" },
};

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Reproductor({ fuente }: { fuente: { uri: string; headers: Record<string, string> } }) {
  const player = useAudioPlayer(fuente);
  const estado = useAudioPlayerStatus(player);
  const [ancho, setAncho] = useState(1);
  const dur = estado.duration || 0;
  const pos = Math.min(estado.currentTime || 0, dur || 0);

  const alternar = () => {
    impacto();
    if (estado.playing) player.pause();
    else {
      // Al terminar, vuelve al principio antes de reproducir de nuevo.
      if (dur > 0 && pos >= dur - 0.3) player.seekTo(0).catch(() => {});
      player.play();
    }
  };
  const saltar = (delta: number) => player.seekTo(Math.max(0, Math.min(dur, pos + delta))).catch(() => {});
  const tocarBarra = (e: GestureResponderEvent) => {
    if (dur > 0) player.seekTo((e.nativeEvent.locationX / ancho) * dur).catch(() => {});
  };

  return (
    <View style={{ gap: 12 }}>
      <Pressable onPress={tocarBarra} onLayout={(e: LayoutChangeEvent) => setAncho(e.nativeEvent.layout.width || 1)} hitSlop={{ top: 10, bottom: 10 }}>
        <View style={{ height: 6, borderRadius: 3, backgroundColor: colores.superficie3, overflow: "hidden" }}>
          <View style={{ height: 6, width: `${dur ? (pos / dur) * 100 : 0}%`, backgroundColor: colores.marca }} />
        </View>
      </Pressable>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: 12, color: colores.textoSecundario }}>{mmss(pos)}</Text>
        <Text style={{ fontSize: 12, color: colores.textoSecundario }}>{dur ? mmss(dur) : estado.isBuffering ? "Cargando…" : "--:--"}</Text>
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 28 }}>
        <Pressable onPress={() => saltar(-10)} hitSlop={10}>
          <Text style={{ fontSize: 13, fontWeight: "700", color: colores.textoSuave }}>⏪ 10 s</Text>
        </Pressable>
        <Pressable
          onPress={alternar}
          style={{ width: 60, height: 60, borderRadius: 30, backgroundColor: colores.marca, alignItems: "center", justifyContent: "center" }}
        >
          <Text style={{ color: "#fff", fontSize: 24 }}>{estado.playing ? "⏸" : "▶"}</Text>
        </Pressable>
        <Pressable onPress={() => saltar(10)} hitSlop={10}>
          <Text style={{ fontSize: 13, fontWeight: "700", color: colores.textoSuave }}>10 s ⏩</Text>
        </Pressable>
      </View>
    </View>
  );
}

function Grabacion({ id }: { id: string }) {
  const [fuente, setFuente] = useState<{ uri: string; headers: Record<string, string> } | null>(null);
  useEffect(() => {
    let vivo = true;
    // Una petición liviana primero: si el token venció, se renueva y la cabecera sale al día.
    peticion("/api/auth/me")
      .catch(() => {})
      .finally(() => vivo && setFuente({ uri: urlApi(`/api/calls/${id}/recording`), headers: cabeceraAuth() }));
    return () => {
      vivo = false;
    };
  }, [id]);
  return fuente ? <Reproductor fuente={fuente} /> : <Esqueleto alto={90} />;
}

export default function DetalleLlamada() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { call } = useSoftphone();
  const { datos: c, cargando, error } = useDatos<Detalle>(id ? `/api/calls/${id}` : null, { ttl: 60_000 });
  const [resumen, setResumen] = useState("");
  const [resumiendo, setResumiendo] = useState(false);
  const [errorResumen, setErrorResumen] = useState("");

  const resumir = async () => {
    setResumiendo(true);
    setErrorResumen("");
    try {
      const r = await peticion<{ summary?: string; reason?: string }>(`/api/calls/${id}/summary`);
      setResumen(r.summary || r.reason || "No se pudo generar un resumen de esta llamada.");
      exito();
    } catch (e) {
      fallo();
      setErrorResumen(e instanceof ApiError ? e.message : "No se pudo generar el resumen. Revisa tu conexión.");
    } finally {
      setResumiendo(false);
    }
  };

  if (cargando && !c) {
    return (
      <View style={{ flex: 1, backgroundColor: colores.fondo, padding: 16, gap: 12 }}>
        <Stack.Screen options={{ title: "Llamada" }} />
        <Esqueleto alto={110} />
        <Esqueleto alto={140} />
      </View>
    );
  }
  if (!c) {
    return (
      <View style={{ flex: 1, backgroundColor: colores.fondo, padding: 16 }}>
        <Stack.Screen options={{ title: "Llamada" }} />
        <Aviso texto={error || "No se encontró la llamada."} />
      </View>
    );
  }

  const entrante = c.direction === "inbound";
  const numero = (entrante ? c.caller_number : c.callee_number) ?? "";
  const nombre = (entrante ? c.caller_name : null) || numero || "Desconocido";
  const e = ESTADOS[c.status] ?? { texto: c.status, tono: "neutro" as const };
  const inicio = c.started_at ? new Date(c.started_at.endsWith("Z") ? c.started_at : `${c.started_at}Z`) : null;

  return (
    <View style={{ flex: 1, backgroundColor: colores.fondo }}>
      <Stack.Screen options={{ title: "Llamada", headerTintColor: colores.marca }} />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 60 }}>
        <Tarjeta style={{ alignItems: "center", gap: 10 }}>
          <Avatar nombre={nombre} tam={64} />
          <Text style={{ fontSize: 20, fontWeight: "700", color: colores.texto }}>{nombre}</Text>
          {nombre !== numero && numero ? <Text style={{ fontSize: 14, color: colores.textoSecundario }}>{numero}</Text> : null}
          <Pildora texto={e.texto} tono={e.tono} />
          <View style={{ flexDirection: "row", gap: 24, marginTop: 4 }}>
            <View style={{ alignItems: "center" }}>
              <Text style={{ fontSize: 12, color: colores.textoSecundario }}>{entrante ? "Entrante" : "Saliente"}</Text>
              <Text style={{ fontSize: 15, fontWeight: "600", color: colores.texto }}>{entrante ? "↙" : "↗"}</Text>
            </View>
            <View style={{ alignItems: "center" }}>
              <Text style={{ fontSize: 12, color: colores.textoSecundario }}>Duración</Text>
              <Text style={{ fontSize: 15, fontWeight: "600", color: colores.texto }}>{c.billsec > 0 ? mmss(c.billsec) : "—"}</Text>
            </View>
            <View style={{ alignItems: "center" }}>
              <Text style={{ fontSize: 12, color: colores.textoSecundario }}>Fecha</Text>
              <Text style={{ fontSize: 15, fontWeight: "600", color: colores.texto }}>
                {inicio ? inicio.toLocaleDateString("es-CO", { day: "numeric", month: "short" }) : "—"}
              </Text>
            </View>
            <View style={{ alignItems: "center" }}>
              <Text style={{ fontSize: 12, color: colores.textoSecundario }}>Hora</Text>
              <Text style={{ fontSize: 15, fontWeight: "600", color: colores.texto }}>
                {inicio ? inicio.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" }) : "—"}
              </Text>
            </View>
          </View>
        </Tarjeta>

        {numero ? (
          <Boton
            titulo={`Llamar a ${numero}`}
            variante="ok"
            onPress={() => {
              call(numero.replace(/[^0-9+*#]/g, ""));
              router.navigate("/");
            }}
          />
        ) : null}

        {c.has_recording ? (
          <Tarjeta style={{ gap: 8 }}>
            <Text style={{ fontSize: 14, fontWeight: "700", color: colores.texto }}>Grabación</Text>
            <Grabacion id={String(c.id)} />
          </Tarjeta>
        ) : (
          <Aviso tono="aviso" texto="Esta llamada no tiene grabación disponible." />
        )}

        {c.status === "answered" ? (
          <Tarjeta style={{ gap: 10 }}>
            <Text style={{ fontSize: 14, fontWeight: "700", color: colores.texto }}>Resumen con IA</Text>
            {resumen ? (
              <Text style={{ fontSize: 14, color: colores.textoSuave, lineHeight: 21 }}>{resumen}</Text>
            ) : (
              <Text style={{ fontSize: 12.5, color: colores.textoSecundario, lineHeight: 18 }}>
                Transcribe la llamada y la resume. Tarda unos segundos y usa el modelo de IA de la empresa.
              </Text>
            )}
            {errorResumen ? <Aviso texto={errorResumen} /> : null}
            {!resumen ? <Boton titulo="Generar resumen" variante="suave" onPress={resumir} cargando={resumiendo} /> : null}
          </Tarjeta>
        ) : null}

        {c.hangup_cause ? (
          <Text style={{ fontSize: 12, color: colores.placeholder, textAlign: "center", borderRadius: radios.chico }}>Motivo de fin: {c.hangup_cause}</Text>
        ) : null}
      </ScrollView>
    </View>
  );
}
