import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { View } from "react-native";

import { AuthProvider, useAuth } from "@/src/auth/AuthContext";
import { Bloqueo } from "@/src/Bloqueo";
import { escucharErroresGlobales } from "@/src/errores";
import { SoftphoneProvider } from "@/src/softphone/SoftphoneContext";
import { TemaProvider, useTema } from "@/src/tema";

// Los errores sin atrapar llegan a Plataforma (con sesión; sin ella el envío falla en silencio).
escucharErroresGlobales();

function Contenido() {
  const { cargando, bloqueada } = useAuth();
  const { c, oscuro } = useTema();
  const oculta = !cargando && bloqueada;
  const cabecera = {
    headerShown: true,
    headerTintColor: c.marca,
    headerTitleStyle: { color: c.texto, fontWeight: "700" as const },
    headerStyle: { backgroundColor: c.superficie },
    headerShadowVisible: false,
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.fondo }}>
      <StatusBar style={oscuro ? "light" : "dark"} />
      {/* Con el bloqueo puesto, la app de abajo no debe recibir toques ni ser
          alcanzable por lectores de pantalla (TalkBack/VoiceOver): una capa
          encima solo tapa lo visible, no lo bloquea. */}
      <View
        style={{ flex: 1 }}
        pointerEvents={oculta ? "none" : "auto"}
        accessibilityElementsHidden={oculta}
        importantForAccessibility={oculta ? "no-hide-descendants" : "auto"}
      >
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.fondo } }}>
          <Stack.Screen name="asistente" options={{ ...cabecera, presentation: "modal", title: "Asistente" }} />
          <Stack.Screen name="diagnostico" options={{ ...cabecera, title: "Llamadas entrantes" }} />
          <Stack.Screen name="llamada/[id]" options={{ ...cabecera, title: "Llamada" }} />
        </Stack>
      </View>
      <Bloqueo />
    </View>
  );
}

export default function RootLayout() {
  return (
    <TemaProvider>
      <AuthProvider>
        <SoftphoneProvider>
          <Contenido />
        </SoftphoneProvider>
      </AuthProvider>
    </TemaProvider>
  );
}
