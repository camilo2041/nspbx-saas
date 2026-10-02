import { Redirect, router } from "expo-router";
import { useEffect, useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, Switch, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { ultimoUsuario } from "@/src/seguridad/biometria";
import { Icono } from "@/src/Icono";
import { crearEstilos, useColores } from "@/src/tema";
import { Boton, Campo, Logo, Tarjeta } from "@/src/ui";

function mensajeAmigable(e: unknown): string {
  const texto = e instanceof Error ? e.message : "";
  if (/network request failed|failed to fetch/i.test(texto)) {
    return "No se pudo conectar con NSPBX. Revisa tu conexión a Internet e inténtalo de nuevo.";
  }
  return texto || "No se pudo iniciar sesión";
}

export default function LoginScreen() {
  const estilos = useEstilos();
  const c = useColores();
  const { usuario, login, bioDisponible, bioActiva, activarBiometria, avisoAcceso, limpiarAvisoAcceso } = useAuth();
  const [recordar, setRecordar] = useState(true);
  const [aviso, setAviso] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    ultimoUsuario().then((u) => u && setUsername((actual) => actual || u));
  }, []);

  if (usuario) return <Redirect href="/(app)" />;

  const listo = username.trim() && password;

  const entrar = async () => {
    setError("");
    limpiarAvisoAcceso();
    setCargando(true);
    try {
      await login(username.trim(), password);
      // Guardar la contraseña con huella: si el sistema lo rechaza (por ejemplo
      // no se confirmó la huella) no se bloquea el ingreso, solo se avisa.
      if (recordar && bioDisponible && !bioActiva) {
        try {
          await activarBiometria(username.trim(), password);
        } catch {
          setAviso("No se activó la huella. Puedes hacerlo luego en Menú → Mi cuenta.");
        }
      }
      router.replace("/(app)");
    } catch (e) {
      setError(mensajeAmigable(e));
    } finally {
      setCargando(false);
    }
  };

  return (
    <KeyboardAvoidingView style={estilos.contenedor} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={estilos.contenido} keyboardShouldPersistTaps="handled">
        <View style={estilos.cabecera}>
          <Logo tam={64} />
          <Text style={estilos.titulo}>NSPBX</Text>
          <Text style={estilos.subtitulo}>Central telefónica</Text>
        </View>

        <Tarjeta style={{ gap: 16, padding: 20 }}>
          <Campo
            etiqueta="Usuario"
            icono="usuario"
            placeholder="tu usuario"
            autoCapitalize="none"
            autoCorrect={false}
            value={username}
            onChangeText={setUsername}
          />
          <Campo
            etiqueta="Contraseña"
            icono="candado"
            placeholder="tu contraseña"
            secureTextEntry
            autoCapitalize="none"
            value={password}
            onChangeText={setPassword}
            onSubmitEditing={listo ? entrar : undefined}
          />

          {bioDisponible && !bioActiva ? (
            <View style={estilos.recordar}>
              <Icono nombre="huella" tam={22} color={c.marca} />
              <View style={{ flex: 1 }}>
                <Text style={estilos.recordarTitulo}>Recordar con huella</Text>
                <Text style={estilos.recordarDetalle}>Entra la próxima vez sin escribir tu contraseña</Text>
              </View>
              <Switch
                value={recordar}
                onValueChange={setRecordar}
                trackColor={{ false: c.bordeFuerte, true: c.marca }}
                thumbColor="#fff"
              />
            </View>
          ) : null}

          {avisoAcceso ? <Text style={estilos.aviso}>{avisoAcceso}</Text> : null}
          {aviso ? <Text style={estilos.aviso}>{aviso}</Text> : null}

          {error ? (
            <View style={estilos.error}>
              <Icono nombre="alerta" tam={18} color={c.peligroTexto} />
              <Text style={estilos.errorTexto}>{error}</Text>
            </View>
          ) : null}

          <Boton titulo="Entrar" onPress={entrar} cargando={cargando} deshabilitado={!listo} />
        </Tarjeta>

        <Text style={estilos.pie}>Usa el mismo usuario y contraseña del panel web.</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const useEstilos = crearEstilos((c) => ({
  contenedor: { flex: 1, backgroundColor: c.fondo },
  contenido: { flexGrow: 1, padding: 20, justifyContent: "center", gap: 24 },
  cabecera: { alignItems: "center", gap: 6 },
  titulo: { fontSize: 24, fontWeight: "700", color: c.texto, marginTop: 10, letterSpacing: -0.3 },
  subtitulo: { fontSize: 14, color: c.textoSecundario },
  error: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: c.peligroSuave,
    borderWidth: 1,
    borderColor: c.peligro,
    borderRadius: 10,
    padding: 12,
  },
  errorTexto: { flex: 1, color: c.peligroTexto, fontSize: 13, lineHeight: 18 },
  recordar: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.superficie2, borderRadius: 12, padding: 12 },
  recordarTitulo: { fontSize: 14, fontWeight: "600", color: c.texto },
  recordarDetalle: { fontSize: 12, color: c.textoSecundario },
  aviso: { fontSize: 12, color: c.avisoTexto },
  pie: { textAlign: "center", fontSize: 12, color: c.placeholder },
}));
