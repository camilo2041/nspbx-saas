import { useMemo, useState } from "react";
import { Alert, Text } from "react-native";

import { peticion } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { invalidar, useDatos } from "@/src/datos";
import {
  Aviso,
  AvisoSinConexion,
  Avatar,
  Buscador,
  CampoDef,
  EstadoVacio,
  FiltroChips,
  Fila,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito } from "@/src/haptico";
import { Boton, Pildora } from "@/src/ui";

interface Usuario {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: string;
  extension_id: number | null;
  extension_number: string | null;
  enabled: boolean;
  last_login_at: string | null;
}

interface Rol {
  value: string;
  label: string;
  description: string;
  requiere_extension: boolean;
}

interface Extension {
  id: number;
  number: string;
  caller_id_name: string | null;
}

function ultimoAcceso(iso: string | null): string {
  if (!iso) return "Nunca ha entrado";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return `Último acceso: ${d.toLocaleDateString("es-CO", { day: "2-digit", month: "short" })}`;
}

export default function Usuarios() {
  const { usuario: yo } = useAuth();
  const u = useDatos<Usuario[]>("/api/users");
  const r = useDatos<Rol[]>("/api/users/roles", { ttl: 5 * 60_000 });
  const e = useDatos<Extension[]>("/api/extensions", { ttl: 60_000 });
  const [q, setQ] = useState("");
  const [filtro, setFiltro] = useState("todos");
  const [editando, setEditando] = useState<Usuario | "nuevo" | null>(null);

  const roles = r.datos ?? [];
  const rolDe = (v: string) => roles.find((x) => x.value === v);
  const usadas = useMemo(() => new Set((u.datos ?? []).map((x) => x.extension_id).filter(Boolean)), [u.datos]);

  const lista = (u.datos ?? []).filter((x) => {
    if (filtro === "activos" && !x.enabled) return false;
    if (filtro === "inactivos" && x.enabled) return false;
    const t = q.trim().toLowerCase();
    return !t || x.full_name.toLowerCase().includes(t) || x.username.includes(t);
  });

  const campos: CampoDef[] = [
    { clave: "full_name", etiqueta: "Nombre completo", placeholder: "Ana Pérez" },
    { clave: "username", etiqueta: "Usuario", placeholder: "ana.perez", ayuda: "Con esto inicia sesión. No se puede cambiar después." },
    { clave: "email", etiqueta: "Correo (opcional)", tipo: "email", placeholder: "ana@empresa.com" },
    {
      clave: "password",
      etiqueta: editando === "nuevo" ? "Contraseña" : "Nueva contraseña (opcional)",
      tipo: "secreto",
      generar: true,
      ayuda: editando === "nuevo" ? "Mínimo 8 caracteres." : "Déjala vacía para no cambiarla. Al cambiarla se cierran sus sesiones abiertas.",
    },
    {
      clave: "role",
      etiqueta: "Rol",
      tipo: "opciones",
      opciones: roles.map((x) => ({ valor: x.value, etiqueta: x.label, detalle: x.description })),
    },
    {
      clave: "extension_id",
      etiqueta: "Extensión",
      tipo: "opciones",
      ayuda: "Este rol necesita una extensión para llamar desde la app.",
      visibleSi: (v) => !!rolDe(String(v.role))?.requiere_extension,
      opciones: [
        ...(e.datos ?? [])
          .filter((x) => !usadas.has(x.id) || (editando && editando !== "nuevo" && editando.extension_id === x.id))
          .map((x) => ({ valor: String(x.id), etiqueta: `${x.number}${x.caller_id_name ? " · " + x.caller_id_name : ""}` })),
      ],
    },
    { clave: "enabled", etiqueta: "Cuenta activa", tipo: "conmutador", ayuda: "Desactivarla cierra sus sesiones y no la borra." },
  ];

  const guardar = async (v: Record<string, unknown>) => {
    const rol = String(v.role || "asesor");
    const cuerpo: Record<string, unknown> = {
      full_name: String(v.full_name ?? "").trim(),
      email: String(v.email ?? "").trim() || null,
      role: rol,
      extension_id: rolDe(rol)?.requiere_extension && v.extension_id ? Number(v.extension_id) : null,
      enabled: !!v.enabled,
    };
    const clave = String(v.password ?? "");
    if (editando === "nuevo") {
      await peticion("/api/users", {
        method: "POST",
        body: { ...cuerpo, username: String(v.username ?? "").trim().toLowerCase(), password: clave },
      });
    } else if (editando) {
      if (clave) cuerpo.password = clave;
      await peticion(`/api/users/${editando.id}`, { method: "PUT", body: cuerpo });
    }
    invalidar("/api/users");
    invalidar("/api/extensions");
    setEditando(null);
    u.recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nuevo") return;
    const x = editando;
    Alert.alert("Eliminar usuario", `Se borrará a ${x.full_name}. Si solo quieres que no entre, mejor desactívala.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/users/${x.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/users");
            setEditando(null);
            u.recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  return (
    <>
      <Pantalla refrescando={u.refrescando} onRefrescar={u.recargar}>
        <Boton titulo="+ Nuevo usuario" onPress={() => setEditando("nuevo")} deshabilitado={!r.datos} />
        <Buscador valor={q} onChange={setQ} placeholder="Buscar por nombre o usuario" />
        <FiltroChips
          valor={filtro}
          onChange={setFiltro}
          opciones={[
            { valor: "todos", etiqueta: "Todos" },
            { valor: "activos", etiqueta: "Activos" },
            { valor: "inactivos", etiqueta: "Desactivados" },
          ]}
        />
        {u.sinConexion ? <AvisoSinConexion /> : null}
        {u.error && !u.datos ? <Aviso texto={u.error} /> : null}
        {u.cargando && !u.datos ? <ListaEsqueleto /> : null}
        {u.datos && lista.length === 0 ? <EstadoVacio icono="👥" titulo="Sin resultados" texto="Prueba con otro nombre o quita el filtro." /> : null}
        {lista.map((x) => (
          <Fila
            key={x.id}
            titulo={`${x.full_name}${x.id === yo?.id ? " (tú)" : ""}`}
            subtitulo={`@${x.username} · ${rolDe(x.role)?.label ?? x.role}${x.extension_number ? " · ext. " + x.extension_number : ""}`}
            izquierda={<Avatar nombre={x.full_name} />}
            derecha={
              x.enabled ? (
                <Text style={{ fontSize: 11, color: "#64748b" }}>{ultimoAcceso(x.last_login_at)}</Text>
              ) : (
                <Pildora texto="Desactivada" tono="neutro" />
              )
            }
            onPress={() => setEditando(x)}
          />
        ))}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nuevo" ? "Nuevo usuario" : editando ? editando.full_name : ""}
        textoGuardar={editando === "nuevo" ? "Crear usuario" : "Guardar cambios"}
        campos={editando === "nuevo" ? campos : campos.filter((c) => c.clave !== "username")}
        inicial={
          editando && editando !== "nuevo"
            ? {
                full_name: editando.full_name,
                username: editando.username,
                email: editando.email ?? "",
                password: "",
                role: editando.role,
                extension_id: editando.extension_id ? String(editando.extension_id) : "",
                enabled: editando.enabled,
              }
            : { full_name: "", username: "", email: "", password: "", role: "asesor", extension_id: "", enabled: true }
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nuevo" && editando.id !== yo?.id ? eliminar : undefined}
      />
    </>
  );
}
