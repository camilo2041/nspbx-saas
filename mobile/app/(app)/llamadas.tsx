import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";

import type { CallLogOut } from "@/src/api/types";
import { useContactos, type ContactoTel } from "@/src/contactos";
import { useDatos } from "@/src/datos";
import { useFavoritos } from "@/src/favoritos";
import { Aviso, AvisoSinConexion, Avatar, Buscador, EstadoVacio, FiltroChips, Fila, Hoja, ListaEsqueleto } from "@/src/gestion";
import { impacto, toque } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { colores, radios } from "@/src/tema";
import { Boton } from "@/src/ui";

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
  const router = useRouter();
  const [tipo, setTipo] = useState<Tipo>("todas");
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [limite, setLimite] = useState(100);

  // Espera a que la persona deje de escribir para no pedir al servidor en cada tecla.
  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const direccion = tipo === "inbound" || tipo === "perdidas" ? "&direction=inbound" : tipo === "outbound" ? "&direction=outbound" : "";
  const path = `/api/calls?limit=${limite}${direccion}${busqueda ? `&search=${encodeURIComponent(busqueda)}` : ""}`;
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
      refreshControl={<RefreshControl refreshing={refrescando} onRefresh={recargar} tintColor={colores.marca} colors={[colores.marca]} />}
      initialNumToRender={12}
      windowSize={9}
      removeClippedSubviews
      keyboardShouldPersistTaps="handled"
      ListEmptyComponent={
        datos ? (
          <EstadoVacio
            icono="📞"
            titulo={busqueda || tipo !== "todas" ? "Sin resultados" : "Aún no hay llamadas"}
            texto={busqueda || tipo !== "todas" ? "Prueba con otro filtro." : "Aquí aparecerán las llamadas que hagas y recibas."}
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
          return <Text style={{ fontSize: 12, fontWeight: "700", color: colores.textoSecundario, textTransform: "uppercase", letterSpacing: 0.6, marginTop: 8 }}>{item.titulo}</Text>;
        }
        const c = item.c;
        const d = aFecha(c.started_at);
        const perdida = esPerdida(c);
        const nombre = (c.direction === "inbound" ? c.caller_name : null) || numeroContrario(c) || "Desconocido";
        const flecha = c.direction === "inbound" ? "↙" : "↗";
        return (
          <Fila
            titulo={nombre}
            subtitulo={`${flecha} ${d ? hora(d) : ""}${c.billsec > 0 ? " · " + duracion(c.billsec) : ""}${perdida ? " · Perdida" : ""}`}
            izquierda={<Avatar nombre={nombre} />}
            derecha={
              <Pressable
                onPress={() => {
                  impacto();
                  llamar(numeroContrario(c));
                }}
                hitSlop={10}
                style={{ width: 38, height: 38, borderRadius: 19, backgroundColor: colores.okSuave, alignItems: "center", justifyContent: "center" }}
              >
                <Text style={{ fontSize: 17 }}>📞</Text>
              </Pressable>
            }
            onPress={() => router.push({ pathname: "/llamada/[id]", params: { id: String(c.id) } })}
          />
        );
      }}
    />
  );
}

function Contactos({ llamar }: { llamar: (n: string) => void }) {
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
        icono="📇"
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
  if (estado === "error") return <EstadoVacio icono="⚠️" titulo="No se pudieron leer los contactos" texto="Cierra y vuelve a abrir la app, o revisa el permiso." />;

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
        ListEmptyComponent={<EstadoVacio icono="📇" titulo={q ? "Sin resultados" : "No hay contactos con número"} />}
        renderItem={({ item: c }) => (
          <Fila
            titulo={c.nombre}
            subtitulo={c.numeros.length > 1 ? `${c.numeros.length} números` : c.numeros[0].numero}
            izquierda={<Avatar nombre={c.nombre} />}
            derecha={
              <Pressable
                hitSlop={10}
                onPress={() => {
                  toque();
                  alternar({ numero: c.numeros[0].numero, nombre: c.nombre });
                }}
              >
                <Text style={{ fontSize: 20 }}>{esFavorito(c.numeros[0].numero) ? "⭐" : "☆"}</Text>
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
              derecha={<Text style={{ fontSize: 18 }}>📞</Text>}
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
  const { favoritos, alternar } = useFavoritos();
  return (
    <FlatList
      data={favoritos}
      keyExtractor={(f) => f.numero}
      contentContainerStyle={{ padding: 16, paddingBottom: 130, gap: 8 }}
      ListEmptyComponent={
        <EstadoVacio icono="⭐" titulo="Sin favoritos" texto="En Contactos, toca la estrella de quien llamas seguido y aparecerá aquí para marcar de un toque." />
      }
      renderItem={({ item: f }) => (
        <Fila
          titulo={f.nombre}
          subtitulo={f.numero}
          izquierda={<Avatar nombre={f.nombre} />}
          derecha={<Text style={{ fontSize: 18 }}>📞</Text>}
          onPress={() => llamar(f.numero)}
          onLongPress={() => alternar(f)}
        />
      )}
    />
  );
}

export default function Llamadas() {
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
    <View style={{ flex: 1, backgroundColor: colores.fondo }}>
      <View style={{ padding: 16, paddingBottom: 4 }}>
        <View style={{ flexDirection: "row", backgroundColor: colores.superficie3, borderRadius: radios.medio, padding: 3 }}>
          {(
            [
              ["recientes", "Recientes"],
              ["contactos", "Contactos"],
              ["favoritos", "Favoritos"],
            ] as [Vista, string][]
          ).map(([v, etiqueta]) => (
            <Pressable
              key={v}
              onPress={() => {
                toque();
                setVista(v);
              }}
              style={{ flex: 1, paddingVertical: 9, borderRadius: radios.chico, alignItems: "center", backgroundColor: vista === v ? colores.superficie : "transparent" }}
            >
              <Text style={{ fontSize: 13.5, fontWeight: "700", color: vista === v ? colores.texto : colores.textoSecundario }}>{etiqueta}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      {vista === "recientes" ? <Recientes llamar={llamar} /> : vista === "contactos" ? <Contactos llamar={llamar} /> : <Favoritos llamar={llamar} />}
    </View>
  );
}
