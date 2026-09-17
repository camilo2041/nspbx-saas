import { Redirect, router } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useAuth } from "@/src/auth/AuthContext";

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
      <Text style={styles.titulo}>NSPBX</Text>
      <Text style={styles.subtitulo}>Iniciá sesión con tu extensión</Text>

      <TextInput
        style={styles.input}
        placeholder="URL de tu empresa (ej. miempresa.pbx.midominio.com)"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        value={urlEmpresa}
        onChangeText={setUrlEmpresa}
      />
      <TextInput
        style={styles.input}
        placeholder="Usuario"
        autoCapitalize="none"
        autoCorrect={false}
        value={username}
        onChangeText={setUsername}
      />
      <TextInput
        style={styles.input}
        placeholder="Contraseña"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={[styles.boton, cargando && styles.botonDeshabilitado]}
        onPress={entrar}
        disabled={cargando || !urlEmpresa || !username || !password}
      >
        {cargando ? <ActivityIndicator color="#fff" /> : <Text style={styles.botonTexto}>Entrar</Text>}
      </Pressable>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  contenedor: { flex: 1, backgroundColor: "#fff", padding: 24, justifyContent: "center", gap: 12 },
  titulo: { fontSize: 32, fontWeight: "700", textAlign: "center" },
  subtitulo: { fontSize: 15, color: "#666", textAlign: "center", marginBottom: 12 },
  input: {
    borderWidth: 1,
    borderColor: "#ddd",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
  },
  boton: {
    backgroundColor: "#1c6dd0",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  botonDeshabilitado: { opacity: 0.6 },
  botonTexto: { color: "#fff", fontSize: 16, fontWeight: "600" },
  error: { color: "#c0392b", textAlign: "center" },
});
