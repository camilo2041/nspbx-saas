/**
 * Íconos nativos de cada plataforma: SF Symbols en iOS y Material Symbols en
 * Android (expo-symbols). Las pantallas usan un nombre propio ("colgar",
 * "historial"…) y no el de la librería, así cambiar un ícono es tocar una
 * línea acá.
 */
import { SymbolView, type AndroidSymbol, type SFSymbol } from "expo-symbols";
import { ColorValue, StyleProp, View, ViewStyle } from "react-native";

import { useColores } from "@/src/tema";

const ICONOS = {
  telefono: ["phone.fill", "call"],
  historial: ["clock.arrow.circlepath", "history"],
  metricas: ["chart.bar.fill", "bar_chart"],
  administrar: ["slider.horizontal.3", "tune"],
  cuenta: ["person.crop.circle", "account_circle"],
  asistente: ["sparkles", "auto_awesome"],
  buscar: ["magnifyingglass", "search"],
  cerrar: ["xmark", "close"],
  ver: ["eye", "visibility"],
  ocultar: ["eye.slash", "visibility_off"],
  colgar: ["phone.down.fill", "call_end"],
  microfono: ["mic.fill", "mic"],
  silenciado: ["mic.slash.fill", "mic_off"],
  altavoz: ["speaker.wave.2.fill", "volume_up"],
  teclado: ["circle.grid.3x3.fill", "dialpad"],
  pausa: ["pause.fill", "pause"],
  reproducir: ["play.fill", "play_arrow"],
  detener: ["stop.fill", "stop"],
  retroceder10: ["gobackward.10", "replay_10"],
  adelantar10: ["goforward.10", "forward_10"],
  transferir: ["arrow.turn.up.right", "phone_forwarded"],
  borrar: ["delete.left", "backspace"],
  entrante: ["phone.arrow.down.left", "call_received"],
  saliente: ["phone.arrow.up.right", "call_made"],
  perdida: ["phone.down", "call_missed"],
  favorito: ["star.fill", "star"],
  noFavorito: ["star", "star_outline"],
  bot: ["cpu", "smart_toy"],
  usuarios: ["person.2.fill", "group"],
  usuario: ["person.fill", "person"],
  troncal: ["point.3.connected.trianglepath.dotted", "hub"],
  extension: ["headphones", "headset_mic"],
  derecha: ["chevron.right", "chevron_right"],
  izquierda: ["chevron.left", "chevron_left"],
  agregar: ["plus", "add"],
  listo: ["checkmark", "check"],
  ok: ["checkmark.circle.fill", "check_circle"],
  error: ["xmark.octagon.fill", "error"],
  alerta: ["exclamationmark.triangle.fill", "warning"],
  info: ["info.circle", "info"],
  salir: ["rectangle.portrait.and.arrow.right", "logout"],
  candado: ["lock.fill", "lock"],
  huella: ["faceid", "fingerprint"],
  contactos: ["person.crop.rectangle.stack", "contacts"],
  refrescar: ["arrow.clockwise", "refresh"],
  enviar: ["paperplane.fill", "send"],
  diagnostico: ["stethoscope", "monitor_heart"],
  calendario: ["calendar", "calendar_month"],
  dinero: ["dollarsign.circle", "payments"],
  campana: ["megaphone.fill", "campaign"],
  sinRed: ["wifi.slash", "wifi_off"],
  tema: ["circle.lefthalf.filled", "contrast"],
  oscuro: ["moon.fill", "dark_mode"],
  claro: ["sun.max.fill", "light_mode"],
  notificaciones: ["bell.fill", "notifications"],
  editar: ["pencil", "edit"],
  eliminar: ["trash", "delete"],
  copiar: ["doc.on.doc", "content_copy"],
  buzon: ["recordingtape", "voicemail"],
  ajustes: ["gearshape.fill", "settings"],
  servidor: ["server.rack", "dns"],
  enLlamada: ["phone.connection.fill", "phone_in_talk"],
  audio: ["waveform", "graphic_eq"],
  mas: ["ellipsis", "more_horiz"],
  seguridad: ["shield.fill", "shield"],
  llave: ["key.fill", "key"],
  horario: ["clock", "schedule"],
  tendencia: ["chart.line.uptrend.xyaxis", "trending_up"],
  grabando: ["record.circle", "radio_button_checked"],
} as const satisfies Record<string, readonly [SFSymbol, AndroidSymbol]>;

export type NombreIcono = keyof typeof ICONOS;

export function Icono({
  nombre,
  tam = 22,
  color,
  style,
}: {
  nombre: NombreIcono;
  tam?: number;
  color?: ColorValue;
  style?: StyleProp<ViewStyle>;
}) {
  const c = useColores();
  const [ios, android] = ICONOS[nombre];
  return (
    <View style={[{ width: tam, height: tam, alignItems: "center", justifyContent: "center" }, style]} pointerEvents="none">
      <SymbolView
        name={{ ios, android, web: android }}
        size={tam}
        tintColor={color ?? c.texto}
        weight="medium"
        resizeMode="scaleAspectFit"
      />
    </View>
  );
}
