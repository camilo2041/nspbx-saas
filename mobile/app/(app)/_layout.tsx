import { Redirect, Tabs } from "expo-router";
import { Text } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { colores } from "@/src/tema";

// Emojis y no una librería de iconos: sin fuente de iconos instalada, el
// icono por defecto de las pestañas se dibuja como un rectángulo vacío.
const icono = (emoji: string) =>
  function Icono({ focused }: { focused: boolean }) {
    return <Text style={{ fontSize: 22, opacity: focused ? 1 : 0.45 }}>{emoji}</Text>;
  };

export default function AppLayout() {
  const { cargando, usuario } = useAuth();

  if (cargando) return null;
  if (!usuario) return <Redirect href="/login" />;

  return (
    <Tabs
      screenOptions={{
        headerTitleAlign: "left",
        headerStyle: { backgroundColor: colores.superficie },
        headerShadowVisible: false,
        headerTitleStyle: { color: colores.texto, fontWeight: "700", fontSize: 18 },
        tabBarActiveTintColor: colores.marca,
        tabBarInactiveTintColor: colores.textoSecundario,
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
        tabBarStyle: { backgroundColor: colores.superficie, borderTopColor: colores.borde },
        sceneStyle: { backgroundColor: colores.fondo },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Teléfono", tabBarIcon: icono("📞") }} />
      <Tabs.Screen name="metrics" options={{ title: "Métricas", tabBarIcon: icono("📊") }} />
      <Tabs.Screen name="settings" options={{ title: "Cuenta", tabBarIcon: icono("👤") }} />
    </Tabs>
  );
}
