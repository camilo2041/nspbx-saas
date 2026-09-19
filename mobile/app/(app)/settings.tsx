import { router } from "expo-router";
import { useState } from "react";
import { ScrollView, StyleSheet, Switch, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { colores } from "@/src/tema";
import { Boton, Campo, Pildora, Tarjeta } from "@/src/ui";

const ROLES: Record<string, string> = {
  admin: "Administrador",
  supervisor: "Supervisor",
  coordinador: "Coordinador",
  asesor: "Asesor",
};

function Fila({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <View style={estilos.fila}>
      <Text style={estilos.etiqueta}>{etiqueta}</Text>
      <Text style={estilos.valor} numberOfLines={1}>
        {valor}
      </Text>
    </View>
  );
}

export default function CuentaScreen() {
  const { usuario, logout, bioDisponible, bioActiva, activarBiometria, desactivarBiometria } = useAuth();
  const [pidiendoClave, setPidiendoClave] = useState(false);
  const [clave, setClave] = useState("");
  const [errorBio, setErrorBio] = useState("");
  const [guardando, setGuardando] = useState(false);
  const { connState } = useSoftphone();
  const [saliendo, setSaliendo] = useState(false);

  const cambiarHuella = async (activar: boolean) => {
    setErrorBio("");
    if (!activar) {
      await desactivarBiometria();
      return;
    }
    setPidiendoClave(true);
  };

  const confirmarClave = async () => {
    if (!usuario) return;
    setGuardando(true);
    setErrorBio("");
    try {
      await activarBiometria(usuario.username, clave, true);
      setPidiendoClave(false);
      setClave("");
    } catch (e) {
      setErrorBio(e instanceof Error && e.message ? e.message : "No se pudo activar la huella");
    } finally {
      setGuardando(false);
    }
  };

  const salir = async () => {
    setSaliendo(true);
    try {
      await logout();
    } finally {
      router.replace("/login");
    }
  };

  const iniciales = (usuario?.full_name || usuario?.username || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <ScrollView style={{ backgroundColor: colores.fondo }} contentContainerStyle={estilos.contenido}>
      <Tarjeta style={{ alignItems: "center", gap: 8, paddingVertical: 24 }}>
        <View style={estilos.avatar}>
          <Text style={estilos.avatarTexto}>{iniciales}</Text>
        </View>
        <Text style={estilos.nombre}>{usuario?.full_name}</Text>
        <Text style={estilos.usuario}>@{usuario?.username}</Text>
        <Pildora
          texto={connState === "registered" ? "Extensión conectada" : "Extensión sin conexión"}
          tono={connState === "registered" ? "ok" : "peligro"}
        />
      </Tarjeta>

      <Tarjeta style={{ paddingVertical: 4 }}>
        <Fila etiqueta="Rol" valor={ROLES[usuario?.role ?? ""] ?? usuario?.role ?? "—"} />
        <View style={estilos.linea} />
        <Fila etiqueta="Extensión" valor={usuario?.extension_number ?? "Sin asignar"} />
      </Tarjeta>

      <Tarjeta style={{ gap: 12 }}>
        <View style={estilos.filaHuella}>
          <View style={{ flex: 1 }}>
            <Text style={estilos.huellaTitulo}>Acceso con huella</Text>
            <Text style={estilos.huellaDetalle}>
              {bioDisponible
                ? "Guarda tu contraseña protegida por tu huella y entra sin escribirla."
                : "Registra una huella en los ajustes del teléfono para usar esta opción."}
            </Text>
          </View>
          <Switch
            value={bioActiva || pidiendoClave}
            disabled={!bioDisponible}
            onValueChange={cambiarHuella}
            trackColor={{ false: colores.bordeFuerte, true: colores.marca }}
            thumbColor="#fff"
          />
        </View>
        {pidiendoClave ? (
          <View style={{ gap: 10 }}>
            <Campo
              etiqueta="Confirma tu contraseña"
              placeholder="tu contraseña"
              secureTextEntry
              autoCapitalize="none"
              value={clave}
              onChangeText={setClave}
            />
            {errorBio ? <Text style={estilos.errorBio}>{errorBio}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Boton titulo="Cancelar" variante="suave" onPress={() => { setPidiendoClave(false); setClave(""); setErrorBio(""); }} style={{ flex: 1 }} />
              <Boton titulo="Activar" onPress={confirmarClave} cargando={guardando} deshabilitado={!clave} style={{ flex: 1 }} />
            </View>
          </View>
        ) : null}
      </Tarjeta>

      <Boton titulo="Cerrar sesión" variante="peligro" onPress={salir} cargando={saliendo} />
    </ScrollView>
  );
}

const estilos = StyleSheet.create({
  contenido: { padding: 16, gap: 14 },
  avatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: colores.marca, alignItems: "center", justifyContent: "center" },
  avatarTexto: { color: "#fff", fontSize: 26, fontWeight: "800" },
  nombre: { fontSize: 20, fontWeight: "700", color: colores.texto },
  usuario: { fontSize: 14, color: colores.textoSecundario },
  fila: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 14, gap: 12 },
  etiqueta: { fontSize: 14, color: colores.textoSecundario },
  valor: { fontSize: 14, fontWeight: "600", color: colores.texto, flexShrink: 1 },
  linea: { height: 1, backgroundColor: colores.borde },
  filaHuella: { flexDirection: "row", alignItems: "center", gap: 12 },
  huellaTitulo: { fontSize: 15, fontWeight: "700", color: colores.texto },
  huellaDetalle: { fontSize: 12, color: colores.textoSecundario, marginTop: 2 },
  errorBio: { fontSize: 13, color: colores.peligroTexto },
});
