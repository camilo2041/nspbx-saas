import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { EstadoVacio, Pantalla } from "@/src/gestion";
import { toque } from "@/src/haptico";
import { colores, radios, sombra } from "@/src/tema";

interface Modulo {
  ruta: string;
  icono: string;
  titulo: string;
  detalle: string;
  permiso: string;
}

const MODULOS: Modulo[] = [
  { ruta: "/administrar/troncales", icono: "🔌", titulo: "Troncales", detalle: "Conexión con tu proveedor: estado, prueba y edición", permiso: "telefonia:gestionar" },
  { ruta: "/administrar/extensiones", icono: "☎️", titulo: "Extensiones", detalle: "Teléfonos y contraseñas SIP", permiso: "telefonia:gestionar" },
  { ruta: "/administrar/usuarios", icono: "👥", titulo: "Usuarios", detalle: "Crear, editar roles y desactivar cuentas", permiso: "usuarios:gestionar" },
  { ruta: "/administrar/bots", icono: "🤖", titulo: "Voizbots", detalle: "Prueba tus bots como lo haría un cliente", permiso: "voizbots:ver" },
];

export default function AdministrarHub() {
  const router = useRouter();
  const { puede } = useAuth();
  const visibles = MODULOS.filter((m) => puede(m.permiso));

  return (
    <Pantalla>
      {visibles.length === 0 ? (
        <EstadoVacio icono="🔒" titulo="Nada para administrar" texto="Tu rol no incluye estas secciones. Pídele a un administrador que revise tus permisos." />
      ) : (
        visibles.map((m) => (
          <Pressable
            key={m.ruta}
            onPress={() => {
              toque();
              router.push(m.ruta as never);
            }}
            style={({ pressed }) => [
              {
                flexDirection: "row",
                alignItems: "center",
                gap: 14,
                backgroundColor: colores.superficie,
                borderRadius: radios.grande,
                borderWidth: 1,
                borderColor: colores.borde,
                padding: 16,
                ...sombra,
              },
              pressed && { transform: [{ scale: 0.985 }] },
            ]}
          >
            <View style={{ width: 48, height: 48, borderRadius: 14, backgroundColor: colores.marcaSuave, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ fontSize: 24 }}>{m.icono}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 16, fontWeight: "700", color: colores.texto }}>{m.titulo}</Text>
              <Text style={{ fontSize: 12.5, color: colores.textoSecundario, marginTop: 2, lineHeight: 17 }}>{m.detalle}</Text>
            </View>
            <Text style={{ fontSize: 20, color: colores.placeholder }}>›</Text>
          </Pressable>
        ))
      )}
    </Pantalla>
  );
}
