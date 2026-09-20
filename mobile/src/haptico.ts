import * as Haptics from "expo-haptics";

// Vibración corta de respuesta al tocar. Nunca debe romper la pantalla: en
// equipos sin motor háptico simplemente no hace nada.
export const toque = () => Haptics.selectionAsync().catch(() => {});
export const exito = () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
export const fallo = () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
export const impacto = () => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
