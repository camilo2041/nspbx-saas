import { useEffect, useMemo, useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { aTextoLocal, deTextoLocal, fechaLarga, horaCorta, SelectorFecha } from "@/src/fecha";
import {
  Aviso,
  AvisoSinConexion,
  Buscador,
  CampoDef,
  EstadoVacio,
  Fila,
  FiltroChips,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito } from "@/src/haptico";
import { NombreIcono } from "@/src/Icono";
import { useLlamar } from "@/src/llamar";
import { useColores } from "@/src/tema";
import { Boton, BotonIcono, CajaIcono, Pildora, Segmentado, Tono } from "@/src/ui";

interface Cita {
  id: number;
  patient_name: string;
  phone: string;
  appointment_date: string;
  duration_minutes: number;
  status: "confirmed" | "cancelled" | "completed";
  notes: string | null;
}

interface Gestion {
  id: number;
  phone: string | null;
  action: "confirmada" | "cancelada" | "reagendada" | "agendada";
  patient_name: string | null;
  appointment_date: string | null;
  called_at: string;
}

const ESTADOS: Record<Cita["status"], { texto: string; tono: Tono }> = {
  confirmed: { texto: "Confirmada", tono: "ok" },
  cancelled: { texto: "Cancelada", tono: "peligro" },
  completed: { texto: "Completada", tono: "info" },
};

const ACCIONES: Record<Gestion["action"], { texto: string; tono: Tono; icono: NombreIcono }> = {
  confirmada: { texto: "Confirmó", tono: "ok", icono: "ok" },
  cancelada: { texto: "Canceló", tono: "peligro", icono: "error" },
  reagendada: { texto: "Reagendó", tono: "aviso", icono: "calendario" },
  agendada: { texto: "Agendó", tono: "info", icono: "agregar" },
};

const CAMPOS: CampoDef[] = [
  { clave: "patient_name", etiqueta: "Paciente", placeholder: "Nombre y apellido" },
  { clave: "phone", etiqueta: "Teléfono", tipo: "telefono", placeholder: "3011234567" },
  { clave: "appointment_date", etiqueta: "Fecha y hora", tipo: "fechaHora" },
  { clave: "duration_minutes", etiqueta: "Duración (minutos)", tipo: "numero" },
  {
    clave: "status",
    etiqueta: "Estado",
    tipo: "opciones",
    opciones: [
      { valor: "confirmed", etiqueta: "Confirmada" },
      { valor: "cancelled", etiqueta: "Cancelada" },
      { valor: "completed", etiqueta: "Completada" },
    ],
  },
  { clave: "notes", etiqueta: "Notas", tipo: "multilinea", placeholder: "Opcional" },
];

const POR_PAGINA = 50;

function GestionBot() {
  const c = useColores();
  const llamar = useLlamar();
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Gestion[]>("/api/appointments/gestion?days=30", {
    ttl: 30_000,
  });
  return (
    <Pantalla refrescando={refrescando} onRefrescar={recargar}>
      <Text style={{ fontSize: 13, color: c.textoSecundario, lineHeight: 18 }}>
        Lo que hizo el voizbot por teléfono en los últimos 30 días: cada confirmación, cancelación o cambio de cita.
      </Text>
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
      {datos && datos.length === 0 ? (
        <EstadoVacio
          icono="bot"
          titulo="Todavía no hay gestiones"
          texto="Aparecen cuando el voizbot confirma, cancela o reagenda una cita, por una llamada entrante o una campaña."
        />
      ) : null}
      {(datos ?? []).map((g) => {
        const a = ACCIONES[g.action] ?? { texto: g.action, tono: "neutro" as const, icono: "info" as const };
        return (
          <Fila
            key={g.id}
            titulo={g.patient_name || g.phone || "Sin nombre"}
            subtitulo={`${a.texto}${g.appointment_date ? " · cita " + fechaLarga(g.appointment_date) : ""} · llamó ${fechaLarga(g.called_at)}`}
            izquierda={<CajaIcono icono={a.icono} tono={a.tono} />}
            derecha={g.phone ? <BotonIcono icono="telefono" etiqueta={`Llamar a ${g.phone}`} tono="ok" tam={38} onPress={() => llamar(g.phone)} /> : null}
          />
        );
      })}
    </Pantalla>
  );
}

function Agenda() {
  const c = useColores();
  const llamar = useLlamar();
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [estado, setEstado] = useState<"" | Cita["status"]>("");
  const [dia, setDia] = useState("");
  const [limite, setLimite] = useState(POR_PAGINA);
  const [editando, setEditando] = useState<Cita | "nueva" | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const qs = new URLSearchParams({ limit: String(limite) });
  if (busqueda) qs.set("search", busqueda);
  if (estado) qs.set("estado", estado);
  if (dia) qs.set("day", dia);
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Cita[]>(`/api/appointments?${qs}`, { ttl: 15_000 });

  // Agrupadas por día, como una agenda.
  const grupos = useMemo(() => {
    const salida: { dia: string; citas: Cita[] }[] = [];
    for (const cita of datos ?? []) {
      const d = cita.appointment_date.slice(0, 10);
      if (salida.at(-1)?.dia !== d) salida.push({ dia: d, citas: [] });
      salida.at(-1)!.citas.push(cita);
    }
    return salida;
  }, [datos]);

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo = {
      patient_name: String(v.patient_name ?? "").trim(),
      phone: String(v.phone ?? "").trim(),
      appointment_date: String(v.appointment_date ?? ""),
      duration_minutes: Number(v.duration_minutes) || 30,
      status: String(v.status ?? "confirmed"),
      notes: String(v.notes ?? "").trim() || null,
    };
    if (!cuerpo.patient_name || !cuerpo.phone) throw new Error("Escribe el nombre y el teléfono del paciente.");
    if (!cuerpo.appointment_date) throw new Error("Elige la fecha y la hora de la cita.");
    if (editando === "nueva") await peticion("/api/appointments", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/appointments/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/appointments");
    setEditando(null);
    recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const cita = editando;
    Alert.alert("Eliminar cita", `Se borrará la cita de ${cita.patient_name} del ${fechaLarga(cita.appointment_date)}.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/appointments/${cita.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/appointments");
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const hayFiltro = !!(busqueda || estado || dia);
  // Nueva cita: mañana a las 8:00 como punto de partida.
  const manana = new Date();
  manana.setDate(manana.getDate() + 1);
  manana.setHours(8, 0, 0, 0);

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="Nueva cita" icono="agregar" onPress={() => setEditando("nueva")} />
        <Buscador valor={q} onChange={setQ} placeholder="Buscar paciente o teléfono" />
        <FiltroChips<"" | Cita["status"]>
          valor={estado}
          onChange={setEstado}
          opciones={[
            { valor: "", etiqueta: "Todas" },
            { valor: "confirmed", etiqueta: "Confirmadas" },
            { valor: "cancelled", etiqueta: "Canceladas" },
            { valor: "completed", etiqueta: "Completadas" },
          ]}
        />
        <SelectorFecha etiqueta="Día" valor={dia} onChange={setDia} conHora={false} opcional />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio
            icono="calendario"
            titulo={hayFiltro ? "Ninguna cita coincide" : "No hay citas"}
            texto={hayFiltro ? "Prueba con otro nombre, estado o día." : "Crea la primera o espera a que el voizbot agende una por teléfono."}
            accion={
              hayFiltro ? (
                <Boton
                  titulo="Quitar filtros"
                  variante="suave"
                  onPress={() => {
                    setQ("");
                    setEstado("");
                    setDia("");
                  }}
                />
              ) : undefined
            }
          />
        ) : null}
        {grupos.map((g) => (
          <View key={g.dia} style={{ gap: 8 }}>
            <Text style={{ fontSize: 12, fontWeight: "700", color: c.textoSecundario, textTransform: "uppercase", letterSpacing: 0.6, marginTop: 6 }}>
              {fechaLarga(g.dia, false)}
            </Text>
            {g.citas.map((cita) => {
              const e = ESTADOS[cita.status] ?? { texto: cita.status, tono: "neutro" as const };
              return (
                <Fila
                  key={cita.id}
                  titulo={cita.patient_name}
                  subtitulo={`${cita.duration_minutes} min · ${cita.phone}`}
                  izquierda={
                    <View style={{ width: 52, alignItems: "center" }}>
                      <Text style={{ fontSize: 15, fontWeight: "800", color: c.texto, fontVariant: ["tabular-nums"] }}>
                        {horaCorta(cita.appointment_date)}
                      </Text>
                    </View>
                  }
                  derecha={<Pildora texto={e.texto} tono={e.tono} />}
                  onPress={() => setEditando(cita)}
                  onLongPress={() => llamar(cita.phone)}
                />
              );
            })}
          </View>
        ))}
        {datos && datos.length >= limite ? (
          <Boton titulo="Cargar más" variante="suave" onPress={() => setLimite((l) => Math.min(l + POR_PAGINA, 500))} />
        ) : null}
        {datos && datos.length > 0 ? (
          <Text style={{ fontSize: 12, color: c.placeholder, textAlign: "center" }}>Mantén presionada una cita para llamar al paciente.</Text>
        ) : null}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva cita" : `Cita de ${editando ? editando.patient_name : ""}`}
        campos={CAMPOS}
        inicial={
          editando && editando !== "nueva"
            ? { ...editando, appointment_date: aTextoLocal(deTextoLocal(editando.appointment_date) ?? new Date()), notes: editando.notes ?? "" }
            : { patient_name: "", phone: "", appointment_date: aTextoLocal(manana), duration_minutes: 30, status: "confirmed", notes: "" }
        }
        textoGuardar={editando === "nueva" ? "Crear cita" : "Guardar"}
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}

export default function Citas() {
  const [vista, setVista] = useState<"gestion" | "agenda">("gestion");
  return (
    <View style={{ flex: 1 }}>
      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <Segmentado
          valor={vista}
          onChange={setVista}
          opciones={[
            { valor: "gestion", etiqueta: "Gestión del bot", icono: "bot" },
            { valor: "agenda", etiqueta: "Agenda", icono: "calendario" },
          ]}
        />
      </View>
      {vista === "gestion" ? <GestionBot /> : <Agenda />}
    </View>
  );
}
