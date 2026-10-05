import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { useColores } from "@/src/tema";

export default function Index() {
  const { cargando, usuario } = useAuth();
  const c = useColores();

  if (cargando) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.fondo }}>
        <ActivityIndicator size="large" color={c.marca} />
      </View>
    );
  }

  return <Redirect href={usuario ? "/(app)" : "/login"} />;
}
