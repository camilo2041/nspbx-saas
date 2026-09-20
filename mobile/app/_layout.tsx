import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { View } from "react-native";

import { AuthProvider, useAuth } from "@/src/auth/AuthContext";
import { Bloqueo } from "@/src/Bloqueo";
import { SoftphoneProvider } from "@/src/softphone/SoftphoneContext";
import { colores } from "@/src/tema";

function Contenido() {
  const { cargando, bloqueada } = useAuth();
  const oculta = !cargando && bloqueada;

  return (
    <View style={{ flex: 1 }}>
      {/* Con el bloqueo puesto, la app de abajo no debe recibir toques ni ser
          alcanzable por lectores de pantalla (TalkBack/VoiceOver): una capa
          encima solo tapa lo visible, no lo bloquea. */}
      <View
        style={{ flex: 1 }}
        pointerEvents={oculta ? "none" : "auto"}
        accessibilityElementsHidden={oculta}
        importantForAccessibility={oculta ? "no-hide-descendants" : "auto"}
      >
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen
            name="asistente"
            options={{ headerShown: true, presentation: "modal", title: "Asistente", headerTintColor: colores.marca, headerStyle: { backgroundColor: colores.superficie }, headerShadowVisible: false }}
          />
          <Stack.Screen
            name="diagnostico"
            options={{ headerShown: true, title: "Llamadas entrantes", headerTintColor: colores.marca, headerStyle: { backgroundColor: colores.superficie }, headerShadowVisible: false }}
          />
          <Stack.Screen
            name="llamada/[id]"
            options={{ headerShown: true, title: "Llamada", headerTintColor: colores.marca, headerStyle: { backgroundColor: colores.superficie }, headerShadowVisible: false }}
          />
        </Stack>
      </View>
      <Bloqueo />
    </View>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <SoftphoneProvider>
        <StatusBar style="dark" />
        <Contenido />
      </SoftphoneProvider>
    </AuthProvider>
  );
}
