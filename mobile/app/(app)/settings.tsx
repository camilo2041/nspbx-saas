import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";

export default function SettingsScreen() {
  const { usuario, logout } = useAuth();

  const salir = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <View style={styles.contenedor}>
      <View style={styles.datos}>
        <Text style={styles.nombre}>{usuario?.full_name}</Text>
        <Text style={styles.detalle}>{usuario?.username}</Text>
        <Text style={styles.detalle}>Rol: {usuario?.role}</Text>
        {usuario?.extension_number && <Text style={styles.detalle}>Extensión: {usuario.extension_number}</Text>}
      </View>
      <Pressable style={styles.boton} onPress={salir}>
        <Text style={styles.botonTexto}>Cerrar sesión</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  contenedor: { flex: 1, backgroundColor: "#fff", padding: 20, justifyContent: "space-between" },
  datos: { gap: 4, marginTop: 12 },
  nombre: { fontSize: 20, fontWeight: "700" },
  detalle: { fontSize: 15, color: "#666" },
  boton: { backgroundColor: "#e74c3c", borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  botonTexto: { color: "#fff", fontSize: 16, fontWeight: "600" },
});
