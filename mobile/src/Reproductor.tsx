import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useEffect, useState } from "react";
import { GestureResponderEvent, LayoutChangeEvent, Pressable, Text, View } from "react-native";

import { cabeceraAuth, peticion, urlApi } from "@/src/api/client";
import { Esqueleto } from "@/src/gestion";
import { impacto } from "@/src/haptico";
import { Icono } from "@/src/Icono";
import { useColores } from "@/src/tema";

export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function Reproductor({ fuente }: { fuente: { uri: string; headers: Record<string, string> } }) {
  const col = useColores();
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
        <View style={{ height: 6, borderRadius: 3, backgroundColor: col.superficie3, overflow: "hidden" }}>
          <View style={{ height: 6, width: `${dur ? (pos / dur) * 100 : 0}%`, backgroundColor: col.marca }} />
        </View>
      </Pressable>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: 12, color: col.textoSecundario }}>{mmss(pos)}</Text>
        <Text style={{ fontSize: 12, color: col.textoSecundario }}>{dur ? mmss(dur) : estado.isBuffering ? "Cargando…" : "--:--"}</Text>
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 28 }}>
        <Pressable onPress={() => saltar(-10)} hitSlop={10} accessibilityLabel="Retroceder 10 segundos">
          <Icono nombre="retroceder10" tam={28} color={col.textoSuave} />
        </Pressable>
        <Pressable
          onPress={alternar}
          accessibilityLabel={estado.playing ? "Pausar" : "Reproducir"}
          style={{ width: 60, height: 60, borderRadius: 30, backgroundColor: col.marca, alignItems: "center", justifyContent: "center" }}
        >
          <Icono nombre={estado.playing ? "pausa" : "reproducir"} tam={28} color={col.sobreMarca} />
        </Pressable>
        <Pressable onPress={() => saltar(10)} hitSlop={10} accessibilityLabel="Adelantar 10 segundos">
          <Icono nombre="adelantar10" tam={28} color={col.textoSuave} />
        </Pressable>
      </View>
    </View>
  );
}

/** Reproductor de un audio de la API (grabación, mensaje de buzón): antes
 * una petición liviana, para que si el token venció se renueve y la cabecera
 * del audio salga al día. */
export function AudioDeApi({ ruta }: { ruta: string }) {
  const [fuente, setFuente] = useState<{ uri: string; headers: Record<string, string> } | null>(null);
  useEffect(() => {
    let vivo = true;
    peticion("/api/auth/me")
      .catch(() => {})
      .finally(() => vivo && setFuente({ uri: urlApi(ruta), headers: cabeceraAuth() }));
    return () => {
      vivo = false;
    };
  }, [ruta]);
  return fuente ? <Reproductor fuente={fuente} /> : <Esqueleto alto={90} />;
}
