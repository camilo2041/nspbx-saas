import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";

import type { CallLogOut } from "@/src/api/types";
import { useContactos, type ContactoTel } from "@/src/contactos";
import { useDatos } from "@/src/datos";
import { SelectorFecha } from "@/src/fecha";
import { useFavoritos } from "@/src/favoritos";
import { Aviso, AvisoSinConexion, Avatar, Buscador, EstadoVacio, FiltroChips, Fila, Hoja, ListaEsqueleto } from "@/src/gestion";
import { impacto, toque } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { Icono } from "@/src/Icono";
import { useColores } from "@/src/tema";
import { Boton, BotonIcono, CajaIcono, Segmentado } from "@/src/ui";

type Vista = "recientes" | "contactos" | "favoritos";
type Tipo = "todas" | "inbound" | "outbound" | "perdidas";

const aFecha = (iso: string | null) => (iso ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`) : null);

function tituloDia(d: Date): string {
  const hoy = new Date();
  const ayer = new Date();
  ayer.setDate(hoy.getDate() - 1);
  const mismo = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (mismo(d, hoy)) return "Hoy";
  if (mismo(d, ayer)) return "Ayer";
  return d.toLocaleDateString("es-CO", { weekday: "short", day: "numeric", month: "short" });
}

const hora = (d: Date) => d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });

function duracion(seg: number): string {
  if (seg <= 0) return "";
  const m = Math.floor(seg / 60);
  return m > 0 ? `${m} min ${seg % 60}s` : `${seg}s`;
}

const esPerdida = (c: CallLogOut) => c.direction === "inbound" && c.status !== "answered";
const numeroContrario = (c: CallLogOut) => (c.direction === "inbound" ? c.caller_number : c.callee_number) ?? "";

type Item = { tipo: "cab"; clave: string; titulo: string } | { tipo: "llamada"; clave: string; c: CallLogOut };

function Recientes({ llamar }: { llamar: (n: string) => void }) {
  const col = useColores();
  const router = useRouter();
  const [tipo, setTipo] = useState<Tipo>("todas");
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [limite, setLimite] = useState(100);
  const [dia, setDia] = useState("");

  // Espera a que la persona deje de escribir para no pedir al servidor en cada tecla.
  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const direccion = tipo === "inbound" || tipo === "perdidas" ? "&direction=inbound" : tipo === "outbound" ? "&direction=outbound" : "";
  const path = `/api/calls?limit=${limite}${direccion}${busqueda ? `&search=${encodeURIComponent(busqueda)}` : ""}${dia ? `&day=${dia}` : ""}`;
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<CallLogOut[]>(path, { ttl: 15_000 });

  const items = useMemo<Item[]>(() => {
    const filas = (datos ?? []).filter((c) => (tipo === "perdidas" ? esPerdida(c) : true));
    const salida: Item[] = [];
    let ultimo = "";
    for (const c of filas) {
      const d = aFecha(c.started_at);
      const dia = d ? tituloDia(d) : "Sin fecha";
      if (dia !== ultimo) {
        salida.push({ tipo: "cab", clave: `cab-${dia}-${c.id}`, titulo: dia });
        ultimo = dia;
      }
      salida.push({ tipo: "llamada", clave: `c-${c.id}`, c });
    }
    return salida;
  }, [datos, tipo]);

  const cabecera = (
    <View style={{ gap: 12, paddingBottom: 8 }}>
      <Buscador valor={q} onChange={setQ} placeholder="Buscar por número o nombre" />
      <FiltroChips<Tipo>
        valor={tipo}
        onChange={setTipo}
        opciones={[
          { valor: "todas", etiqueta: "Todas" },
          { valor: "perdidas", etiqueta: "Perdidas" },
          { valor: "inbound", etiqueta: "Entrantes" },
          { valor: "outbound", etiqueta: "Salientes" },
        ]}
      />
      <SelectorFecha etiqueta="Día" valor={dia} onChange={setDia} conHora={false} opcional />
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando && !datos ? <ListaEsqueleto /> : null}
    </View>
  );

  return (
    <FlatList
      data={items}
      keyExtractor={(i) => i.clave}
      ListHeaderComponent={cabecera}
      contentContainerStyle={{ padding: 16, paddingBottom: 130, gap: 8 }}
      refreshControl={<RefreshControl refreshing={refrescando} onRefresh={recargar} tintColor={col.marca} colors={[col.marca]} />}
      initialNumToRender={12}
      windowSize={9}
      removeClippedSubviews
      keyboardShouldPersistTaps="handled"
      ListEmptyComponent={
        datos ? (
          <EstadoVacio
            icono="historial"
            titulo={busqueda || dia || tipo !== "todas" ? "Sin resultados" : "Aún no hay llamadas"}
            texto={busqueda || dia || tipo !== "todas" ? "Prueba con otro filtro." : "Aquí aparecerán las llamadas que hagas y recibas."}
          />
        ) : null
      }
      ListFooterComponent={
        datos && datos.length >= limite ? (
          <View style={{ paddingTop: 8 }}>
            <Boton titulo="Cargar más" variante="suave" onPress={() => setLimite((l) => Math.min(l + 100, 500))} />
          </View>
        ) : null
      }
      renderItem={({ item }) => {
        if (item.tipo === "cab") {
          return <Text style={{ fontSize: 12, fontWeight: "700", color: col.textoSecundario, textTransform: "uppercase", letterSpacing: 0.6, marginTop: 8 }}>{item.titulo}</Text>;
        }
        const c = item.c;
        const d = aFecha(c.started_at);
        const perdida = esPerdida(c);
        const nombre = (c.direction === "inbound" ? c.caller_name : null) || numeroContrario(c) || "Desconocido";
        const sentido = perdida ? "Perdida" : c.direction === "inbound" ? "Entrante" : "Saliente";
        return (
          <Fila
            titulo={nombre}
            subtitulo={`${sentido} · ${d ? hora(d) : ""}${c.billsec > 0 ? " · " + duracion(c.billsec) : ""}`}
            izquierda={
              <CajaIcono
                icono={perdida ? "perdida" : c.direction === "inbound" ? "entrante" : "saliente"}
                tono={perdida ? "peligro" : c.direction === "inbound" ? "info" : "ok"}
              />
            }
            derecha={
              <BotonIcono
                icono="telefono"
                etiqueta={`Llamar a ${nombre}`}
                tono="ok"
                tam={38}
                onPress={() => {
                  impacto();
                  llamar(numeroContrario(c));
                }}
              />
            }
            onPress={() => router.push({ pathname: "/llamada/[id]", params: { id: String(c.id) } })}
          />
        );
      }}
    />
  );
}

function Contactos({ llamar }: { llamar: (n: string) => void }) {
  const col = useColores();
  const { estado, contactos, pedirPermiso } = useContactos(true);
  const { esFavorito, alternar } = useFavoritos();
  const [q, setQ] = useState("");
  const [elegido, setElegido] = useState<ContactoTel | null>(null);

  const lista = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return contactos;
    return contactos.filter((c) => c.nombre.toLowerCase().includes(t) || c.numeros.some((n) => n.numero.replace(/\D/g, "").includes(t.replace(/\D/g, "") || "§")));
  }, [contactos, q]);

  if (estado === "sin-permiso" || estado === "denegado") {
    return (
      <EstadoVacio
        icono="contactos"
        titulo="Llama a tus contactos"
        texto={
          estado === "denegado"
            ? "El permiso está bloqueado. Actívalo en Ajustes del teléfono → Aplicaciones → NSPBX → Permisos."
            : "Para marcar sin escribir el número, permite que NSPBX lea tus contactos. Solo se leen en tu teléfono; no se envían a ningún lado."
        }
        accion={estado === "sin-permiso" ? <Boton titulo="Permitir contactos" onPress={pedirPermiso} /> : undefined}
      />
    );
  }
  if (estado === "revisando" || estado === "cargando") return <View style={{ padding: 16 }}><ListaEsqueleto filas={6} /></View>;
  if (estado === "error") return <EstadoVacio icono="alerta" titulo="No se pudieron leer los contactos" texto="Cierra y vuelve a abrir la app, o revisa el permiso." />;

  const marcar = (c: ContactoTel) => {
    if (c.numeros.length === 1) llamar(c.numeros[0].numero);
    else setElegido(c);
  };

  return (
    <>
      <FlatList
        data={lista}
        keyExtractor={(c) => c.clave}
        ListHeaderComponent={<View style={{ paddingBottom: 8 }}><Buscador valor={q} onChange={setQ} placeholder="Buscar contacto" /></View>}
        contentContainerStyle={{ padding: 16, paddingBottom: 130, gap: 8 }}
        initialNumToRender={14}
        windowSize={9}
        removeClippedSubviews
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={<EstadoVacio icono="contactos" titulo={q ? "Sin resultados" : "No hay contactos con número"} />}
        renderItem={({ item: c }) => (
          <Fila
            titulo={c.nombre}
            subtitulo={c.numeros.length > 1 ? `${c.numeros.length} números` : c.numeros[0].numero}
            izquierda={<Avatar nombre={c.nombre} />}
            derecha={
              <Pressable
                hitSlop={10}
                accessibilityRole="button"
                accessibilityLabel={esFavorito(c.numeros[0].numero) ? "Quitar de favoritos" : "Agregar a favoritos"}
                onPress={() => {
                  toque();
                  alternar({ numero: c.numeros[0].numero, nombre: c.nombre });
                }}
              >
                <Icono
                  nombre={esFavorito(c.numeros[0].numero) ? "favorito" : "noFavorito"}
                  tam={22}
                  color={esFavorito(c.numeros[0].numero) ? col.aviso : col.placeholder}
                />
              </Pressable>
            }
            onPress={() => marcar(c)}
          />
        )}
      />
      <Hoja visible={!!elegido} titulo={elegido?.nombre ?? ""} onCerrar={() => setElegido(null)}>
        <View style={{ padding: 20, paddingTop: 4, gap: 10 }}>
          {elegido?.numeros.map((n) => (
            <Fila
              key={n.numero}
              titulo={n.numero}
              subtitulo={n.etiqueta || "Teléfono"}
              derecha={<Icono nombre="telefono" tam={20} color={col.ok} />}
              onPress={() => {
                setElegido(null);
                llamar(n.numero);
              }}
            />
          ))}
        </View>
      </Hoja>
    </>
  );
}

function Favoritos({ llamar }: { llamar: (n: string) => void }) {
  const col = useColores();
  const { favoritos, alternar } = useFavoritos();
  return (
    <FlatList
      data={favoritos}
      keyExtractor={(f) => f.numero}
      contentContainerStyle={{ padding: 16, paddingBottom: 130, gap: 8 }}
      ListEmptyComponent={
        <EstadoVacio icono="favorito" titulo="Sin favoritos" texto="En Contactos, toca la estrella de quien llamas seguido y aparecerá aquí para marcar de un toque." />
      }
      renderItem={({ item: f }) => (
        <Fila
          titulo={f.nombre}
          subtitulo={f.numero}
          izquierda={<Avatar nombre={f.nombre} />}
          derecha={<Icono nombre="telefono" tam={20} color={col.ok} />}
          onPress={() => llamar(f.numero)}
          onLongPress={() => alternar(f)}
        />
      )}
    />
  );
}

export default function Llamadas() {
  const col = useColores();
  const router = useRouter();
  const { call } = useSoftphone();
  const [vista, setVista] = useState<Vista>("recientes");

  // Marca y lleva a la pantalla del teléfono, donde se ve la llamada (o el motivo si no puede salir).
  const llamar = (numero: string) => {
    const limpio = numero.replace(/[^0-9+*#]/g, "");
    if (!limpio) return;
    call(limpio);
    router.navigate("/");
  };

  return (
    <View style={{ flex: 1, backgroundColor: col.fondo }}>
      <View style={{ padding: 16, paddingBottom: 4 }}>
        <Segmentado<Vista>
          valor={vista}
          onChange={setVista}
          opciones={[
            { valor: "recientes", etiqueta: "Recientes", icono: "historial" },
            { valor: "contactos", etiqueta: "Contactos", icono: "contactos" },
            { valor: "favoritos", etiqueta: "Favoritos", icono: "favorito" },
          ]}
        />
      </View>
      {vista === "recientes" ? <Recientes llamar={llamar} /> : vista === "contactos" ? <Contactos llamar={llamar} /> : <Favoritos llamar={llamar} />}
    </View>
  );
}
