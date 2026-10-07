import { useRouter } from "expo-router";
import { Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { useDatos } from "@/src/datos";
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
  ruta: string;
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
      { titulo: "Trabajar", detalle: "Consola de agente: campañas, pausas y disposiciones", icono: "enLlamada", tono: "ok", permiso: "agente:operar", ruta: "/administrar/agente" },
      { titulo: "Buzón de voz", detalle: "Mensajes que te dejaron cuando no contestaste", icono: "buzon", tono: "marca", permiso: ["llamadas:ver_propias", "llamadas:ver_todas"], modulo: "pbx", ruta: "/administrar/buzon" },
      { titulo: "Mis evaluaciones", detalle: "Lo que el supervisor calificó de tus llamadas", icono: "ok", tono: "ok", permiso: "llamadas:ver_propias", ruta: "/administrar/mis-evaluaciones" },
      { titulo: "Citas", detalle: "Agenda y confirmaciones del voizbot", icono: "calendario", tono: "info", permiso: "citas:gestionar", modulo: "voicebot", ruta: "/administrar/citas" },
      { titulo: "Supervisión", detalle: "Agentes y campañas en vivo; escuchar y susurrar", icono: "ver", tono: "marca", permiso: "supervision:ver", ruta: "/administrar/supervision" },
      { titulo: "Reportes", detalle: "Agentes, campañas, disposiciones y cumplimiento", icono: "metricas", tono: "info", permiso: "reportes:ver", ruta: "/administrar/reportes" },
      { titulo: "Contactos", detalle: "Clientes, su historial, notas y no llamar", icono: "contactos", tono: "marca", permiso: "crm:ver", ruta: "/administrar/contactos" },
      { titulo: "Cobranza", detalle: "Cartera, promesas de pago y resultados", icono: "dinero", tono: "ok", permiso: "campanas:gestionar", modulo: "voicebot", ruta: "/administrar/cobranza" },
    ],
  },
  {
    titulo: "Telefonía",
    entradas: [
      { titulo: "Extensiones", detalle: "Teléfonos, contraseñas SIP y desvíos", icono: "extension", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/extensiones" },
      { titulo: "Proveedor de telefonía", detalle: "La línea por la que entran y salen las llamadas", icono: "troncal", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/troncales" },
      { titulo: "Números entrantes", detalle: "A dónde va la llamada cuando marcan tu número", icono: "entrante", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/rutas-entrantes" },
      { titulo: "Reglas de salida", detalle: "A qué números se llama y por qué proveedor", icono: "saliente", tono: "marca", permiso: "telefonia:gestionar", modulo: "pbx", ruta: "/administrar/rutas-salientes" },
      { titulo: "Grupos de atención", detalle: "Varias personas que atienden las mismas llamadas", icono: "cola", tono: "marca", permiso: "colas:gestionar", modulo: "pbx", ruta: "/administrar/colas" },
    ],
  },
  {
    titulo: "Automatización",
    entradas: [
      { titulo: "Voizbots", detalle: "Prueba tus bots como lo haría un cliente", icono: "bot", tono: "info", permiso: "voizbots:ver", modulo: "voicebot", ruta: "/administrar/bots" },
      { titulo: "Campañas", detalle: "Llamadas masivas, avance y topes del día", icono: "campana", tono: "info", permiso: "campanas:gestionar", modulo: "voicebot", ruta: "/administrar/campanas" },
      { titulo: "Pausas y disposiciones", detalle: "Lo que eligen los agentes al pausar y al colgar", icono: "pausa", tono: "info", permiso: "campanas:gestionar", ruta: "/administrar/pausas-disposiciones" },
      { titulo: "Consumo IA", detalle: "Minutos y costo de los voizbots", icono: "tendencia", tono: "info", permiso: "consumo_ia:ver", modulo: "voicebot", ruta: "/administrar/consumo" },
    ],
  },
  {
    titulo: "Sistema",
    entradas: [
      { titulo: "Usuarios", detalle: "Crear, editar roles y desactivar cuentas", icono: "usuario", tono: "neutro", permiso: "usuarios:gestionar", ruta: "/administrar/usuarios" },
      { titulo: "Roles y permisos", detalle: "Qué puede hacer cada rol", icono: "llave", tono: "neutro", permiso: "usuarios:gestionar", ruta: "/administrar/roles" },
      { titulo: "Seguridad", detalle: "Bloqueos, alertas y auditoría", icono: "seguridad", tono: "neutro", permiso: "ajustes:gestionar", ruta: "/administrar/seguridad" },
      { titulo: "Ajustes", detalle: "Horarios, emergencias y datos de la empresa", icono: "ajustes", tono: "neutro", permiso: "ajustes:gestionar", ruta: "/administrar/ajustes" },
      { titulo: "Empresas", detalle: "Clientes de la plataforma y sus licencias", icono: "servidor", tono: "neutro", permiso: "empresas:gestionar", ruta: "/administrar/empresas" },
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
  // Mensajes de voz sin escuchar, junto a «Buzón de voz».
  const veBuzon = puede("llamadas:ver_propias") || puede("llamadas:ver_todas");
  const { datos: buzon } = useDatos<{ sin_escuchar: number }>(veBuzon ? "/api/buzon/resumen" : null, { ttl: 15_000 });

  const permitido = (x: Entrada) =>
    (x.permiso === null || (Array.isArray(x.permiso) ? x.permiso.some(puede) : puede(x.permiso))) &&
    (!x.modulo || tieneModulo(x.modulo));
  const grupos = GRUPOS.map((g) => ({ ...g, entradas: g.entradas.filter(permitido) })).filter((g) => g.entradas.length);

  const abrir = (x: Entrada) => {
    toque();
    router.push(x.ruta as never);
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
              derecha={
                x.ruta === "/administrar/buzon" && buzon?.sin_escuchar ? (
                  <Pildora texto={`${buzon.sin_escuchar} nuevo${buzon.sin_escuchar === 1 ? "" : "s"}`} tono="marca" />
                ) : undefined
              }
              onPress={() => abrir(x)}
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
