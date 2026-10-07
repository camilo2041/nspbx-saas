import { Redirect, Tabs, useRouter } from "expo-router";
import { ColorValue, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth/AuthContext";
import { GuiaFlotante } from "@/src/GuiaFlotante";
import { impacto } from "@/src/haptico";
import { Icono, NombreIcono } from "@/src/Icono";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { sombraDe, useColores } from "@/src/tema";

const icono = (nombre: NombreIcono) =>
  function IconoPestana({ color, focused }: { color: ColorValue; focused: boolean }) {
    return <Icono nombre={nombre} tam={focused ? 25 : 23} color={color} />;
  };

/** Botón flotante del asistente: siempre a mano, sobre la barra de pestañas. */
function BotonAsistente() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const c = useColores();
  const { phase } = useSoftphone();
  // En plena llamada no estorba: la pantalla del teléfono necesita todo el espacio.
  if (phase !== "idle") return null;
  return (
    <View pointerEvents="box-none" style={{ position: "absolute", right: 16, bottom: 72 + insets.bottom }}>
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
            backgroundColor: c.marca,
            alignItems: "center",
            justifyContent: "center",
            ...sombraDe(c, 3),
          },
          pressed && { transform: [{ scale: 0.94 }] },
        ]}
      >
        <Icono nombre="asistente" tam={24} color={c.sobreMarca} />
      </Pressable>
    </View>
  );
}

/**
 * Pestañas: lo que se usa todo el día (teléfono, llamadas, resumen) y el menú
 * con el resto del sistema, agrupado igual que la barra lateral del panel web.
 */
export default function AppLayout() {
  const { cargando, usuario, puede } = useAuth();
  const c = useColores();

  if (cargando) return null;
  if (!usuario) return <Redirect href="/login" />;

  const veLlamadas = puede("llamadas:ver_propias") || puede("llamadas:ver_todas");

  return (
    <View style={{ flex: 1, backgroundColor: c.fondo }}>
      <Tabs
        screenOptions={{
          headerTitleAlign: "left",
          headerStyle: { backgroundColor: c.superficie },
          headerShadowVisible: false,
          headerTitleStyle: { color: c.texto, fontWeight: "700", fontSize: 18 },
          tabBarActiveTintColor: c.marca,
          tabBarInactiveTintColor: c.textoSecundario,
          tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
          tabBarStyle: { backgroundColor: c.superficie, borderTopColor: c.borde },
          sceneStyle: { backgroundColor: c.fondo },
          lazy: true,
        }}
      >
        <Tabs.Screen name="index" options={{ title: "Teléfono", tabBarIcon: icono("telefono") }} />
        <Tabs.Screen
          name="llamadas"
          options={{ title: "Llamadas", tabBarIcon: icono("historial"), href: veLlamadas ? undefined : null }}
        />
        <Tabs.Screen name="metrics" options={{ title: "Resumen", tabBarIcon: icono("metricas") }} />
        <Tabs.Screen name="administrar" options={{ title: "Menú", headerShown: false, tabBarIcon: icono("mas") }} />
      </Tabs>
      <BotonAsistente />
      <GuiaFlotante />
    </View>
  );
}
