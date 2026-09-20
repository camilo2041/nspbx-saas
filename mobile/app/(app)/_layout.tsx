import { Redirect, Tabs, useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth/AuthContext";
import { impacto } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { colores, sombra } from "@/src/tema";

// Emojis y no una librería de iconos: sin fuente de iconos instalada, el
// icono por defecto de las pestañas se dibuja como un rectángulo vacío.
const icono = (emoji: string) =>
  function Icono({ focused }: { focused: boolean }) {
    return <Text style={{ fontSize: 22, opacity: focused ? 1 : 0.45 }}>{emoji}</Text>;
  };

/** Botón flotante del asistente: siempre a mano, sobre la barra de pestañas. */
function BotonAsistente() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { phase } = useSoftphone();
  // En plena llamada no estorba: la pantalla del teléfono necesita todo el espacio.
  if (phase !== "idle") return null;
  return (
    <View pointerEvents="box-none" style={{ position: "absolute", right: 16, bottom: 68 + insets.bottom }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Abrir el asistente"
        onPress={() => {
          impacto();
          router.push("/asistente");
        }}
        style={({ pressed }) => [
          {
            width: 54,
            height: 54,
            borderRadius: 27,
            backgroundColor: colores.marca,
            alignItems: "center",
            justifyContent: "center",
            ...sombra,
            shadowOpacity: 0.25,
          },
          pressed && { transform: [{ scale: 0.94 }] },
        ]}
      >
        <Text style={{ fontSize: 24 }}>✨</Text>
      </Pressable>
    </View>
  );
}

export default function AppLayout() {
  const { cargando, usuario, puede } = useAuth();

  if (cargando) return null;
  if (!usuario) return <Redirect href="/login" />;

  const veLlamadas = puede("llamadas:ver_propias") || puede("llamadas:ver_todas");
  const administra = puede("telefonia:gestionar") || puede("usuarios:gestionar") || puede("voizbots:ver");

  return (
    <View style={{ flex: 1 }}>
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
          lazy: true,
        }}
      >
        <Tabs.Screen name="index" options={{ title: "Teléfono", tabBarIcon: icono("📞") }} />
        <Tabs.Screen name="llamadas" options={{ title: "Llamadas", tabBarIcon: icono("🕘"), href: veLlamadas ? undefined : null }} />
        <Tabs.Screen name="metrics" options={{ title: "Métricas", tabBarIcon: icono("📊") }} />
        <Tabs.Screen
          name="administrar"
          options={{ title: "Administrar", headerShown: false, tabBarIcon: icono("🛠️"), href: administra ? undefined : null }}
        />
        <Tabs.Screen name="settings" options={{ title: "Cuenta", tabBarIcon: icono("👤") }} />
      </Tabs>
      <BotonAsistente />
    </View>
  );
}
