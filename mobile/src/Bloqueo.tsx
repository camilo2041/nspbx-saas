import { useCallback, useEffect, useRef, useState } from "react";
import { BackHandler, Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { colores } from "@/src/tema";
import { Boton, Logo } from "@/src/ui";

/**
 * Pantalla de bloqueo por huella, encima de toda la app. La sesión ya está
 * restaurada por debajo (para que las llamadas sigan entrando); esto solo
 * decide quién puede VER y usar la pantalla.
 */
export function Bloqueo() {
  const { cargando, bloqueada, usuario, nombreBio, desbloquear, omitirBloqueo, logout } = useAuth();
  const [mensaje, setMensaje] = useState("");
  const [verificando, setVerificando] = useState(false);
  const enCurso = useRef(false);

  const pedir = useCallback(async () => {
    if (enCurso.current) return;
    enCurso.current = true;
    setVerificando(true);
    setMensaje("");
    try {
      const error = await desbloquear();
      if (error) setMensaje(error);
    } finally {
      enCurso.current = false;
      setVerificando(false);
    }
  }, [desbloquear]);

  // Abre el lector apenas aparece el bloqueo, como Nequi y las apps de bancos.
  useEffect(() => {
    if (!cargando && bloqueada) pedir();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cargando, bloqueada]);

  // Mientras está bloqueada, el botón atrás no puede cerrar el bloqueo ni
  // navegar por la app que hay debajo.
  const visible = !cargando && bloqueada;
  useEffect(() => {
    if (!visible) return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => true);
    return () => sub.remove();
  }, [visible]);

  if (!visible) return null;

  const nombre = (usuario?.full_name || nombreBio || "").split(" ")[0];

  return (
    <View style={estilos.pantalla} accessibilityViewIsModal importantForAccessibility="yes">
      <View style={estilos.centro}>
        <Logo tam={64} />
        <Text style={estilos.saludo}>{nombre ? `Hola, ${nombre}` : "Bienvenido"}</Text>
        <Text style={estilos.detalle}>Confirma que eres tú para entrar a NSPBX</Text>

        <Pressable onPress={pedir} style={({ pressed }) => [estilos.huella, pressed && { opacity: 0.8 }]} disabled={verificando}>
          <Text style={{ fontSize: 44 }}>🔒</Text>
        </Pressable>
        <Text style={estilos.ayuda}>{verificando ? "Verificando…" : "Toca para usar tu huella"}</Text>

        {mensaje ? (
          <View style={estilos.error}>
            <Text style={estilos.errorTexto}>{mensaje}</Text>
          </View>
        ) : null}
      </View>

      <View style={estilos.pie}>
        <Boton titulo="Desbloquear" onPress={pedir} cargando={verificando} />
        {usuario ? (
          <Pressable onPress={() => logout()} hitSlop={10}>
            <Text style={estilos.enlace}>Cerrar sesión</Text>
          </Pressable>
        ) : (
          <Pressable onPress={() => omitirBloqueo()} hitSlop={10}>
            <Text style={estilos.enlace}>Usar mi contraseña</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const estilos = StyleSheet.create({
  pantalla: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: colores.fondo, zIndex: 1000, padding: 24, justifyContent: "space-between" },
  centro: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  saludo: { fontSize: 26, fontWeight: "800", color: colores.texto, marginTop: 12 },
  detalle: { fontSize: 14, color: colores.textoSecundario, textAlign: "center" },
  huella: {
    width: 104,
    height: 104,
    borderRadius: 52,
    backgroundColor: colores.marcaSuave,
    borderWidth: 2,
    borderColor: colores.marca,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 28,
  },
  ayuda: { fontSize: 13, color: colores.textoSecundario },
  error: { backgroundColor: colores.peligroSuave, borderRadius: 10, padding: 12, marginTop: 14, maxWidth: 320 },
  errorTexto: { color: colores.peligroTexto, fontSize: 13, textAlign: "center" },
  pie: { gap: 16, alignItems: "stretch", paddingBottom: 12 },
  enlace: { textAlign: "center", color: colores.marcaTexto, fontWeight: "600", fontSize: 14 },
});
