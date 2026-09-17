/**
 * `sip.js` (igual que el panel web, ver frontend/lib/softphone-context.tsx)
 * espera encontrar WebRTC en globales de navegador: `RTCPeerConnection`,
 * `RTCSessionDescription`, `RTCIceCandidate`, `navigator.mediaDevices`.
 * React Native no los trae — `@livekit/react-native-webrtc` los
 * implementa, pero como clases exportadas, no como globales. Sin este
 * polyfill, `sip.js` revienta al primer intento de armar un
 * PeerConnection con "RTCPeerConnection is not defined".
 *
 * Se importa una sola vez, antes de que se monte cualquier pantalla — ver
 * app/_layout.tsx.
 */
import {
  MediaStream,
  RTCIceCandidate,
  RTCPeerConnection,
  RTCSessionDescription,
  mediaDevices,
} from "@livekit/react-native-webrtc";

// `as any`: los tipos DOM ambientes (lib "DOM" en tsconfig, necesaria para
// que sip.js tipe bien contra el navegador) no coinciden con las clases
// reales de `@livekit/react-native-webrtc` — es exactamente lo que este
// polyfill reemplaza en tiempo de ejecución, así que el choque de tipos
// acá es esperado y no un error real.
const globalAny = globalThis as any;

export function instalarPolyfillWebRTC(): void {
  globalAny.RTCPeerConnection = RTCPeerConnection;
  globalAny.RTCSessionDescription = RTCSessionDescription;
  globalAny.RTCIceCandidate = RTCIceCandidate;
  globalAny.MediaStream = MediaStream;
  if (!globalAny.navigator) globalAny.navigator = {};
  globalAny.navigator.mediaDevices = mediaDevices;
}
