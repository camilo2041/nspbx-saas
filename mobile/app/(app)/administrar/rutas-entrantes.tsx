import { useState } from "react";
import { Alert } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, CampoDef, EstadoVacio, Fila, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { NombreIcono } from "@/src/Icono";
import { Boton, CajaIcono, Pildora, Tono } from "@/src/ui";

type Tipo = "extension" | "queue" | "voicebot" | "hangup";

interface Ruta {
  id: number;
  name: string;
  did_pattern: string;
  destination_type: Tipo;
  destination_value: string | null;
  priority: number;
  enabled: boolean;
}

interface Ext {
  number: string;
  caller_id_name: string | null;
}
interface Cola {
  extension: string;
  name: string;
}
interface Bot {
  id: number;
  name: string;
}

const TIPOS: Record<Tipo, { texto: string; icono: NombreIcono; tono: Tono }> = {
  extension: { texto: "Extensión", icono: "extension", tono: "marca" },
  queue: { texto: "Cola", icono: "cola", tono: "info" },
  voicebot: { texto: "Voizbot", icono: "bot", tono: "ok" },
  hangup: { texto: "Colgar", icono: "colgar", tono: "peligro" },
};

// Un campo de destino por tipo: así cada uno ofrece sus propias opciones.
const CAMPO_DESTINO: Record<Exclude<Tipo, "hangup">, string> = { extension: "dest_ext", queue: "dest_cola", voicebot: "dest_bot" };

export default function RutasEntrantes() {
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Ruta[]>("/api/inbound-routes");
  const exts = useDatos<Ext[]>("/api/extensions", { ttl: 60_000 });
  const colas = useDatos<Cola[]>("/api/queues", { ttl: 60_000 });
  const bots = useDatos<Bot[]>("/api/voicebots", { ttl: 60_000 });
  const [editando, setEditando] = useState<Ruta | "nueva" | null>(null);

  const destino = (r: Ruta) => {
    if (r.destination_type === "hangup") return "Colgar";
    if (r.destination_type === "extension") {
      const e = exts.datos?.find((x) => x.number === r.destination_value);
      return `Ext. ${r.destination_value}${e?.caller_id_name ? ` (${e.caller_id_name})` : ""}`;
    }
    if (r.destination_type === "queue") return `Cola ${colas.datos?.find((q) => q.extension === r.destination_value)?.name ?? r.destination_value}`;
    return `Voizbot ${bots.datos?.find((b) => `bot_${b.id}` === r.destination_value)?.name ?? r.destination_value}`;
  };

  const campos: CampoDef[] = [
    { clave: "name", etiqueta: "Nombre", placeholder: "Línea principal" },
    {
      clave: "did_pattern",
      etiqueta: "Número marcado (DID)",
      placeholder: "6017654321 o any",
      ayuda: "El número al que llaman. «any» captura cualquiera: úsalo de respaldo con la prioridad más alta (número mayor).",
    },
    { clave: "priority", etiqueta: "Prioridad", tipo: "numero", ayuda: "Se revisan de menor a mayor; la primera que coincide gana." },
    {
      clave: "destination_type",
      etiqueta: "A dónde va la llamada",
      tipo: "opciones",
      opciones: (Object.keys(TIPOS) as Tipo[]).map((k) => ({ valor: k, etiqueta: TIPOS[k].texto })),
    },
    {
      clave: "dest_ext",
      etiqueta: "Extensión",
      tipo: "opciones",
      visibleSi: (v) => v.destination_type === "extension",
      opciones: (exts.datos ?? []).map((e) => ({ valor: e.number, etiqueta: e.number, detalle: e.caller_id_name ?? undefined })),
    },
    {
      clave: "dest_cola",
      etiqueta: "Cola",
      tipo: "opciones",
      visibleSi: (v) => v.destination_type === "queue",
      opciones: (colas.datos ?? []).map((q) => ({ valor: q.extension, etiqueta: q.name, detalle: `Extensión ${q.extension}` })),
    },
    {
      clave: "dest_bot",
      etiqueta: "Voizbot",
      tipo: "opciones",
      visibleSi: (v) => v.destination_type === "voicebot",
      opciones: (bots.datos ?? []).map((b) => ({ valor: `bot_${b.id}`, etiqueta: b.name })),
    },
    { clave: "enabled", etiqueta: "Activa", tipo: "conmutador" },
  ];

  const guardar = async (v: Record<string, unknown>) => {
    const tipo = v.destination_type as Tipo;
    const valor = tipo === "hangup" ? null : String(v[CAMPO_DESTINO[tipo]] ?? "") || null;
    if (tipo !== "hangup" && !valor) throw new Error("Elige el destino de la llamada.");
    const cuerpo = {
      name: String(v.name ?? "").trim(),
      did_pattern: String(v.did_pattern ?? "").trim(),
      priority: Number(v.priority) || 0,
      destination_type: tipo,
      destination_value: valor,
      enabled: !!v.enabled,
    };
    if (editando === "nueva") await peticion("/api/inbound-routes", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/inbound-routes/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/inbound-routes");
    setEditando(null);
    recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const r = editando;
    Alert.alert("Eliminar ruta", `Las llamadas a ${r.did_pattern} dejarán de entrar por "${r.name}".`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/inbound-routes/${r.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/inbound-routes");
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const inicial = (r: Ruta | null): Record<string, unknown> => ({
    name: r?.name ?? "",
    did_pattern: r?.did_pattern ?? "any",
    priority: r?.priority ?? 10,
    destination_type: r?.destination_type ?? "extension",
    dest_ext: r?.destination_type === "extension" ? r.destination_value : "",
    dest_cola: r?.destination_type === "queue" ? r.destination_value : "",
    dest_bot: r?.destination_type === "voicebot" ? r.destination_value : "",
    enabled: r?.enabled ?? true,
  });

  const lista = [...(datos ?? [])].sort((a, b) => a.priority - b.priority);

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="Nueva ruta entrante" icono="agregar" onPress={() => setEditando("nueva")} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio
            icono="entrante"
            titulo="No hay rutas entrantes"
            texto="Sin rutas, toda llamada que entra se cuelga. Crea al menos una; con «any» capturas cualquier número."
          />
        ) : null}
        {lista.map((r) => {
          const t = TIPOS[r.destination_type] ?? TIPOS.hangup;
          return (
            <Fila
              key={r.id}
              titulo={r.name}
              subtitulo={`${r.did_pattern === "any" ? "Cualquier número" : r.did_pattern} → ${destino(r)} · prioridad ${r.priority}`}
              izquierda={<CajaIcono icono={t.icono} tono={t.tono} />}
              derecha={r.enabled ? undefined : <Pildora texto="Apagada" tono="neutro" />}
              onPress={() => setEditando(r)}
            />
          );
        })}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva ruta entrante" : editando ? editando.name : ""}
        campos={campos}
        inicial={inicial(editando === "nueva" ? null : editando)}
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}
