import { useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { fechaLarga } from "@/src/fecha";
import {
  Aviso,
  AvisoSinConexion,
  Avatar,
  Buscador,
  CampoDef,
  EstadoVacio,
  Fila,
  FiltroChips,
  Hoja,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useLlamar } from "@/src/llamar";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Metrica, Pildora, Seccion, Segmentado, Tono } from "@/src/ui";

interface Deuda {
  id: number;
  phone: string;
  debtor_name: string;
  amount: number;
  due_date: string | null;
  invoice_number: string | null;
  notes: string | null;
  status: "open" | "promised" | "overdue" | "paid";
}

interface Promesa {
  id: number;
  phone: string;
  debtor_name: string | null;
  amount_promised: number;
  promise_date: string;
  plan: string;
  installments: number | null;
  notes: string | null;
  status: "pending" | "completed" | "missed";
}

interface Resumen {
  debts_open: number;
  amount_owed: number;
  promises_pending: number;
  amount_promised: number;
}

const ESTADO_DEUDA: Record<Deuda["status"], { texto: string; tono: Tono }> = {
  open: { texto: "Pendiente", tono: "aviso" },
  promised: { texto: "Con promesa", tono: "info" },
  overdue: { texto: "Vencida", tono: "peligro" },
  paid: { texto: "Pagada", tono: "ok" },
};

const ESTADO_PROMESA: Record<Promesa["status"], { texto: string; tono: Tono }> = {
  pending: { texto: "Pendiente", tono: "aviso" },
  completed: { texto: "Cumplida", tono: "ok" },
  missed: { texto: "Incumplida", tono: "peligro" },
};

const PLANES: Record<string, string> = { completo: "Pago total", abono: "Abono", cuotas: "Plan de cuotas" };

const pesos = (n: number) => "$" + Number(n || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 });

const camposDeuda = (nueva: boolean): CampoDef[] => [
  { clave: "debtor_name", etiqueta: "Nombre del deudor", placeholder: "Nombre y apellido" },
  ...(nueva ? [{ clave: "phone", etiqueta: "Teléfono", tipo: "telefono" as const, placeholder: "3011234567" }] : []),
  { clave: "amount", etiqueta: "Monto (pesos)", tipo: "numero" },
  { clave: "due_date", etiqueta: "Vencimiento", tipo: "fecha", opcional: true },
  { clave: "invoice_number", etiqueta: "Factura o número de cuenta", placeholder: "Opcional" },
  {
    clave: "status",
    etiqueta: "Estado",
    tipo: "opciones",
    opciones: (Object.keys(ESTADO_DEUDA) as Deuda["status"][]).map((k) => ({ valor: k, etiqueta: ESTADO_DEUDA[k].texto })),
  },
  { clave: "notes", etiqueta: "Notas", tipo: "multilinea", placeholder: "Opcional" },
];

function Deudas({ alCambiar, vuelta }: { alCambiar: () => void; vuelta: number }) {
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [estado, setEstado] = useState<"" | Deuda["status"]>("");
  const [editando, setEditando] = useState<Deuda | "nueva" | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const qs = new URLSearchParams({ limit: "200" });
  if (busqueda) qs.set("search", busqueda);
  if (estado) qs.set("estado", estado);
  const { datos, cargando, error, sinConexion, recargar } = useDatos<Deuda[]>(`/api/cobranza/debts?${qs}`);

  // El padre pide recargar (arrastrar para actualizar) sin perder los filtros.
  useEffect(() => {
    if (vuelta) recargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vuelta]);

  const refrescarTodo = () => {
    invalidar("/api/cobranza");
    recargar();
    alCambiar();
  };

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo: Record<string, unknown> = {
      debtor_name: String(v.debtor_name ?? "").trim(),
      amount: Number(v.amount) || 0,
      due_date: String(v.due_date ?? "") || null,
      invoice_number: String(v.invoice_number ?? "").trim() || null,
      notes: String(v.notes ?? "").trim() || null,
      status: v.status || "open",
    };
    if (!cuerpo.debtor_name) throw new Error("Escribe el nombre del deudor.");
    if (editando === "nueva") {
      cuerpo.phone = String(v.phone ?? "").trim();
      if (!cuerpo.phone) throw new Error("Escribe el teléfono.");
      await peticion("/api/cobranza/debts", { method: "POST", body: cuerpo });
    } else if (editando) {
      await peticion(`/api/cobranza/debts/${editando.id}`, { method: "PUT", body: cuerpo });
    }
    setEditando(null);
    refrescarTodo();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const d = editando;
    Alert.alert("Eliminar deuda", `Se borrará la deuda de ${d.debtor_name} (${pesos(d.amount)}). El voizbot ya no la mencionará.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/cobranza/debts/${d.id}`, { method: "DELETE" });
            exito();
            setEditando(null);
            refrescarTodo();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  return (
    <>
      <Boton titulo="Nueva deuda" icono="agregar" onPress={() => setEditando("nueva")} />
      <Buscador valor={q} onChange={setQ} placeholder="Buscar por nombre o teléfono" />
      <FiltroChips<"" | Deuda["status"]>
        valor={estado}
        onChange={setEstado}
        opciones={[{ valor: "", etiqueta: "Todas" }, ...(Object.keys(ESTADO_DEUDA) as Deuda["status"][]).map((k) => ({ valor: k, etiqueta: ESTADO_DEUDA[k].texto }))]}
      />
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
      {datos && datos.length === 0 ? (
        <EstadoVacio
          icono="dinero"
          titulo={busqueda || estado ? "Ninguna deuda coincide" : "No hay deudas"}
          texto={busqueda || estado ? "Prueba con otro nombre o estado." : "Se cargan solas con una campaña de cobranza, o créalas a mano."}
        />
      ) : null}
      {(datos ?? []).map((d) => {
        const e = ESTADO_DEUDA[d.status] ?? { texto: d.status, tono: "neutro" as const };
        return (
          <Fila
            key={d.id}
            titulo={d.debtor_name}
            subtitulo={`${pesos(d.amount)} · ${d.due_date ? "vence " + fechaLarga(d.due_date, false) : d.phone}`}
            izquierda={<Avatar nombre={d.debtor_name} />}
            derecha={<Pildora texto={e.texto} tono={e.tono} />}
            onPress={() => setEditando(d)}
          />
        );
      })}

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva deuda" : editando ? editando.debtor_name : ""}
        campos={camposDeuda(editando === "nueva")}
        inicial={
          editando && editando !== "nueva"
            ? { ...editando, due_date: editando.due_date?.slice(0, 10) ?? "", invoice_number: editando.invoice_number ?? "", notes: editando.notes ?? "" }
            : { debtor_name: "", phone: "", amount: "", due_date: "", invoice_number: "", status: "open", notes: "" }
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}

function Promesas({ alCambiar, vuelta }: { alCambiar: () => void; vuelta: number }) {
  const c = useColores();
  const llamar = useLlamar();
  const [estado, setEstado] = useState<"" | Promesa["status"]>("pending");
  const [abierta, setAbierta] = useState<Promesa | null>(null);
  const [guardando, setGuardando] = useState<Promesa["status"] | null>(null);
  const [errorHoja, setErrorHoja] = useState("");

  const { datos, cargando, error, sinConexion, recargar } = useDatos<Promesa[]>(
    `/api/cobranza/promises?limit=200${estado ? `&estado=${estado}` : ""}`
  );

  // El padre pide recargar (arrastrar para actualizar) sin perder los filtros.
  useEffect(() => {
    if (vuelta) recargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vuelta]);

  const marcar = async (p: Promesa, nuevo: Promesa["status"]) => {
    setGuardando(nuevo);
    setErrorHoja("");
    try {
      await peticion(`/api/cobranza/promises/${p.id}`, { method: "PUT", body: { status: nuevo } });
      exito();
      invalidar("/api/cobranza");
      setAbierta(null);
      recargar();
      alCambiar();
    } catch (err) {
      fallo();
      setErrorHoja(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setGuardando(null);
    }
  };

  return (
    <>
      <FiltroChips<"" | Promesa["status"]>
        valor={estado}
        onChange={setEstado}
        opciones={[
          { valor: "pending", etiqueta: "Pendientes" },
          { valor: "completed", etiqueta: "Cumplidas" },
          { valor: "missed", etiqueta: "Incumplidas" },
          { valor: "", etiqueta: "Todas" },
        ]}
      />
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
      {datos && datos.length === 0 ? (
        <EstadoVacio icono="dinero" titulo="Sin promesas" texto="Aparecen cuando el voizbot cierra una promesa de pago en una llamada." />
      ) : null}
      {(datos ?? []).map((p) => {
        const e = ESTADO_PROMESA[p.status] ?? { texto: p.status, tono: "neutro" as const };
        return (
          <Fila
            key={p.id}
            titulo={p.debtor_name || p.phone}
            subtitulo={`${pesos(p.amount_promised)} · ${PLANES[p.plan] ?? p.plan} · ${fechaLarga(p.promise_date, false)}`}
            izquierda={<Avatar nombre={p.debtor_name || p.phone} />}
            derecha={<Pildora texto={e.texto} tono={e.tono} />}
            onPress={() => {
              setErrorHoja("");
              setAbierta(p);
            }}
          />
        );
      })}

      <Hoja visible={!!abierta} titulo={abierta?.debtor_name || abierta?.phone || ""} onCerrar={() => setAbierta(null)}>
        {abierta ? (
          <View style={{ padding: 20, paddingTop: 4, gap: 14 }}>
            <Seccion>
              <FilaMenu titulo="Monto prometido" icono="dinero" tono="ok" valor={pesos(abierta.amount_promised)} />
              <FilaMenu titulo="Fecha de pago" icono="calendario" tono="info" valor={fechaLarga(abierta.promise_date, false)} />
              <FilaMenu
                titulo="Plan"
                icono="tendencia"
                valor={`${PLANES[abierta.plan] ?? abierta.plan}${abierta.installments ? ` · ${abierta.installments} cuotas` : ""}`}
              />
              <FilaMenu titulo="Teléfono" icono="telefono" valor={abierta.phone} ultima />
            </Seccion>
            {abierta.notes ? <Text style={{ fontSize: 13, color: c.textoSuave, lineHeight: 19 }}>{abierta.notes}</Text> : null}
            {errorHoja ? <Aviso texto={errorHoja} /> : null}
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Boton
                titulo="Cumplida"
                icono="ok"
                variante="ok"
                style={{ flex: 1 }}
                deshabilitado={abierta.status === "completed"}
                cargando={guardando === "completed"}
                onPress={() => marcar(abierta, "completed")}
              />
              <Boton
                titulo="Incumplida"
                icono="error"
                variante="peligro"
                style={{ flex: 1 }}
                deshabilitado={abierta.status === "missed"}
                cargando={guardando === "missed"}
                onPress={() => marcar(abierta, "missed")}
              />
            </View>
            {abierta.status !== "pending" ? (
              <Boton titulo="Volver a pendiente" variante="suave" cargando={guardando === "pending"} onPress={() => marcar(abierta, "pending")} />
            ) : null}
            <Boton titulo={`Llamar a ${abierta.phone}`} icono="telefono" variante="contorno" onPress={() => llamar(abierta.phone)} />
            <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>
              Marcarla cumplida no salda la deuda: un abono o una cuota cumplen la promesa y la deuda sigue. El estado de la deuda se
              cambia en Deudas.
            </Text>
          </View>
        ) : null}
      </Hoja>
    </>
  );
}

export default function Cobranza() {
  const [vista, setVista] = useState<"deudas" | "promesas">("deudas");
  const r = useDatos<Resumen>("/api/cobranza/summary", { ttl: 15_000 });
  // Arrastrar para actualizar recarga el resumen y la lista que se ve.
  const [vuelta, setVuelta] = useState(0);
  const refrescar = () => {
    invalidar("/api/cobranza");
    setVuelta((n) => n + 1);
    r.recargar();
  };

  return (
    <Pantalla refrescando={r.refrescando} onRefrescar={refrescar}>
      <View style={{ flexDirection: "row", gap: 10 }}>
        <Metrica etiqueta="Deudas vigentes" valor={r.datos?.debts_open ?? "—"} icono="alerta" tono="aviso" />
        <Metrica etiqueta="Adeudado" valor={r.datos ? pesos(r.datos.amount_owed) : "—"} icono="dinero" tono="peligro" />
      </View>
      <View style={{ flexDirection: "row", gap: 10 }}>
        <Metrica etiqueta="Promesas pendientes" valor={r.datos?.promises_pending ?? "—"} icono="calendario" tono="info" />
        <Metrica etiqueta="Prometido" valor={r.datos ? pesos(r.datos.amount_promised) : "—"} icono="ok" tono="ok" />
      </View>
      <Segmentado
        valor={vista}
        onChange={setVista}
        opciones={[
          { valor: "deudas", etiqueta: "Deudas", icono: "dinero" },
          { valor: "promesas", etiqueta: "Promesas", icono: "ok" },
        ]}
      />
      {vista === "deudas" ? <Deudas vuelta={vuelta} alCambiar={r.recargar} /> : <Promesas vuelta={vuelta} alCambiar={r.recargar} />}
    </Pantalla>
  );
}
