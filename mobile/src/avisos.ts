import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { peticion } from "@/src/api/client";

/**
 * Avisos que no son llamadas (mensaje de voz nuevo) en el iPhone.
 *
 * El token de PushKit (expo-callkit-telecom) solo sirve para llamadas: Apple
 * cierra la app que lo usa para otra cosa. Para los avisos se pide el token
 * APNs normal y se registra aparte («ios-avisos»), así el backend nunca lo
 * confunde con el de llamadas. En Android el token de FCM ya sirve para los dos.
 */
export async function registrarAvisosIos(): Promise<void> {
  if (Platform.OS !== "ios") return;
  const permiso = await Notifications.getPermissionsAsync();
  const concedido = permiso.granted || (await Notifications.requestPermissionsAsync({
    ios: { allowAlert: true, allowBadge: true, allowSound: true },
  })).granted;
  if (!concedido) return;
  const token = await Notifications.getDevicePushTokenAsync();
  if (typeof token.data !== "string" || !token.data) return;
  await peticion("/api/auth/dispositivo", {
    method: "POST",
    body: { platform: "ios-avisos", token_type: "APNS", token: token.data },
  });
}

/** El número del ícono de la app: los mensajes de voz sin escuchar. */
export function ponerInsignia(sinEscuchar: number): void {
  if (Platform.OS !== "ios") return;
  Notifications.setBadgeCountAsync(Math.max(0, sinEscuchar)).catch(() => {});
}
