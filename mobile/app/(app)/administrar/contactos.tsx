import * as DocumentPicker from "expo-document-picker";
import { useEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";

import { peticion, subirFormulario } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { invalidar, useDatos } from "@/src/datos";
import { fechaLarga, tiempoCorto } from "@/src/fecha";
import {
  Aviso,
  AvisoSinConexion,
  Avatar,
  Buscador,
  CampoDef,
  EstadoVacio,
  Fila,
  Hoja,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useLlamar } from "@/src/llamar";
import { useColores } from "@/src/tema";
import { Boton, Campo, FilaMenu, Metrica, Pildora, Seccion, Segmentado, Tarjeta, Tono } from "@/src/ui";

// --- Tipos (los mismos que el panel: frontend/lib/types.ts) -----------------

type TipoCampo = "texto" | "numero" | "fecha" | "opciones" | "si_no";

interface CampoContacto {
  id: number;
  clave: string;
  nombre: string;
  tipo: TipoCampo;
  opciones: string[];
  obligatorio: boolean;
}

interface Contacto {
  id: number;
  nombre: string;
  documento: string | null;
  telefono: string;
  telefonos: { numero: string; tipo: string }[];
  email: string | null;
  direccion: string | null;
  ciudad: string | null;
  campos: Record<string, string | number | boolean>;
  fuente: string | null;
  no_llamar: boolean;
  updated_at: string;
}

interface Ficha {
  contacto: Contacto;
  telefonos_no_llamar: string[];
  campos_definidos: CampoContacto[];
  notas: { id: number; texto: string; autor: string | null; created_at: string }[];
  secciones: { llamadas: boolean; campanas: boolean; cobranza: boolean; citas: boolean };
  llamadas: { id: number; direction: string; status: string; caller_number: string | null; callee_number: string | null; billsec: number; ring_ms: number | null; started_at: string | null }[];
  campanas: { numero_id: number; campana: string; phone: string; status: string; attempts: number; proximo_intento_at: string | null }[];
  deudas: { id: number; amount: number; due_date: string | null; status: string }[];
  promesas: { id: number; amount_promised: number; promise_date: string; status: string }[];
  citas: { id: number; appointment_date: string; status: string }[];
}

interface RegistroNoLlamar {
  id: number;
  telefono: string;
  motivo: string | null;
  hasta: string | null;
  creado_por: string | null;
  vigente: boolean;
}

interface VistaPrevia {
  columnas: string[];
  filas: string[][];
  total_filas: number;
  sugerido: Record<string, string>;
}

interface Reporte {
  filas: number;
  creados: number;
  actualizados: number;
  con_error: number;
  errores: { fila: number; motivo: string }[];
  campana: { added: number; updated: number; bloqueados?: unknown[] } | null;
}

const pesos = (n: number) => "$" + Number(n || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 });

const ESTADO_LLAMADA: Record<string, { texto: string; tono: Tono }> = {
  answered: { texto: "Contestada", tono: "ok" },
  no_answer: { texto: "Sin respuesta", tono: "aviso" },
  busy: { texto: "Ocupado", tono: "aviso" },
  failed: { texto: "Fallida", tono: "peligro" },
  rejected: { texto: "Rechazada", tono: "peligro" },
  cancelled: { texto: "Cancelada", tono: "neutro" },
};

const ESTADO_NUMERO: Record<string, { texto: string; tono: Tono }> = {
  pending: { texto: "Pendiente", tono: "aviso" },
  dialing: { texto: "Marcando", tono: "info" },
  done: { texto: "Completado", tono: "ok" },
  answered: { texto: "Contestó", tono: "ok" },
  busy: { texto: "Ocupado", tono: "peligro" },
  noanswer: { texto: "Sin respuesta", tono: "neutro" },
  failed: { texto: "Falló", tono: "peligro" },
  no_llamar: { texto: "No llamar", tono: "peligro" },
};

// --- Formulario del contacto ------------------------------------------------------

function camposFormulario(defs: CampoContacto[]): CampoDef[] {
  const fijos: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "Nombre y apellido" },
    { clave: "telefono", etiqueta: "Teléfono principal", tipo: "telefono", placeholder: "3011234567" },
    { clave: "telefono2", etiqueta: "Otro teléfono", tipo: "telefono", placeholder: "Opcional" },
    { clave: "documento", etiqueta: "Documento", placeholder: "Opcional" },
    { clave: "email", etiqueta: "Correo", tipo: "email", placeholder: "Opcional" },
    { clave: "direccion", etiqueta: "Dirección", placeholder: "Opcional" },
    { clave: "ciudad", etiqueta: "Ciudad", placeholder: "Opcional" },
  ];
  const propios: CampoDef[] = defs.map((d) => {
    const etiqueta = d.obligatorio ? `${d.nombre} *` : d.nombre;
    const clave = `campo:${d.clave}`;
    if (d.tipo === "si_no") return { clave, etiqueta: d.nombre, tipo: "conmutador" };
    if (d.tipo === "opciones") return { clave, etiqueta, tipo: "opciones", opciones: d.opciones.map((o) => ({ valor: o, etiqueta: o })) };
    if (d.tipo === "fecha") return { clave, etiqueta, tipo: "fecha", opcional: true };
    if (d.tipo === "numero") return { clave, etiqueta, tipo: "decimal" };
    return { clave, etiqueta };
  });
  return [...fijos, ...propios];
}

function inicialDe(c: Contacto | null, defs: CampoContacto[]): Record<string, unknown> {
  const v: Record<string, unknown> = {
    nombre: c?.nombre ?? "",
    telefono: c?.telefono ?? "",
    telefono2: c?.telefonos?.[0]?.numero ?? "",
    documento: c?.documento ?? "",
    email: c?.email ?? "",
    direccion: c?.direccion ?? "",
    ciudad: c?.ciudad ?? "",
  };
  for (const d of defs) {
    const actual = c?.campos?.[d.clave];
    v[`campo:${d.clave}`] = d.tipo === "si_no" ? actual === true : actual === undefined ? "" : String(actual);
  }
  return v;
}

function cuerpoDe(v: Record<string, unknown>, defs: CampoContacto[], previo: Contacto | null) {
  const texto = (k: string) => String(v[k] ?? "").trim();
  if (!texto("telefono")) throw new Error("Escribe el teléfono.");
  const campos: Record<string, unknown> = {};
  for (const d of defs) {
    const x = v[`campo:${d.clave}`];
    if (d.tipo === "si_no") {
      if (x) campos[d.clave] = true;
    } else if (String(x ?? "").trim()) {
      campos[d.clave] = String(x).trim();
    }
  }
  // El formulario del teléfono edita el primer número extra; los demás se conservan.
  const resto = (previo?.telefonos ?? []).slice(1);
  const telefonos = texto("telefono2") ? [{ numero: texto("telefono2"), tipo: previo?.telefonos?.[0]?.tipo ?? "otro" }, ...resto] : resto;
  return {
    nombre: texto("nombre"),
    telefono: texto("telefono"),
    telefonos,
    documento: texto("documento") || null,
    email: texto("email") || null,
    direccion: texto("direccion") || null,
    ciudad: texto("ciudad") || null,
    campos,
  };
}

// --- Ficha ------------------------------------------------------------------------------

function FichaContacto({ id, onCerrar, onCambio, gestiona }: { id: number | null; onCerrar: () => void; onCambio: () => void; gestiona: boolean }) {
  const c = useColores();
  const llamar = useLlamar();
  const ruta = id ? `/api/crm/contactos/${id}` : null;
  const { datos: ficha, error, recargar } = useDatos<Ficha>(ruta, { ttl: 0 });
  const [nota, setNota] = useState("");
  const [guardandoNota, setGuardandoNota] = useState(false);
  const [editando, setEditando] = useState(false);

  const refrescar = () => {
    if (ruta) invalidar(ruta);
    invalidar("/api/crm");
    recargar();
    onCambio();
  };

  const guardarNota = async () => {
    if (!id || !nota.trim()) return;
    setGuardandoNota(true);
    try {
      await peticion(`/api/crm/contactos/${id}/notas`, { method: "POST", body: { texto: nota.trim() } });
      exito();
      setNota("");
      refrescar();
    } catch (err) {
      fallo();
      Alert.alert("No se pudo guardar la nota", err instanceof Error ? err.message : "Error");
    } finally {
      setGuardandoNota(false);
    }
  };

  const noLlamar = () => {
    if (!ficha) return;
    Alert.alert("No llamar", `Ninguna campaña volverá a marcar ${ficha.contacto.telefono}.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Agregar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion("/api/crm/no-llamar", { method: "POST", body: { telefono: ficha.contacto.telefono } });
            exito();
            refrescar();
          } catch (err) {
            Alert.alert("No se pudo agregar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const borrar = () => {
    if (!ficha) return;
    Alert.alert("Borrar contacto", "Se borran el contacto y sus notas. Sus números en campañas se conservan.", [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Borrar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/crm/contactos/${ficha.contacto.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/crm");
            onCambio();
            onCerrar();
          } catch (err) {
            Alert.alert("No se pudo borrar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const k = ficha?.contacto;
  return (
    <>
      <Hoja visible={id !== null && !editando} titulo={k ? k.nombre || k.telefono : "Contacto"} onCerrar={onCerrar}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 14 }} keyboardShouldPersistTaps="handled">
          {error && !ficha ? <Aviso texto={error} /> : null}
          {!ficha ? <ListaEsqueleto filas={3} /> : null}
          {ficha && k ? (
            <>
              {ficha.telefonos_no_llamar.length > 0 ? (
                <Aviso tono="aviso" texto={`En no llamar: ${ficha.telefonos_no_llamar.join(", ")}. Ninguna campaña los marca.`} />
              ) : null}
              <View style={{ flexDirection: "row", gap: 10 }}>
                <Boton titulo="Llamar" icono="telefono" style={{ flex: 1 }} onPress={() => llamar(k.telefono)} />
                {gestiona ? <Boton titulo="Editar" icono="editar" variante="suave" style={{ flex: 1 }} onPress={() => setEditando(true)} /> : null}
              </View>
              <Seccion>
                <FilaMenu titulo="Teléfono" icono="telefono" valor={k.telefono} />
                {k.telefonos.map((t) => (
                  <FilaMenu key={t.numero} titulo={`Teléfono (${t.tipo})`} icono="telefono" valor={t.numero} onPress={() => llamar(t.numero)} />
                ))}
                {k.documento ? <FilaMenu titulo="Documento" icono="usuario" valor={k.documento} /> : null}
                {k.email ? <FilaMenu titulo="Correo" icono="enviar" valor={k.email} /> : null}
                {k.ciudad || k.direccion ? <FilaMenu titulo="Dirección" icono="ruta" valor={[k.direccion, k.ciudad].filter(Boolean).join(", ")} /> : null}
                {ficha.campos_definidos.map((d) => {
                  const v = k.campos[d.clave];
                  return (
                    <FilaMenu
                      key={d.clave}
                      titulo={d.nombre}
                      icono="info"
                      valor={v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "Sí" : "No") : String(v)}
                    />
                  );
                })}
                <FilaMenu titulo="Origen" icono="info" valor={k.fuente ?? "—"} ultima />
              </Seccion>

              <Seccion titulo="Notas" sinTarjeta>
                <View style={{ gap: 8 }}>
                  <Campo etiqueta="Nueva nota" value={nota} onChangeText={setNota} placeholder="Qué se habló, qué quedó pendiente…" multiline />
                  <Boton titulo="Guardar nota" variante="contorno" cargando={guardandoNota} deshabilitado={!nota.trim()} onPress={guardarNota} />
                  {ficha.notas.map((n) => (
                    <Tarjeta key={n.id} style={{ gap: 4 }}>
                      <Text style={{ fontSize: 14, color: c.texto, lineHeight: 20 }}>{n.texto}</Text>
                      <Text style={{ fontSize: 12, color: c.textoSecundario }}>
                        {n.autor ?? "—"} · {fechaLarga(n.created_at)}
                      </Text>
                    </Tarjeta>
                  ))}
                </View>
              </Seccion>

              {ficha.secciones.llamadas && ficha.llamadas.length > 0 ? (
                <Seccion titulo="Llamadas">
                  {ficha.llamadas.map((l, i) => {
                    const e = ESTADO_LLAMADA[l.status] ?? { texto: l.status, tono: "neutro" as const };
                    return (
                      <FilaMenu
                        key={l.id}
                        titulo={l.direction === "inbound" ? "Entrante" : "Saliente"}
                        detalle={[
                          fechaLarga(l.started_at),
                          l.billsec > 0 ? tiempoCorto(l.billsec) : "",
                          l.ring_ms !== null ? `ring ${tiempoCorto(l.ring_ms / 1000)}` : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                        icono={l.direction === "inbound" ? "entrante" : "saliente"}
                        derecha={<Pildora texto={e.texto} tono={e.tono} />}
                        ultima={i === ficha.llamadas.length - 1}
                      />
                    );
                  })}
                </Seccion>
              ) : null}

              {ficha.secciones.campanas && ficha.campanas.length > 0 ? (
                <Seccion titulo="Campañas">
                  {ficha.campanas.map((n, i) => {
                    const e = ESTADO_NUMERO[n.status] ?? { texto: n.status, tono: "neutro" as const };
                    return (
                      <FilaMenu
                        key={n.numero_id}
                        titulo={n.campana}
                        detalle={`${n.phone} · ${n.attempts} intento(s)${n.proximo_intento_at ? ` · próximo ${fechaLarga(n.proximo_intento_at)}` : ""}`}
                        icono="campana"
                        derecha={<Pildora texto={e.texto} tono={e.tono} />}
                        ultima={i === ficha.campanas.length - 1}
                      />
                    );
                  })}
                </Seccion>
              ) : null}

              {ficha.secciones.cobranza && (ficha.deudas.length > 0 || ficha.promesas.length > 0) ? (
                <Seccion titulo="Cobranza">
                  {ficha.deudas.map((d) => (
                    <FilaMenu key={`d${d.id}`} titulo={`Deuda ${pesos(d.amount)}`} detalle={d.due_date ? `Vence ${fechaLarga(d.due_date, false)}` : undefined} icono="dinero" valor={d.status} />
                  ))}
                  {ficha.promesas.map((p, i) => (
                    <FilaMenu
                      key={`p${p.id}`}
                      titulo={`Promesa ${pesos(p.amount_promised)}`}
                      detalle={`Para ${fechaLarga(p.promise_date, false)}`}
                      icono="ok"
                      valor={p.status}
                      ultima={i === ficha.promesas.length - 1}
                    />
                  ))}
                </Seccion>
              ) : null}

              {ficha.secciones.citas && ficha.citas.length > 0 ? (
                <Seccion titulo="Citas">
                  {ficha.citas.map((a, i) => (
                    <FilaMenu key={a.id} titulo={fechaLarga(a.appointment_date)} icono="calendario" valor={a.status} ultima={i === ficha.citas.length - 1} />
                  ))}
                </Seccion>
              ) : null}

              {gestiona ? (
                <Seccion>
                  {!k.no_llamar ? <FilaMenu titulo="Agregar a no llamar" icono="candado" tono="aviso" onPress={noLlamar} /> : null}
                  <FilaMenu titulo="Borrar contacto" icono="eliminar" peligro onPress={borrar} ultima />
                </Seccion>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      </Hoja>

      <HojaFormulario
        visible={editando && !!ficha}
        titulo="Editar contacto"
        campos={camposFormulario(ficha?.campos_definidos ?? [])}
        inicial={inicialDe(ficha?.contacto ?? null, ficha?.campos_definidos ?? [])}
        onGuardar={async (v) => {
          if (!ficha) return;
          await peticion(`/api/crm/contactos/${ficha.contacto.id}`, {
            method: "PUT",
            body: cuerpoDe(v, ficha.campos_definidos, ficha.contacto),
          });
          setEditando(false);
          refrescar();
        }}
        onCerrar={() => setEditando(false)}
      />
    </>
  );
}

// --- Pestañas ---------------------------------------------------------------------------

function Contactos({ campos, gestiona, vuelta }: { campos: CampoContacto[]; gestiona: boolean; vuelta: number }) {
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [limite, setLimite] = useState(50);
  const [abierto, setAbierto] = useState<number | null>(null);
  const [nuevo, setNuevo] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const qs = new URLSearchParams({ limit: String(limite) });
  if (busqueda) qs.set("q", busqueda);
  const { datos, cargando, error, sinConexion, recargar } = useDatos<{ total: number; contactos: Contacto[] }>(`/api/crm/contactos?${qs}`);

  useEffect(() => {
    if (vuelta) recargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vuelta]);

  const lista = datos?.contactos ?? [];
  return (
    <>
      {gestiona ? <Boton titulo="Nuevo contacto" icono="agregar" onPress={() => setNuevo(true)} /> : null}
      <Buscador valor={q} onChange={setQ} placeholder="Nombre, documento o teléfono" />
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
      {datos && lista.length === 0 ? (
        <EstadoVacio
          icono="contactos"
          titulo={busqueda ? "Sin coincidencias" : "Todavía no hay contactos"}
          texto={busqueda ? "Prueba con otra parte del nombre o del teléfono." : "Se crean solos al cargar números en una campaña, o impórtalos desde un CSV."}
        />
      ) : null}
      {lista.map((k) => (
        <Fila
          key={k.id}
          titulo={k.nombre || k.telefono}
          subtitulo={[k.telefono, k.ciudad].filter(Boolean).join(" · ")}
          izquierda={<Avatar nombre={k.nombre || k.telefono} />}
          derecha={k.no_llamar ? <Pildora texto="No llamar" tono="peligro" /> : undefined}
          onPress={() => setAbierto(k.id)}
        />
      ))}
      {datos && datos.total > lista.length ? (
        <Boton titulo={`Ver más (${datos.total - lista.length})`} variante="texto" onPress={() => setLimite((l) => Math.min(l + 50, 200))} />
      ) : null}

      <FichaContacto id={abierto} gestiona={gestiona} onCerrar={() => setAbierto(null)} onCambio={recargar} />
      <HojaFormulario
        visible={nuevo}
        titulo="Nuevo contacto"
        campos={camposFormulario(campos)}
        inicial={inicialDe(null, campos)}
        onGuardar={async (v) => {
          const creado = await peticion<Contacto>("/api/crm/contactos", { method: "POST", body: cuerpoDe(v, campos, null) });
          setNuevo(false);
          invalidar("/api/crm/contactos");
          recargar();
          setAbierto(creado.id);
        }}
        onCerrar={() => setNuevo(false)}
      />
    </>
  );
}

function NoLlamar({ gestiona }: { gestiona: boolean }) {
  const c = useColores();
  const [q, setQ] = useState("");
  const [telefono, setTelefono] = useState("");
  const [motivo, setMotivo] = useState("");
  const [guardando, setGuardando] = useState(false);
  const { datos, cargando, error, recargar } = useDatos<{ total: number; registros: RegistroNoLlamar[] }>(
    `/api/crm/no-llamar${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`
  );

  const agregar = async () => {
    setGuardando(true);
    try {
      await peticion("/api/crm/no-llamar", { method: "POST", body: { telefono: telefono.trim(), motivo: motivo.trim() || null } });
      exito();
      setTelefono("");
      setMotivo("");
      invalidar("/api/crm");
      recargar();
    } catch (err) {
      fallo();
      Alert.alert("No se pudo agregar", err instanceof Error ? err.message : "Error");
    } finally {
      setGuardando(false);
    }
  };

  const quitar = (r: RegistroNoLlamar) =>
    Alert.alert("Quitar de no llamar", `Las campañas podrán volver a marcar ${r.telefono}.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Quitar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/crm/no-llamar/${r.id}`, { method: "DELETE" });
            invalidar("/api/crm");
            recargar();
          } catch (err) {
            Alert.alert("No se pudo quitar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  return (
    <>
      {gestiona ? (
        <Tarjeta style={{ gap: 10 }}>
          <Campo etiqueta="Teléfono" value={telefono} onChangeText={setTelefono} keyboardType="phone-pad" placeholder="3011234567" />
          <Campo etiqueta="Motivo (opcional)" value={motivo} onChangeText={setMotivo} placeholder="Lo pidió en la llamada" />
          <Boton titulo="Agregar a no llamar" icono="candado" cargando={guardando} deshabilitado={!telefono.trim()} onPress={agregar} />
          <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>
            Ninguna campaña marca estos números, en ninguna de sus formas (con o sin +57).
          </Text>
        </Tarjeta>
      ) : null}
      <Buscador valor={q} onChange={setQ} placeholder="Buscar teléfono" />
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
      {datos && datos.registros.length === 0 ? <EstadoVacio icono="candado" titulo="La lista está vacía" texto="Agrega aquí a quien pidió que no lo llamen." /> : null}
      {(datos?.registros ?? []).map((r) => (
        <Fila
          key={r.id}
          titulo={r.telefono}
          subtitulo={[r.motivo, r.creado_por].filter(Boolean).join(" · ") || undefined}
          derecha={
            <Pildora
              texto={r.vigente ? (r.hasta ? `Hasta ${fechaLarga(r.hasta, false)}` : "Siempre") : "Vencido"}
              tono={r.vigente ? "peligro" : "neutro"}
            />
          }
          onLongPress={gestiona ? () => quitar(r) : undefined}
          onPress={gestiona ? () => quitar(r) : undefined}
        />
      ))}
    </>
  );
}

const TIPOS = [
  { valor: "texto", etiqueta: "Texto" },
  { valor: "numero", etiqueta: "Número" },
  { valor: "fecha", etiqueta: "Fecha" },
  { valor: "opciones", etiqueta: "Lista de opciones" },
  { valor: "si_no", etiqueta: "Sí / No" },
];

function Campos({ campos, gestiona, onCambio }: { campos: CampoContacto[]; gestiona: boolean; onCambio: () => void }) {
  const [editando, setEditando] = useState<CampoContacto | "nuevo" | null>(null);
  const formulario: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "Plan contratado" },
    ...(editando === "nuevo" ? [{ clave: "clave", etiqueta: "Clave", placeholder: "plan", ayuda: "Minúsculas, números y _. No cambia después." }] : []),
    { clave: "tipo", etiqueta: "Tipo", tipo: "opciones", opciones: TIPOS },
    { clave: "opciones", etiqueta: "Opciones (separadas por coma)", placeholder: "Oro, Plata, Bronce", visibleSi: (v) => v.tipo === "opciones" },
    { clave: "obligatorio", etiqueta: "Obligatorio", tipo: "conmutador" },
  ];

  const borrar = () => {
    if (!editando || editando === "nuevo") return;
    const d = editando;
    Alert.alert("Borrar campo", `«${d.nombre}» deja de pedirse y de mostrarse.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Borrar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/crm/campos/${d.id}`, { method: "DELETE" });
            setEditando(null);
            onCambio();
          } catch (err) {
            Alert.alert("No se pudo borrar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  return (
    <>
      {gestiona ? <Boton titulo="Nuevo campo" icono="agregar" onPress={() => setEditando("nuevo")} /> : null}
      {campos.length === 0 ? (
        <EstadoVacio icono="usuario" titulo="Sin campos propios" texto="Lo que tu operación necesita guardar de cada cliente: plan, saldo, sede…" />
      ) : (
        <Seccion>
          {campos.map((d, i) => (
            <FilaMenu
              key={d.id}
              titulo={d.nombre}
              detalle={`${TIPOS.find((t) => t.valor === d.tipo)?.etiqueta}${d.tipo === "opciones" ? `: ${d.opciones.join(", ")}` : ""}`}
              icono="usuario"
              valor={d.obligatorio ? "Obligatorio" : undefined}
              onPress={gestiona ? () => setEditando(d) : undefined}
              ultima={i === campos.length - 1}
            />
          ))}
        </Seccion>
      )}
      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nuevo" ? "Nuevo campo" : "Editar campo"}
        campos={formulario}
        inicial={
          editando && editando !== "nuevo"
            ? { nombre: editando.nombre, tipo: editando.tipo, opciones: editando.opciones.join(", "), obligatorio: editando.obligatorio }
            : { nombre: "", clave: "", tipo: "texto", opciones: "", obligatorio: false }
        }
        onGuardar={async (v) => {
          const cuerpo = {
            nombre: String(v.nombre ?? "").trim(),
            tipo: String(v.tipo || "texto"),
            opciones: v.tipo === "opciones" ? String(v.opciones ?? "").split(",").map((o) => o.trim()).filter(Boolean) : null,
            obligatorio: !!v.obligatorio,
          };
          if (!cuerpo.nombre) throw new Error("Ponle un nombre al campo.");
          if (editando === "nuevo") {
            await peticion("/api/crm/campos", { method: "POST", body: { ...cuerpo, clave: String(v.clave ?? "").trim().toLowerCase() } });
          } else if (editando) {
            await peticion(`/api/crm/campos/${editando.id}`, { method: "PUT", body: cuerpo });
          }
          setEditando(null);
          onCambio();
        }}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nuevo" ? borrar : undefined}
      />
    </>
  );
}

const DESTINOS_FIJOS = [
  { valor: "", etiqueta: "No importar" },
  { valor: "nombre", etiqueta: "Nombre" },
  { valor: "documento", etiqueta: "Documento" },
  { valor: "telefono", etiqueta: "Teléfono principal" },
  { valor: "telefono2", etiqueta: "Teléfono 2" },
  { valor: "telefono3", etiqueta: "Teléfono 3" },
  { valor: "email", etiqueta: "Correo" },
  { valor: "direccion", etiqueta: "Dirección" },
  { valor: "ciudad", etiqueta: "Ciudad" },
];

function variableDe(columna: string) {
  const base = columna
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return (/^[a-z]/.test(base) ? base : `col_${base}`).slice(0, 40);
}

function Importar({ campos, onImportado }: { campos: CampoContacto[]; onImportado: () => void }) {
  const c = useColores();
  const { puede, tieneModulo } = useAuth();
  const conCampanas = puede("campanas:gestionar") && tieneModulo("voicebot");
  const campanas = useDatos<{ id: number; name: string }[]>(conCampanas ? "/api/campaigns" : null, { ttl: 30_000 });
  const [archivo, setArchivo] = useState<{ uri: string; name: string; type: string } | null>(null);
  const [vista, setVista] = useState<VistaPrevia | null>(null);
  const [mapeo, setMapeo] = useState<Record<string, string>>({});
  const [columna, setColumna] = useState<string | null>(null);
  const [campana, setCampana] = useState("");
  const [eligiendoCampana, setEligiendoCampana] = useState(false);
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState("");
  const [reporte, setReporte] = useState<Reporte | null>(null);

  const elegir = async () => {
    setError("");
    const r = await DocumentPicker.getDocumentAsync({ type: ["text/csv", "text/comma-separated-values", "text/plain", "application/vnd.ms-excel"], copyToCacheDirectory: true });
    if (r.canceled || !r.assets?.[0]) return;
    const a = r.assets[0];
    const f = { uri: a.uri, name: a.name || "contactos.csv", type: a.mimeType || "text/csv" };
    setTrabajando(true);
    try {
      const v = await subirFormulario<VistaPrevia>("/api/crm/importar/vista-previa", { archivo: f });
      setArchivo(f);
      setVista(v);
      setMapeo(v.sugerido);
      setReporte(null);
    } catch (err) {
      fallo();
      setError(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      setTrabajando(false);
    }
  };

  const importar = async () => {
    if (!archivo) return;
    setTrabajando(true);
    setError("");
    try {
      const datos: Record<string, string | typeof archivo> = { archivo, mapeo: JSON.stringify(mapeo) };
      if (campana) {
        datos.campaign_id = campana;
        datos.nombre_lista = archivo.name.replace(/\.[^.]+$/, "");
      }
      setReporte(await subirFormulario<Reporte>("/api/crm/importar", datos));
      exito();
      invalidar("/api/crm");
      invalidar("/api/campaigns");
      onImportado();
    } catch (err) {
      fallo();
      setError(err instanceof Error ? err.message : "No se pudo importar");
    } finally {
      setTrabajando(false);
    }
  };

  const reiniciar = () => {
    setArchivo(null);
    setVista(null);
    setMapeo({});
    setReporte(null);
    setCampana("");
  };

  const destinos = (col: string) => [
    ...DESTINOS_FIJOS,
    ...campos.map((d) => ({ valor: `campo:${d.clave}`, etiqueta: `Campo: ${d.nombre}` })),
    ...(campana ? [{ valor: `var:${variableDe(col)}`, etiqueta: `Variable {${variableDe(col)}}` }] : []),
  ];
  const etiquetaDe = (col: string) => destinos(col).find((d) => d.valor === (mapeo[col] ?? ""))?.etiqueta ?? "No importar";
  const usados = new Set(Object.values(mapeo).filter(Boolean));
  const nombreCampana = campanas.datos?.find((x) => String(x.id) === campana)?.name;

  if (reporte) {
    return (
      <>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Metrica etiqueta="Nuevos" valor={reporte.creados} icono="agregar" tono="ok" />
          <Metrica etiqueta="Actualizados" valor={reporte.actualizados} icono="refrescar" tono="info" />
        </View>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Metrica etiqueta="Filas" valor={reporte.filas} icono="info" tono="neutro" />
          <Metrica etiqueta="Con error" valor={reporte.con_error} icono="error" tono={reporte.con_error ? "peligro" : "neutro"} />
        </View>
        {reporte.campana ? <Aviso tono="ok" texto={`Campaña: ${reporte.campana.added} número(s) agregado(s).`} /> : null}
        {reporte.errores.length > 0 ? (
          <Seccion titulo="Filas que no entraron">
            {reporte.errores.slice(0, 50).map((e, i) => (
              <FilaMenu key={e.fila} titulo={`Fila ${e.fila}`} detalle={e.motivo} icono="error" tono="peligro" ultima={i === Math.min(reporte.errores.length, 50) - 1} />
            ))}
          </Seccion>
        ) : null}
        <Boton titulo="Importar otro archivo" variante="suave" onPress={reiniciar} />
      </>
    );
  }

  return (
    <>
      {error ? <Aviso texto={error} /> : null}
      {!vista ? (
        <Tarjeta style={{ gap: 10 }}>
          <Text style={{ fontSize: 14, color: c.texto, lineHeight: 20 }}>
            Archivo CSV con encabezados (Excel: Guardar como → CSV). Primero verás una vista previa: no se guarda nada hasta confirmar.
          </Text>
          <Boton titulo="Elegir archivo" icono="agregar" cargando={trabajando} onPress={elegir} />
        </Tarjeta>
      ) : (
        <>
          <Text style={{ fontSize: 13, color: c.textoSecundario, lineHeight: 18 }}>
            {archivo?.name} · {vista.total_filas} fila(s). Toca cada columna para decir qué es; el teléfono es obligatorio.
          </Text>
          <Seccion titulo="Columnas">
            {vista.columnas.map((col, i) => (
              <FilaMenu
                key={col + i}
                titulo={col || "(sin nombre)"}
                detalle={vista.filas.map((f) => f[i]).filter(Boolean).slice(0, 2).join(" · ") || undefined}
                valor={etiquetaDe(col)}
                onPress={() => setColumna(col)}
                ultima={i === vista.columnas.length - 1}
              />
            ))}
          </Seccion>
          {conCampanas ? (
            <Seccion>
              <FilaMenu
                titulo="Cargar también en una campaña"
                icono="campana"
                valor={nombreCampana ?? "Solo al CRM"}
                onPress={() => setEligiendoCampana(true)}
                ultima
              />
            </Seccion>
          ) : null}
          <Boton
            titulo={`Importar ${vista.total_filas} fila(s)`}
            icono="ok"
            cargando={trabajando}
            deshabilitado={!usados.has("telefono")}
            onPress={importar}
          />
          {!usados.has("telefono") ? <Aviso tono="aviso" texto="Falta indicar qué columna es el teléfono." /> : null}
          <Boton titulo="Elegir otro archivo" variante="texto" onPress={reiniciar} />
        </>
      )}

      <Hoja visible={columna !== null} titulo={columna ? `«${columna}» va a…` : ""} onCerrar={() => setColumna(null)}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 8 }}>
          {columna !== null
            ? destinos(columna).map((d) => {
                const ocupado = !!d.valor && usados.has(d.valor) && mapeo[columna] !== d.valor;
                const activo = (mapeo[columna] ?? "") === d.valor;
                return (
                  <Pressable
                    key={d.valor || "nada"}
                    disabled={ocupado}
                    onPress={() => {
                      setMapeo({ ...mapeo, [columna]: d.valor });
                      setColumna(null);
                    }}
                    style={{
                      padding: 14,
                      borderRadius: 12,
                      borderWidth: 1,
                      borderColor: activo ? c.marca : c.borde,
                      backgroundColor: activo ? c.marcaSuave : c.superficie,
                      opacity: ocupado ? 0.4 : 1,
                    }}
                  >
                    <Text style={{ fontSize: 15, color: c.texto, fontWeight: activo ? "700" : "500" }}>{d.etiqueta}</Text>
                    {ocupado ? <Text style={{ fontSize: 12, color: c.textoSecundario }}>Ya lo usa otra columna</Text> : null}
                  </Pressable>
                );
              })
            : null}
        </ScrollView>
      </Hoja>

      <Hoja visible={eligiendoCampana} titulo="Cargar en una campaña" onCerrar={() => setEligiendoCampana(false)}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 8 }}>
          {[{ id: 0, name: "Solo al CRM" }, ...(campanas.datos ?? [])].map((x) => {
            const valor = x.id ? String(x.id) : "";
            const activo = campana === valor;
            return (
              <Pressable
                key={x.id}
                onPress={() => {
                  setCampana(valor);
                  setEligiendoCampana(false);
                }}
                style={{ padding: 14, borderRadius: 12, borderWidth: 1, borderColor: activo ? c.marca : c.borde, backgroundColor: activo ? c.marcaSuave : c.superficie }}
              >
                <Text style={{ fontSize: 15, color: c.texto, fontWeight: activo ? "700" : "500" }}>{x.name}</Text>
              </Pressable>
            );
          })}
          <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>
            Entran como una lista nueva que puedes pausar o priorizar desde la campaña.
          </Text>
        </ScrollView>
      </Hoja>
    </>
  );
}

// --- Pantalla -------------------------------------------------------------------------------

type Vista = "contactos" | "importar" | "no_llamar" | "campos";

export default function ContactosScreen() {
  const { puede } = useAuth();
  const gestiona = puede("crm:gestionar");
  const [vista, setVista] = useState<Vista>("contactos");
  const [vuelta, setVuelta] = useState(0);
  const campos = useDatos<CampoContacto[]>("/api/crm/campos", { ttl: 60_000 });

  const refrescar = () => {
    invalidar("/api/crm");
    campos.recargar();
    setVuelta((n) => n + 1);
  };

  const opciones: { valor: Vista; etiqueta: string }[] = [
    { valor: "contactos", etiqueta: "Contactos" },
    ...(gestiona ? [{ valor: "importar" as const, etiqueta: "Importar" }] : []),
    { valor: "no_llamar", etiqueta: "No llamar" },
    { valor: "campos", etiqueta: "Campos" },
  ];

  return (
    <Pantalla refrescando={campos.refrescando} onRefrescar={refrescar}>
      <Segmentado valor={vista} onChange={setVista} opciones={opciones} />
      {vista === "contactos" ? <Contactos campos={campos.datos ?? []} gestiona={gestiona} vuelta={vuelta} /> : null}
      {vista === "importar" && gestiona ? <Importar campos={campos.datos ?? []} onImportado={() => setVuelta((n) => n + 1)} /> : null}
      {vista === "no_llamar" ? <NoLlamar gestiona={gestiona} /> : null}
      {vista === "campos" ? (
        <Campos
          campos={campos.datos ?? []}
          gestiona={gestiona}
          onCambio={() => {
            invalidar("/api/crm/campos");
            campos.recargar();
          }}
        />
      ) : null}
    </Pantalla>
  );
}
