import { useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import {
  AvisoSinConexion,
  Aviso,
  Buscador,
  CampoDef,
  EstadoVacio,
  Fila,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito } from "@/src/haptico";
import { colores } from "@/src/tema";
import { Boton, Pildora } from "@/src/ui";

interface Extension {
  id: number;
  number: string;
  password: string;
  caller_id_name: string | null;
  voicemail: boolean;
  enabled: boolean;
}

const CAMPOS: CampoDef[] = [
  { clave: "number", etiqueta: "Número de extensión", tipo: "numero", placeholder: "1005", ayuda: "Solo dígitos. Es lo que marcan los demás para llamarla." },
  { clave: "caller_id_name", etiqueta: "Nombre a mostrar", placeholder: "Ana Pérez", ayuda: "Lo que ve quien recibe la llamada." },
  { clave: "password", etiqueta: "Contraseña SIP", tipo: "secreto", generar: true, ayuda: "La usa el teléfono para registrarse. Usa una larga: es lo que protege la línea del fraude." },
  { clave: "voicemail", etiqueta: "Buzón de voz", tipo: "conmutador" },
  { clave: "enabled", etiqueta: "Activa", tipo: "conmutador" },
];

export default function Extensiones() {
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Extension[]>("/api/extensions");
  const [q, setQ] = useState("");
  const [editando, setEditando] = useState<Extension | "nueva" | null>(null);

  const lista = (datos ?? []).filter((e) => {
    const t = q.trim().toLowerCase();
    return !t || e.number.includes(t) || (e.caller_id_name ?? "").toLowerCase().includes(t);
  });

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo = {
      number: String(v.number ?? "").trim(),
      password: String(v.password ?? ""),
      caller_id_name: String(v.caller_id_name ?? "").trim() || null,
      voicemail: !!v.voicemail,
      enabled: !!v.enabled,
    };
    if (editando === "nueva") await peticion("/api/extensions", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/extensions/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/extensions");
    setEditando(null);
    recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const e = editando;
    Alert.alert("Eliminar extensión", `Se borrará la extensión ${e.number}. Su teléfono dejará de registrarse.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/extensions/${e.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/extensions");
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="+ Nueva extensión" onPress={() => setEditando("nueva")} />
        <Buscador valor={q} onChange={setQ} placeholder="Buscar por número o nombre" />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto /> : null}
        {datos && lista.length === 0 ? (
          <EstadoVacio icono="☎️" titulo={q ? "Sin resultados" : "Aún no hay extensiones"} texto={q ? undefined : "Crea la primera con el botón de arriba."} />
        ) : null}
        {lista.map((e) => (
          <Fila
            key={e.id}
            titulo={`${e.number}${e.caller_id_name ? " · " + e.caller_id_name : ""}`}
            subtitulo={e.voicemail ? "Con buzón de voz" : "Sin buzón de voz"}
            izquierda={
              <View style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: colores.infoSuave, alignItems: "center", justifyContent: "center" }}>
                <Text style={{ fontWeight: "800", color: colores.infoTexto, fontSize: 12 }}>{e.number.slice(-4)}</Text>
              </View>
            }
            derecha={<Pildora texto={e.enabled ? "Activa" : "Apagada"} tono={e.enabled ? "ok" : "neutro"} />}
            onPress={() => setEditando(e)}
          />
        ))}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva extensión" : `Extensión ${editando ? editando.number : ""}`}
        campos={CAMPOS}
        inicial={
          editando && editando !== "nueva"
            ? { ...editando }
            : { number: "", caller_id_name: "", password: "", voicemail: true, enabled: true }
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}
