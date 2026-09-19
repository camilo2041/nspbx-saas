/**
 * `sip.js` (igual que el panel web, ver frontend/lib/softphone-context.tsx)
 * espera encontrar WebRTC en globales de navegador. React Native no los trae;
 * `@livekit/react-native-webrtc` los implementa como clases exportadas, no
 * como globales.
 *
 * Se usa `registerGlobals()` de la propia librería y NO una lista escrita a
 * mano: `sip.js` usa además `MediaStreamTrackEvent`, `MediaStreamTrack`,
 * `RTCRtpSender`, etc. Con la lista manual el REGISTRO funcionaba (no usa
 * audio) pero toda llamada fallaba en silencio con un `ReferenceError` al
 * agregar la pista de audio local.
 *
 * Se importa una sola vez, antes de que se monte cualquier pantalla.
 */
import { registerGlobals } from "@livekit/react-native-webrtc";

export function instalarPolyfillWebRTC(): void {
  registerGlobals();
}
