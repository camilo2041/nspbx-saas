/**
 * Sesiones abiertas de la propia cuenta (backend /api/auth/sesiones): un
 * equipo por fila. Cerrar uno sirve para un teléfono perdido; «Cerrar
 * todas» saca también a este equipo (y al panel web).
 */
import { useState } from "react";
import { Alert, View } from "react-native";

import { peticion } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { useDatos } from "@/src/datos";
import { Aviso } from "@/src/gestion";
import { exito } from "@/src/haptico";
import type { NombreIcono } from "@/src/Icono";
import { Boton, FilaMenu, Seccion } from "@/src/ui";

interface SesionAbierta {
  id: number;
  plataforma: string | null;
  dispositivo: string | null;
  ultima_actividad: string;
}

const ICONO: Record<string, NombreIcono> = { android: "telefono", ios: "telefono", web: "mundo" };

export function SesionesAbiertas() {
  const { logout } = useAuth();
  const { datos, error, recargar } = useDatos<SesionAbierta[]>("/api/auth/sesiones", { ttl: 10_000 });
  const [cerrando, setCerrando] = useState(false);

  const cerrarUna = (s: SesionAbierta) =>
    Alert.alert("Cerrar sesión de este equipo", `${s.dispositivo || "El equipo"} tendrá que volver a entrar.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Cerrar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/auth/sesiones/${s.id}`, { method: "DELETE" });
            exito();
            recargar();
          } catch (err) {
            Alert.alert("No se pudo cerrar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const cerrarTodas = () =>
    Alert.alert(
      "Cerrar todas las sesiones",
      "Se cierran en todos tus equipos, también en este y en el panel web. Úsalo si crees que alguien más entró a tu cuenta (y cambia tu contraseña).",
      [
        { text: "Cancelar", style: "cancel" },
        {
          text: "Cerrar todas",
          style: "destructive",
          onPress: async () => {
            setCerrando(true);
            try {
              await peticion("/api/auth/sesiones/cerrar-todas", { method: "POST" });
            } catch {
              // aunque falle, este equipo sale igual
            }
            await logout();
          },
        },
      ]
    );

  const lista = datos ?? [];
  const hace = (iso: string) =>
    new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  return (
    <Seccion titulo="Sesiones abiertas">
      {error && !datos ? (
        <View style={{ padding: 14 }}>
          <Aviso texto={error} />
        </View>
      ) : null}
      {lista.map((s) => (
        <FilaMenu
          key={s.id}
          titulo={s.dispositivo || "Equipo sin nombre"}
          detalle={`Última actividad: ${hace(s.ultima_actividad)}`}
          icono={ICONO[s.plataforma ?? ""] ?? "telefono"}
          onPress={() => cerrarUna(s)}
        />
      ))}
      {datos && lista.length === 0 ? <FilaMenu titulo="Ningún equipo con la app abierta" icono="info" /> : null}
      <View style={{ padding: 14 }}>
        <Boton titulo="Cerrar todas las sesiones" icono="salir" variante="contorno" cargando={cerrando} onPress={cerrarTodas} />
      </View>
    </Seccion>
  );
}
