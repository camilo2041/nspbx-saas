import { Redirect, Tabs } from "expo-router";

import { useAuth } from "@/src/auth/AuthContext";

export default function AppLayout() {
  const { cargando, usuario } = useAuth();

  if (cargando) return null;
  if (!usuario) return <Redirect href="/login" />;

  return (
    <Tabs screenOptions={{ headerTitleAlign: "center" }}>
      <Tabs.Screen name="index" options={{ title: "Teléfono" }} />
      <Tabs.Screen name="metrics" options={{ title: "Métricas" }} />
      <Tabs.Screen name="settings" options={{ title: "Cuenta" }} />
    </Tabs>
  );
}
