import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from "expo-audio";
import { Vibration } from "react-native";

/**
 * Timbre propio de la app para llamadas entrantes con la app abierta.
 *
 * El timbre del sistema (el de la notificación de llamada) depende del modo del
 * teléfono: en silencio o "no molestar" no suena, y la persona cree que la
 * llamada no entró. Este se reproduce por el volumen multimedia, así que suena
 * aunque el teléfono esté en silencio (pero no si el volumen multimedia está a 0).
 */
let player: AudioPlayer | null = null;

export async function iniciarTimbre(): Promise<void> {
  if (player) return;
  try {
    await setAudioModeAsync({ playsInSilentMode: true, interruptionMode: "duckOthers" });
    const p = createAudioPlayer(require("../assets/sounds/ring.wav"));
    p.loop = true;
    p.play();
    player = p;
  } catch (e) {
    console.warn("No se pudo reproducir el timbre:", e instanceof Error ? e.message : "error");
  }
  Vibration.vibrate([0, 700, 900], true);
}

export function detenerTimbre(): void {
  Vibration.cancel();
  const p = player;
  player = null;
  if (!p) return;
  try {
    p.pause();
    p.remove();
  } catch {
    // ya estaba liberado
  }
}

/** Para el botón «Probar timbre» del diagnóstico: suena unos segundos y se corta solo. */
export async function probarTimbre(segundos = 4): Promise<void> {
  await iniciarTimbre();
  setTimeout(detenerTimbre, segundos * 1000);
}
