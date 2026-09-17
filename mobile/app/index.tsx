import { Redirect } from "expo-router";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";

export default function Index() {
  const { cargando, usuario } = useAuth();

  if (cargando) {
    return (
      <View style={styles.centro}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return <Redirect href={usuario ? "/(app)" : "/login"} />;
}

const styles = StyleSheet.create({
  centro: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#fff" },
});
