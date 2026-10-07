import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Text, TextInput, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { Aviso, EstadoVacio, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito, fallo, toque } from "@/src/haptico";
import { esperarSesionAgente, useSoftphone } from "@/src/softphone/SoftphoneContext";
import { radios, useColores } from "@/src/tema";
import { Boton, Pildora, Tarjeta, Tono } from "@/src/ui";

type EstadoAgente = "LISTO" | "PAUSA" | "PREVIA" | "TIMBRANDO" | "EN_LLAMADA" | "DISPO";

interface Estado {
  agente: {
    estado: EstadoAgente;
    desde: string | null;
    audio: boolean;
    campanas: number[];
    codigo_pausa_id: number | null;
    telefono: string | null;
    token_audio: string | null;
  } | null;
  campanas: { id: number; nombre: string; metodo: string; status: string }[];
  pausas: { id: number; nombre: string }[];
  disposiciones: { id: number; nombre: string; categoria: string }[];
  lead: {
    telefono: string;
    campana: { nombre: string } | null;
    guion: string | null;
    contacto: { nombre?: string | null; documento?: string | null } | null;
    notas: { texto: string; autor: string | null }[];
  } | null;
}

const ESTADOS: Record<EstadoAgente, { texto: string; tono: Tono }> = {
  LISTO: { texto: "Listo", tono: "ok" },
  PAUSA: { texto: "En pausa", tono: "aviso" },
  PREVIA: { texto: "Vista previa", tono: "info" },
  TIMBRANDO: { texto: "Timbrando", tono: "info" },
  EN_LLAMADA: { texto: "En llamada", tono: "marca" },
  DISPO: { texto: "Cerrar la llamada", tono: "neutro" },
};

function tiempo(desde: string | null): string {
  if (!desde) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(desde.endsWith("Z") ? desde : `${desde}Z`).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Consola de agente en el teléfono (la misma de «Trabajar» en el panel):
 * entrar a las campañas, quedar listo o en pausa, ver al cliente que entra y
 * cerrar la llamada con una disposición. El audio de la sala llega como una
 * llamada a la extensión y la app la contesta sola (SoftphoneContext).
 */
export default function ConsolaAgente() {
  const c = useColores();
  const { connState } = useSoftphone();
  const [estado, setEstado] = useState<Estado | null>(null);
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState("");
  const [elegidas, setElegidas] = useState<number[]>([]);
  const [nota, setNota] = useState("");
  const [, setTick] = useState(0);
  const vivo = useRef(true);

  const aplicar = useCallback((e: Estado) => {
    if (!vivo.current) return;
    setEstado(e);
    esperarSesionAgente(e.agente?.token_audio ?? null);
  }, []);

  const cargar = useCallback(() => {
    peticion<Estado>("/api/agente/estado").then(aplicar, (e) => vivo.current && setError(e instanceof ApiError ? e.message : "Sin conexión"));
  }, [aplicar]);

  useEffect(() => {
    vivo.current = true;
    cargar();
    const datos = setInterval(cargar, 3000);
    const reloj = setInterval(() => setTick((t) => t + 1), 1000);
    return () => {
      vivo.current = false;
      clearInterval(datos);
      clearInterval(reloj);
    };
  }, [cargar]);

  const hacer = async (clave: string, ruta: string, cuerpo: unknown = {}) => {
    toque();
    setTrabajando(clave);
    setError("");
    try {
      aplicar(await peticion<Estado>(`/api/agente/${ruta}`, { method: "POST", body: cuerpo }));
      exito();
    } catch (e) {
      fallo();
      setError(e instanceof ApiError ? e.message : "No se pudo. Revisa tu conexión.");
    } finally {
      setTrabajando("");
    }
  };

  if (!estado) {
    return (
      <Pantalla>
        {error ? <Aviso texto={error} /> : <ListaEsqueleto filas={3} />}
      </Pantalla>
    );
  }

  const a = estado.agente;

  // --- Sin sesión: elegir campañas y empezar ---------------------------------------------------
  if (!a) {
    if (!estado.campanas.length) {
      return (
        <Pantalla onRefrescar={cargar}>
          <EstadoVacio icono="campana" titulo="No tienes campañas asignadas" texto="Pídele a tu supervisor que te asigne a una campaña." />
        </Pantalla>
      );
    }
    const seleccion = elegidas.length ? elegidas : estado.campanas.filter((x) => x.status === "running").map((x) => x.id);
    return (
      <Pantalla onRefrescar={cargar}>
        {error ? <Aviso texto={error} /> : null}
        {connState !== "registered" ? (
          <Aviso tono="aviso" texto="El teléfono de la app no está conectado: el audio de la sala te llega a la extensión. Conéctalo en la pestaña Teléfono." />
        ) : null}
        <Tarjeta style={{ gap: 10 }}>
          <Text style={{ fontSize: 16, fontWeight: "700", color: c.texto }}>¿En qué campañas trabajas hoy?</Text>
          {estado.campanas.map((x) => {
            const activa = seleccion.includes(x.id);
            return (
              <Tarjeta
                key={x.id}
                onPress={() => setElegidas(activa ? seleccion.filter((i) => i !== x.id) : [...seleccion, x.id])}
                style={{ flexDirection: "row", alignItems: "center", gap: 10, borderColor: activa ? c.marca : c.borde, padding: 12 }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ fontSize: 15, fontWeight: "600", color: c.texto }}>{x.nombre}</Text>
                  <Text style={{ fontSize: 12, color: c.textoSecundario }}>{x.status === "running" ? "En curso" : "Detenida"}</Text>
                </View>
                {activa ? <Pildora texto="Elegida" tono="marca" icono="listo" /> : null}
              </Tarjeta>
            );
          })}
          <Boton
            titulo="Empezar a trabajar"
            icono="telefono"
            cargando={trabajando === "entrar"}
            deshabilitado={!seleccion.length}
            onPress={() => hacer("entrar", "entrar", { campanas: seleccion })}
          />
          <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 17 }}>
            La central llama a tu extensión para abrir el audio; la app contesta sola. Después quedas listo para recibir clientes.
          </Text>
        </Tarjeta>
      </Pantalla>
    );
  }

  // --- En sesión ----------------------------------------------------------------------------------
  const est = ESTADOS[a.estado] ?? { texto: a.estado, tono: "neutro" as Tono };
  const lead = estado.lead;
  const pausar = () =>
    Alert.alert(
      "¿Por qué pausas?",
      undefined,
      [
        ...estado.pausas.slice(0, 6).map((p) => ({ text: p.nombre, onPress: () => hacer("pausa", "pausa", { codigo_pausa_id: p.id }) })),
        { text: "Cancelar", style: "cancel" as const },
      ]
    );

  return (
    <Pantalla onRefrescar={cargar}>
      {error ? <Aviso texto={error} /> : null}
      <Tarjeta style={{ gap: 12 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          <Pildora texto={est.texto} tono={est.tono} />
          <Text style={{ fontSize: 15, color: c.textoSecundario, fontVariant: ["tabular-nums"] }}>{tiempo(a.desde)}</Text>
          <View style={{ flex: 1 }} />
          <Pildora texto={a.audio ? "Audio conectado" : "Sin audio"} tono={a.audio ? "ok" : "peligro"} icono={a.audio ? "audio" : "alerta"} />
        </View>
        {!a.audio ? (
          <Boton titulo="Reconectar audio" variante="contorno" cargando={trabajando === "audio"} onPress={() => hacer("audio", "audio")} />
        ) : null}
        <View style={{ flexDirection: "row", gap: 8 }}>
          {a.estado === "PAUSA" ? (
            <Boton style={{ flex: 1 }} titulo="Quedar listo" variante="ok" cargando={trabajando === "listo"} deshabilitado={!a.audio} onPress={() => hacer("listo", "listo")} />
          ) : a.estado === "LISTO" ? (
            <Boton style={{ flex: 1 }} titulo="Pausa" variante="contorno" icono="pausa" cargando={trabajando === "pausa"} onPress={pausar} />
          ) : null}
          {a.estado === "EN_LLAMADA" ? (
            <Boton style={{ flex: 1 }} titulo="Colgar" variante="peligro" icono="colgar" cargando={trabajando === "colgar"} onPress={() => hacer("colgar", "colgar")} />
          ) : null}
          {a.estado === "LISTO" || a.estado === "PAUSA" ? (
            <Boton style={{ flex: 1 }} titulo="Terminar" variante="texto" cargando={trabajando === "salir"} onPress={() => hacer("salir", "salir")} />
          ) : null}
        </View>
      </Tarjeta>

      {lead ? (
        <Tarjeta style={{ gap: 8 }}>
          <Text style={{ fontSize: 12, fontWeight: "700", color: c.textoSecundario, textTransform: "uppercase", letterSpacing: 0.6 }}>
            Cliente{lead.campana ? ` · ${lead.campana.nombre}` : ""}
          </Text>
          <Text style={{ fontSize: 20, fontWeight: "800", color: c.texto }}>{lead.contacto?.nombre || lead.telefono}</Text>
          {lead.contacto?.nombre ? <Text style={{ fontSize: 14, color: c.textoSecundario }}>{lead.telefono}</Text> : null}
          {lead.guion ? (
            <View style={{ backgroundColor: c.superficie2, borderRadius: radios.chico, padding: 10 }}>
              <Text style={{ fontSize: 14, color: c.textoSuave, lineHeight: 20 }}>{lead.guion}</Text>
            </View>
          ) : null}
          {lead.notas.slice(0, 3).map((n, i) => (
            <Text key={i} style={{ fontSize: 13, color: c.textoSecundario }}>
              • {n.texto}
              {n.autor ? ` — ${n.autor}` : ""}
            </Text>
          ))}
        </Tarjeta>
      ) : null}

      {a.estado === "DISPO" ? (
        <Tarjeta style={{ gap: 10 }}>
          <Text style={{ fontSize: 16, fontWeight: "700", color: c.texto }}>¿Cómo terminó la llamada?</Text>
          <TextInput
            value={nota}
            onChangeText={setNota}
            placeholder="Nota (opcional)"
            placeholderTextColor={c.placeholder}
            multiline
            style={{ borderWidth: 1, borderColor: c.borde, borderRadius: radios.medio, padding: 10, minHeight: 60, color: c.texto }}
          />
          {estado.disposiciones.map((d) => (
            <Boton
              key={d.id}
              titulo={d.nombre}
              variante="contorno"
              cargando={trabajando === `d${d.id}`}
              onPress={async () => {
                await hacer(`d${d.id}`, "disponer", { disposicion_id: d.id, nota: nota.trim() || null });
                setNota("");
              }}
            />
          ))}
        </Tarjeta>
      ) : null}
    </Pantalla>
  );
}
