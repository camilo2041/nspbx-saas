import { Redirect, router } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { colores } from "@/src/tema";

export default function LoginScreen() {
  const { usuario, login } = useAuth();
  const [urlEmpresa, setUrlEmpresa] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  if (usuario) return <Redirect href="/(app)" />;

  const entrar = async () => {
    setError("");
    setCargando(true);
    try {
      await login(urlEmpresa, username, password);
      router.replace("/(app)");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo iniciar sesión");
    } finally {
      setCargando(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.contenedor}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView contentContainerStyle={styles.contenido} keyboardShouldPersistTaps="handled">
        <Text style={styles.titulo}>NSPBX</Text>
        <Text style={styles.subtitulo}>Iniciá sesión con tu extensión</Text>

        <Text style={styles.etiqueta}>Dirección de tu empresa</Text>
        <TextInput
          style={styles.input}
          placeholder="miempresa.pbx.midominio.com"
          placeholderTextColor={colores.placeholder}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          value={urlEmpresa}
          onChangeText={setUrlEmpresa}
        />

        <Text style={styles.etiqueta}>Usuario</Text>
        <TextInput
          style={styles.input}
          placeholder="tu usuario"
          placeholderTextColor={colores.placeholder}
          autoCapitalize="none"
          autoCorrect={false}
          value={username}
          onChangeText={setUsername}
        />

        <Text style={styles.etiqueta}>Contraseña</Text>
        <TextInput
          style={styles.input}
          placeholder="tu contraseña"
          placeholderTextColor={colores.placeholder}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Pressable
          style={[styles.boton, (cargando || !urlEmpresa || !username || !password) && styles.botonDeshabilitado]}
          onPress={entrar}
          disabled={cargando || !urlEmpresa || !username || !password}
        >
          {cargando ? <ActivityIndicator color="#fff" /> : <Text style={styles.botonTexto}>Entrar</Text>}
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  contenedor: { flex: 1, backgroundColor: colores.fondo },
  contenido: { flexGrow: 1, padding: 24, justifyContent: "center", gap: 6 },
  titulo: { fontSize: 32, fontWeight: "700", textAlign: "center", color: colores.texto },
  subtitulo: { fontSize: 15, color: colores.textoSecundario, textAlign: "center", marginBottom: 16 },
  etiqueta: { fontSize: 14, fontWeight: "600", color: colores.texto, marginTop: 10 },
  input: {
    borderWidth: 1,
    borderColor: colores.borde,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colores.texto,
    backgroundColor: colores.fondo,
  },
  boton: {
    backgroundColor: colores.primario,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 18,
  },
  botonDeshabilitado: { opacity: 0.5 },
  botonTexto: { color: "#fff", fontSize: 16, fontWeight: "600" },
  error: { color: colores.error, textAlign: "center", marginTop: 8 },
});
