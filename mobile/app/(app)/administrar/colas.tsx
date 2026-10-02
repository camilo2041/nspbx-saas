import { useState } from "react";
import { Alert } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, CampoDef, EstadoVacio, Fila, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { Boton, CajaIcono, Pildora } from "@/src/ui";

interface Cola {
  id: number;
  name: string;
  extension: string;
  strategy: string;
  moh_sound: string;
  agents: string[];
  max_wait_time: number;
  max_wait_time_with_no_agent: number;
  agent_ring_timeout: number;
  max_no_answer: number;
  wrap_up_time: number;
  record: boolean;
  failover_extension: string | null;
  announce_position: boolean;
  enabled: boolean;
}

const ESTRATEGIAS = [
  { valor: "ring-all", etiqueta: "Timbrar a todos a la vez" },
  { valor: "round-robin", etiqueta: "Por turnos (round robin)" },
  { valor: "top-down", etiqueta: "En el orden de la lista" },
  { valor: "sequentially-by-agent-order", etiqueta: "Secuencial por orden de agente" },
  { valor: "longest-idle-agent", etiqueta: "El agente con más tiempo libre" },
  { valor: "agent-with-least-talk-time", etiqueta: "El agente con menos tiempo hablado" },
  { valor: "agent-with-fewest-calls", etiqueta: "El agente con menos llamadas" },
  { valor: "random", etiqueta: "Al azar" },
];

export default function Colas() {
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Cola[]>("/api/queues");
  const exts = useDatos<{ number: string; caller_id_name: string | null }[]>("/api/extensions", { ttl: 60_000 });
  const [editando, setEditando] = useState<Cola | "nueva" | null>(null);

  const campos: CampoDef[] = [
    { clave: "name", etiqueta: "Nombre de la cola", placeholder: "soporte", ayuda: "Sin espacios: letras, números, guion o guion bajo." },
    { clave: "extension", etiqueta: "Número para entrar a la cola", tipo: "numero", placeholder: "7000" },
    { clave: "strategy", etiqueta: "Cómo se reparten las llamadas", tipo: "opciones", opciones: ESTRATEGIAS },
    {
      clave: "agents",
      etiqueta: "Agentes",
      tipo: "multiples",
      conOrden: true,
      opciones: (exts.datos ?? []).map((e) => ({ valor: e.number, etiqueta: e.number, detalle: e.caller_id_name ?? undefined })),
      ayuda: "El orden cuenta en las estrategias «en el orden de la lista» y «secuencial».",
    },
    { clave: "agent_ring_timeout", etiqueta: "Segundos que timbra cada agente", tipo: "numero", ayuda: "De 3 a 120." },
    { clave: "max_no_answer", etiqueta: "No-contestas antes de pausar al agente", tipo: "numero", ayuda: "0 = nunca se pausa." },
    { clave: "max_wait_time", etiqueta: "Espera máxima en cola (segundos)", tipo: "numero", ayuda: "0 = sin límite." },
    { clave: "max_wait_time_with_no_agent", etiqueta: "Espera máxima sin agentes (segundos)", tipo: "numero", ayuda: "0 = sin límite." },
    { clave: "wrap_up_time", etiqueta: "Pausa del agente al colgar (segundos)", tipo: "numero" },
    {
      clave: "failover_extension",
      etiqueta: "Desborde (opcional)",
      tipo: "numero",
      placeholder: "1000",
      ayuda: "A dónde va la llamada si se agota la espera o no hay agentes. Vacío = se cuelga.",
    },
    { clave: "record", etiqueta: "Grabar las llamadas de la cola", tipo: "conmutador" },
    { clave: "announce_position", etiqueta: "Decirle a quien espera su posición", tipo: "conmutador" },
    { clave: "enabled", etiqueta: "Activa", tipo: "conmutador" },
  ];

  const guardar = async (v: Record<string, unknown>) => {
    const n = (k: string) => Number(v[k]) || 0;
    const cuerpo = {
      name: String(v.name ?? "").trim(),
      extension: String(v.extension ?? "").trim(),
      strategy: String(v.strategy || "ring-all"),
      agents: String(v.agents ?? "").split(",").filter(Boolean),
      agent_ring_timeout: n("agent_ring_timeout"),
      max_no_answer: n("max_no_answer"),
      max_wait_time: n("max_wait_time"),
      max_wait_time_with_no_agent: n("max_wait_time_with_no_agent"),
      wrap_up_time: n("wrap_up_time"),
      failover_extension: String(v.failover_extension ?? "").trim() || null,
      record: !!v.record,
      announce_position: !!v.announce_position,
      enabled: !!v.enabled,
    };
    if (editando === "nueva") await peticion("/api/queues", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/queues/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/queues");
    setEditando(null);
    recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const q = editando;
    Alert.alert("Eliminar cola", `Las rutas que mandan llamadas a "${q.name}" dejarán de funcionar hasta que las cambies.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/queues/${q.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/queues");
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const q = editando === "nueva" ? null : editando;

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="Nueva cola" icono="agregar" onPress={() => setEditando("nueva")} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio icono="cola" titulo="No hay colas" texto="Crea una para repartir las llamadas entrantes entre varios agentes." />
        ) : null}
        {(datos ?? []).map((x) => (
          <Fila
            key={x.id}
            titulo={`${x.name} · ${x.extension}`}
            subtitulo={`${x.agents.length} agente(s) · ${ESTRATEGIAS.find((e) => e.valor === x.strategy)?.etiqueta ?? x.strategy}`}
            izquierda={<CajaIcono icono="cola" tono="info" />}
            derecha={!x.enabled ? <Pildora texto="Apagada" tono="neutro" /> : x.record ? <Pildora texto="Graba" tono="aviso" icono="grabando" /> : undefined}
            onPress={() => setEditando(x)}
          />
        ))}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva cola" : q?.name ?? ""}
        campos={campos}
        inicial={{
          name: q?.name ?? "",
          extension: q?.extension ?? "",
          strategy: q?.strategy ?? "ring-all",
          agents: (q?.agents ?? []).join(","),
          agent_ring_timeout: q?.agent_ring_timeout ?? 20,
          max_no_answer: q?.max_no_answer ?? 3,
          max_wait_time: q?.max_wait_time ?? 0,
          max_wait_time_with_no_agent: q?.max_wait_time_with_no_agent ?? 0,
          wrap_up_time: q?.wrap_up_time ?? 10,
          failover_extension: q?.failover_extension ?? "",
          record: q?.record ?? false,
          announce_position: q?.announce_position ?? false,
          enabled: q?.enabled ?? true,
        }}
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}
