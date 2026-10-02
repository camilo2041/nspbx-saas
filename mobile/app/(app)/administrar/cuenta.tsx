import { router } from "expo-router";
import { useState } from "react";
import { Pressable, Switch, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { Avatar, Pantalla } from "@/src/gestion";
import { toque } from "@/src/haptico";
import { Icono, NombreIcono } from "@/src/Icono";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { crearEstilos, Preferencia, radios, useTema } from "@/src/tema";
import { Boton, Campo, FilaMenu, Pildora, Seccion, Tarjeta } from "@/src/ui";

const ROLES: Record<string, string> = {
  admin: "Administrador",
  supervisor: "Supervisor",
  coordinador: "Coordinador",
  asesor: "Asesor",
  plataforma: "Plataforma",
};

const APARIENCIAS: { valor: Preferencia; etiqueta: string; icono: NombreIcono }[] = [
  { valor: "sistema", etiqueta: "Sistema", icono: "tema" },
  { valor: "claro", etiqueta: "Claro", icono: "claro" },
  { valor: "oscuro", etiqueta: "Oscuro", icono: "oscuro" },
];

function SelectorApariencia() {
  const { c, preferencia, setPreferencia } = useTema();
  const e = useEstilos();
  return (
    <View style={e.segmentos} accessibilityRole="radiogroup">
      {APARIENCIAS.map((a) => {
        const activo = a.valor === preferencia;
        return (
          <Pressable
            key={a.valor}
            accessibilityRole="radio"
            accessibilityState={{ checked: activo }}
            onPress={() => {
              toque();
              setPreferencia(a.valor);
            }}
            style={[e.segmento, activo && e.segmentoActivo]}
          >
            <Icono nombre={a.icono} tam={18} color={activo ? c.marcaTexto : c.textoSecundario} />
            <Text style={[e.segmentoTexto, activo && { color: c.texto }]}>{a.etiqueta}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function CuentaScreen() {
  const { c } = useTema();
  const e = useEstilos();
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
    } catch (err) {
      setErrorBio(err instanceof Error && err.message ? err.message : "No se pudo activar la huella");
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

  const conectada = connState === "registered";

  return (
    <Pantalla>
      <Tarjeta style={e.perfil}>
        <Avatar nombre={usuario?.full_name || usuario?.username || "?"} tam={72} />
        <Text style={e.nombre}>{usuario?.full_name}</Text>
        <Text style={e.usuario}>@{usuario?.username}</Text>
        <Pildora texto={conectada ? "Extensión conectada" : "Extensión sin conexión"} tono={conectada ? "ok" : "peligro"} />
      </Tarjeta>

      <Seccion titulo="Datos">
        <FilaMenu titulo="Rol" icono="llave" valor={ROLES[usuario?.role ?? ""] ?? usuario?.role ?? "—"} />
        <FilaMenu titulo="Extensión" icono="extension" valor={usuario?.extension_number ?? "Sin asignar"} ultima />
      </Seccion>

      <Seccion titulo="Apariencia">
        <View style={{ padding: 12 }}>
          <SelectorApariencia />
        </View>
      </Seccion>

      <Seccion titulo="Seguridad">
        <FilaMenu
          titulo="Acceso con huella"
          icono="huella"
          detalle={
            bioDisponible
              ? "Guarda tu contraseña protegida por tu huella y entra sin escribirla."
              : "Registra una huella en los ajustes del teléfono para usar esta opción."
          }
          derecha={
            <Switch
              value={bioActiva || pidiendoClave}
              disabled={!bioDisponible}
              onValueChange={cambiarHuella}
              trackColor={{ false: c.bordeFuerte, true: c.marca }}
              thumbColor="#fff"
            />
          }
          ultima={!pidiendoClave}
        />
        {pidiendoClave ? (
          <View style={{ gap: 10, padding: 14 }}>
            <Campo
              etiqueta="Confirma tu contraseña"
              placeholder="tu contraseña"
              secureTextEntry
              autoCapitalize="none"
              value={clave}
              onChangeText={setClave}
              error={errorBio || undefined}
            />
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Boton
                titulo="Cancelar"
                variante="suave"
                onPress={() => {
                  setPidiendoClave(false);
                  setClave("");
                  setErrorBio("");
                }}
                style={{ flex: 1 }}
              />
              <Boton titulo="Activar" onPress={confirmarClave} cargando={guardando} deshabilitado={!clave} style={{ flex: 1 }} />
            </View>
          </View>
        ) : null}
      </Seccion>

      <Seccion titulo="Ayuda">
        <FilaMenu
          titulo="Diagnóstico de llamadas entrantes"
          detalle="Notificaciones, permisos y conexión de la extensión"
          icono="diagnostico"
          onPress={() => router.push("/diagnostico")}
          ultima
        />
      </Seccion>

      <Boton titulo="Cerrar sesión" icono="salir" variante="contorno" onPress={salir} cargando={saliendo} style={{ marginTop: 4 }} />
    </Pantalla>
  );
}

const useEstilos = crearEstilos((c) => ({
  perfil: { alignItems: "center", gap: 6, paddingVertical: 24 },
  nombre: { fontSize: 20, fontWeight: "700", color: c.texto, marginTop: 6 },
  usuario: { fontSize: 14, color: c.textoSecundario, marginBottom: 4 },
  segmentos: { flexDirection: "row", backgroundColor: c.superficie3, borderRadius: radios.medio, padding: 4, gap: 4 },
  segmento: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 9,
    borderRadius: radios.chico,
  },
  segmentoActivo: { backgroundColor: c.superficie, borderWidth: 1, borderColor: c.borde },
  segmentoTexto: { fontSize: 13.5, fontWeight: "600", color: c.textoSecundario },
}));
