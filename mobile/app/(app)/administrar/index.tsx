import { useRouter } from "expo-router";
import { Alert, Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { Avatar, Pantalla } from "@/src/gestion";
import { toque } from "@/src/haptico";
import { NombreIcono } from "@/src/Icono";
import { crearEstilos } from "@/src/tema";
import { FilaMenu, Pildora, Seccion, Tarjeta, Tono } from "@/src/ui";

interface Entrada {
  titulo: string;
  detalle: string;
  icono: NombreIcono;
  tono: Tono;
  /** null = cualquiera con sesión. */
  permiso: string | string[] | null;
  /** Paquete que tiene que tener la empresa (igual que el panel). */
  modulo?: "pbx" | "voicebot";
  /** Sin ruta: está en el panel web y llega a la app en una próxima versión. */
  ruta?: string;
}

/**
 * Las mismas secciones y en el mismo orden que la barra lateral del panel
 * web (frontend/components/layout.tsx), para que quien usa los dos no tenga
 * que aprender dos organizaciones.
 */
const GRUPOS: { titulo: string; entradas: Entrada[] }[] = [
  {
    titulo: "Operación",
    entradas: [
      { titulo: "Citas", detalle: "Agenda y confirmaciones del voizbot", icono: "calendario", tono: "info", permiso: "citas:gestionar", modulo: "voicebot", ruta: "/administrar/citas" },
      { titulo: "Cobranza", detalle: "Cartera, promesas de pago y resultados", icono: "dinero", tono: "ok", permiso: "campanas:gestionar", modulo: "voicebot", ruta: "/administrar/cobranza" },
    ],
  },
  {
    titulo: "Telefonía",
    entradas: [
      { titulo: "Extensiones", detalle: "Teléfonos, contraseñas SIP y desvíos", icono: "extension", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/extensiones" },
      { titulo: "Troncales", detalle: "Conexión con tu proveedor: estado y prueba", icono: "troncal", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/troncales" },
      { titulo: "Rutas entrantes", detalle: "A dónde va cada número que te llaman", icono: "entrante", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx" },
      { titulo: "Rutas salientes", detalle: "Por qué troncal sale cada llamada", icono: "saliente", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx" },
      { titulo: "Colas", detalle: "Grupos de atención y sus agentes", icono: "usuarios", tono: "marca", permiso: "colas:gestionar", modulo: "pbx" },
    ],
  },
  {
    titulo: "Automatización",
    entradas: [
      { titulo: "Voizbots", detalle: "Prueba tus bots como lo haría un cliente", icono: "bot", tono: "info", permiso: "voizbots:ver", modulo: "voicebot", ruta: "/administrar/bots" },
      { titulo: "Campañas", detalle: "Llamadas masivas, avance y topes del día", icono: "campana", tono: "info", permiso: "campanas:gestionar", modulo: "voicebot", ruta: "/administrar/campanas" },
      { titulo: "Consumo IA", detalle: "Minutos y costo de los voizbots", icono: "tendencia", tono: "info", permiso: "consumo_ia:ver", modulo: "voicebot" },
    ],
  },
  {
    titulo: "Sistema",
    entradas: [
      { titulo: "Usuarios", detalle: "Crear, editar roles y desactivar cuentas", icono: "usuario", tono: "neutro", permiso: "usuarios:gestionar", ruta: "/administrar/usuarios" },
      { titulo: "Roles y permisos", detalle: "Qué puede hacer cada rol", icono: "llave", tono: "neutro", permiso: "usuarios:gestionar" },
      { titulo: "Seguridad", detalle: "Bloqueos, alertas y auditoría", icono: "seguridad", tono: "neutro", permiso: "ajustes:gestionar" },
      { titulo: "Ajustes", detalle: "Horarios, emergencias y datos de la empresa", icono: "ajustes", tono: "neutro", permiso: "ajustes:gestionar" },
      { titulo: "Empresas", detalle: "Clientes de la plataforma y sus licencias", icono: "servidor", tono: "neutro", permiso: "empresas:gestionar" },
    ],
  },
];

const ROLES: Record<string, string> = {
  admin: "Administrador",
  supervisor: "Supervisor",
  coordinador: "Coordinador",
  asesor: "Asesor",
  plataforma: "Plataforma",
};

export default function Menu() {
  const router = useRouter();
  const e = useEstilos();
  const { usuario, puede, tieneModulo } = useAuth();

  const permitido = (x: Entrada) =>
    (x.permiso === null || (Array.isArray(x.permiso) ? x.permiso.some(puede) : puede(x.permiso))) &&
    (!x.modulo || tieneModulo(x.modulo));
  const grupos = GRUPOS.map((g) => ({ ...g, entradas: g.entradas.filter(permitido) })).filter((g) => g.entradas.length);

  const abrir = (x: Entrada) => {
    toque();
    if (x.ruta) router.push(x.ruta as never);
    else Alert.alert(x.titulo, "Esta sección llega pronto a la app. Mientras tanto la tienes en el panel web.");
  };

  return (
    <Pantalla>
      <Tarjeta onPress={() => router.push("/administrar/cuenta")} style={e.perfil}>
        <Avatar nombre={usuario?.full_name || usuario?.username || "?"} tam={52} />
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={e.nombre} numberOfLines={1}>
            {usuario?.full_name || usuario?.username}
          </Text>
          <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
            <Pildora texto={ROLES[usuario?.role ?? ""] ?? usuario?.role ?? ""} tono="marca" />
            {usuario?.extension_number ? <Pildora texto={`Ext. ${usuario.extension_number}`} tono="neutro" icono="extension" /> : null}
          </View>
        </View>
      </Tarjeta>

      {grupos.map((g) => (
        <Seccion key={g.titulo} titulo={g.titulo}>
          {g.entradas.map((x, i) => (
            <FilaMenu
              key={x.titulo}
              titulo={x.titulo}
              detalle={x.detalle}
              icono={x.icono}
              tono={x.tono}
              onPress={() => abrir(x)}
              derecha={x.ruta ? undefined : <Pildora texto="Pronto" tono="neutro" />}
              ultima={i === g.entradas.length - 1}
            />
          ))}
        </Seccion>
      ))}

      <Seccion titulo="Cuenta">
        <FilaMenu titulo="Mi cuenta" detalle="Contraseña, huella, apariencia y notificaciones" icono="cuenta" onPress={() => router.push("/administrar/cuenta")} />
        <FilaMenu
          titulo="Diagnóstico de llamadas"
          detalle="Revisa por qué no te entran las llamadas"
          icono="diagnostico"
          onPress={() => router.push("/diagnostico")}
          ultima
        />
      </Seccion>
    </Pantalla>
  );
}

const useEstilos = crearEstilos((c) => ({
  perfil: { flexDirection: "row", alignItems: "center", gap: 14 },
  nombre: { fontSize: 18, fontWeight: "700", color: c.texto },
}));
