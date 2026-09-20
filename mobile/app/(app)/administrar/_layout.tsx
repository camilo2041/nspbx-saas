import { Stack } from "expo-router";

import { colores } from "@/src/tema";

export default function AdministrarLayout() {
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colores.superficie },
        headerShadowVisible: false,
        headerTitleStyle: { color: colores.texto, fontWeight: "700", fontSize: 18 },
        headerTintColor: colores.marca,
        contentStyle: { backgroundColor: colores.fondo },
      }}
    >
      <Stack.Screen name="index" options={{ title: "Administrar" }} />
      <Stack.Screen name="troncales" options={{ title: "Troncales" }} />
      <Stack.Screen name="extensiones" options={{ title: "Extensiones" }} />
      <Stack.Screen name="usuarios" options={{ title: "Usuarios" }} />
      <Stack.Screen name="bots" options={{ title: "Voizbots" }} />
      <Stack.Screen name="probar-bot" options={{ title: "Probar bot" }} />
    </Stack>
  );
}
