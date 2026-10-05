import { Stack } from "expo-router";

import { useColores } from "@/src/tema";

export default function MenuLayout() {
  const c = useColores();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: c.superficie },
        headerShadowVisible: false,
        headerTitleStyle: { color: c.texto, fontWeight: "700", fontSize: 18 },
        headerTintColor: c.marca,
        contentStyle: { backgroundColor: c.fondo },
      }}
    >
      <Stack.Screen name="index" options={{ title: "Menú" }} />
      <Stack.Screen name="cuenta" options={{ title: "Mi cuenta" }} />
      <Stack.Screen name="citas" options={{ title: "Citas" }} />
      <Stack.Screen name="supervision" options={{ title: "Supervisión" }} />
      <Stack.Screen name="reportes" options={{ title: "Reportes" }} />
      <Stack.Screen name="contactos" options={{ title: "Contactos" }} />
      <Stack.Screen name="cobranza" options={{ title: "Cobranza" }} />
      <Stack.Screen name="campanas" options={{ title: "Campañas" }} />
      <Stack.Screen name="campana/[id]" options={{ title: "Campaña" }} />
      <Stack.Screen name="pausas-disposiciones" options={{ title: "Pausas y disposiciones" }} />
      <Stack.Screen name="rutas-entrantes" options={{ title: "Rutas entrantes" }} />
      <Stack.Screen name="rutas-salientes" options={{ title: "Rutas salientes" }} />
      <Stack.Screen name="colas" options={{ title: "Colas" }} />
      <Stack.Screen name="roles" options={{ title: "Roles y permisos" }} />
      <Stack.Screen name="ajustes" options={{ title: "Ajustes" }} />
      <Stack.Screen name="consumo" options={{ title: "Consumo de IA" }} />
      <Stack.Screen name="seguridad" options={{ title: "Seguridad" }} />
      <Stack.Screen name="empresas" options={{ title: "Empresas" }} />
      <Stack.Screen name="troncales" options={{ title: "Troncales" }} />
      <Stack.Screen name="extensiones" options={{ title: "Extensiones" }} />
      <Stack.Screen name="usuarios" options={{ title: "Usuarios" }} />
      <Stack.Screen name="bots" options={{ title: "Voizbots" }} />
      <Stack.Screen name="probar-bot" options={{ title: "Probar bot" }} />
    </Stack>
  );
}
