import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { useDatos } from "@/src/datos";
import { Aviso } from "@/src/gestion";
import { exito, fallo, toque } from "@/src/haptico";
import { colores, radios } from "@/src/tema";

interface Accion {
  herramienta: string;
  argumentos: Record<string, unknown>;
  simulada: boolean;
  resultado: string;
}

interface RespuestaIvr {
  modo: "ivr";
  nodo?: string;
  texto: string;
  opciones: { tecla: string; etiqueta: string }[];
  fin: boolean;
  nota?: string;
}

interface RespuestaIa {
  modo: "ia";
  reply?: string;
  texto?: string;
  terminada?: boolean;
  acciones?: Accion[];
  intencion?: string;
  nota?: string;
  datos?: { telefono: string; modo: string; tipo?: string; detalle: string };
}

interface DatosPrueba {
  citas: { telefono: string; nombre: string; cuando: string }[];
  deudas: { telefono: string; nombre: string; monto: number }[];
}

type Respuesta = RespuestaIvr | RespuestaIa;

interface Burbuja {
  quien: "bot" | "yo" | "sistema";
  texto: string;
  acciones?: Accion[];
}

const TECLADO = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

export default function ProbarBot() {
  const { id, nombre, tipo } = useLocalSearchParams<{ id: string; nombre?: string; tipo?: string }>();
  const [burbujas, setBurbujas] = useState<Burbuja[]>([]);
  const [modo, setModo] = useState<"ivr" | "ia">(tipo === "ai" ? "ia" : "ivr");
  const [nodo, setNodo] = useState<string | undefined>();
  const [opciones, setOpciones] = useState<{ tecla: string; etiqueta: string }[]>([]);
  const [intencion, setIntencion] = useState("general");
  const [fin, setFin] = useState(false);
  const [texto, setTexto] = useState("");
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [telefono, setTelefono] = useState("");
  const ultimoDato = useRef("");
  const scroll = useRef<ScrollView>(null);
  // Teléfonos con cita o deuda reales, para probar con datos de verdad en vez de inventados.
  const { datos: sugeridos } = useDatos<DatosPrueba>("/api/voicebots/probar/datos", { ttl: 60_000 });

  const abajo = () => setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 80);

  const aplicar = useCallback((r: Respuesta) => {
    if (r.modo === "ivr") {
      setBurbujas((b) => [...b, { quien: "bot", texto: r.texto }, ...(r.nota ? [{ quien: "sistema" as const, texto: r.nota }] : [])]);
      setNodo(r.nodo);
      setOpciones(r.opciones);
      setFin(r.fin);
    } else {
      if (r.nota) setBurbujas((b) => [...b, { quien: "sistema", texto: r.nota! }]);
      if (r.reply) setBurbujas((b) => [...b, { quien: "bot", texto: r.reply!, acciones: r.acciones }]);
      else if (r.texto) setBurbujas((b) => [...b, { quien: "bot", texto: r.texto! }]);
      setModo("ia");
      setOpciones([]);
      if (r.intencion) setIntencion(r.intencion);
      // Qué datos reales detectó el bot para ese número (solo cuando cambian).
      if (r.datos && r.datos.detalle !== ultimoDato.current) {
        ultimoDato.current = r.datos.detalle;
        setBurbujas((b) => [...b, { quien: "sistema", texto: "🔎 " + r.datos!.detalle }]);
      }
      if (r.terminada) {
        setFin(true);
        setBurbujas((b) => [...b, { quien: "sistema", texto: "El bot terminó la llamada." }]);
      }
    }
    abajo();
  }, []);

  const enviar = useCallback(
    async (cuerpo: Record<string, unknown>) => {
      setCargando(true);
      setError("");
      try {
        aplicar(await peticion<Respuesta>(`/api/voicebots/${id}/probar`, { method: "POST", body: cuerpo }));
        exito();
      } catch (e) {
        fallo();
        setError(e instanceof ApiError ? e.message : "No se pudo probar el bot. Revisa tu conexión.");
      } finally {
        setCargando(false);
      }
    },
    [id, aplicar]
  );

  const empezar = useCallback(() => {
    setBurbujas([]);
    setFin(false);
    setNodo(undefined);
    setOpciones([]);
    setModo(tipo === "ai" ? "ia" : "ivr");
    setIntencion("general");
    ultimoDato.current = "";
    if (tipo === "ai") {
      setBurbujas([
        {
          quien: "sistema",
          texto: telefono
            ? `Simulando una llamada desde ${telefono}: el bot verá su cita o deuda real. Escribe como el cliente.`
            : "Escribe como si fueras un cliente que llama. Sin número, el bot usa una persona y una cita de prueba.",
        },
      ]);
    } else {
      enviar({ modo: "ivr" });
    }
  }, [tipo, enviar, telefono]);

  useEffect(() => {
    empezar();
    // solo al abrir la pantalla
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const marcar = (tecla: string) => {
    toque();
    setBurbujas((b) => [...b, { quien: "yo", texto: `Marcaste ${tecla}` }]);
    enviar({ modo: "ivr", nodo, tecla });
  };

  const escribir = () => {
    const t = texto.trim();
    if (!t || cargando) return;
    setTexto("");
    const historial = [...burbujas.filter((b) => b.quien !== "sistema"), { quien: "yo" as const, texto: t }];
    setBurbujas((b) => [...b, { quien: "yo", texto: t }]);
    enviar({
      modo: "ia",
      intencion,
      telefono: telefono || undefined,
      mensajes: historial.slice(-20).map((b) => ({ role: b.quien === "yo" ? "user" : "assistant", content: b.texto })),
    });
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colores.fondo }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <View style={{ padding: 12, paddingBottom: 0 }}>
        <Aviso tono="ok" texto={`Simulación de «${nombre ?? "bot"}»: no llama a nadie ni modifica la agenda ni la cobranza.`} />
      </View>
      {modo === "ia" || tipo !== "ai" ? (
        <View style={{ paddingHorizontal: 12, paddingTop: 8, gap: 6 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <TextInput
              value={telefono}
              onChangeText={(t) => setTelefono(t.replace(/[^0-9+]/g, ""))}
              onSubmitEditing={empezar}
              placeholder="Simular llamada desde el número… (opcional)"
              placeholderTextColor={colores.placeholder}
              selectionColor={colores.marca}
              keyboardType="phone-pad"
              maxLength={30}
              style={{ flex: 1, borderWidth: 1, borderColor: colores.bordeFuerte, borderRadius: radios.medio, paddingHorizontal: 12, paddingVertical: 8, fontSize: 14, color: colores.texto, backgroundColor: colores.superficie }}
            />
            <Pressable onPress={empezar} style={{ backgroundColor: colores.superficie3, borderRadius: radios.medio, paddingHorizontal: 12, paddingVertical: 10 }}>
              <Text style={{ fontWeight: "700", fontSize: 12, color: colores.textoSuave }}>Reiniciar</Text>
            </Pressable>
          </View>
          {sugeridos && (sugeridos.citas.length > 0 || sugeridos.deudas.length > 0) ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
              {sugeridos.citas.map((c) => (
                <Pressable key={"c" + c.telefono + c.cuando} onPress={() => setTelefono(c.telefono.replace(/[^0-9+]/g, ""))} style={{ backgroundColor: colores.infoSuave, borderRadius: 999, paddingVertical: 5, paddingHorizontal: 11 }}>
                  <Text style={{ fontSize: 12, color: colores.infoTexto, fontWeight: "600" }}>📅 {c.nombre} · {c.cuando}</Text>
                </Pressable>
              ))}
              {sugeridos.deudas.map((d) => (
                <Pressable key={"d" + d.telefono} onPress={() => setTelefono(d.telefono.replace(/[^0-9+]/g, ""))} style={{ backgroundColor: colores.avisoSuave, borderRadius: 999, paddingVertical: 5, paddingHorizontal: 11 }}>
                  <Text style={{ fontSize: 12, color: colores.avisoTexto, fontWeight: "600" }}>💰 {d.nombre}</Text>
                </Pressable>
              ))}
            </ScrollView>
          ) : null}
        </View>
      ) : null}
      <ScrollView ref={scroll} contentContainerStyle={{ padding: 16, gap: 10 }} keyboardShouldPersistTaps="handled">
        {burbujas.map((b, i) =>
          b.quien === "sistema" ? (
            <Text key={i} style={{ textAlign: "center", fontSize: 12, color: colores.textoSecundario, paddingHorizontal: 12 }}>
              {b.texto}
            </Text>
          ) : (
            <View key={i} style={{ alignSelf: b.quien === "yo" ? "flex-end" : "flex-start", maxWidth: "88%", gap: 6 }}>
              <View
                style={{
                  backgroundColor: b.quien === "yo" ? colores.marca : colores.superficie,
                  borderRadius: 16,
                  borderBottomRightRadius: b.quien === "yo" ? 4 : 16,
                  borderBottomLeftRadius: b.quien === "yo" ? 16 : 4,
                  borderWidth: b.quien === "yo" ? 0 : 1,
                  borderColor: colores.borde,
                  paddingHorizontal: 14,
                  paddingVertical: 10,
                }}
              >
                <Text style={{ color: b.quien === "yo" ? "#fff" : colores.texto, fontSize: 15, lineHeight: 21 }}>{b.texto}</Text>
              </View>
              {b.acciones?.map((a, k) => (
                <View
                  key={k}
                  style={{ backgroundColor: a.simulada ? colores.avisoSuave : colores.infoSuave, borderRadius: radios.chico, paddingHorizontal: 10, paddingVertical: 6 }}
                >
                  <Text style={{ fontSize: 12, color: a.simulada ? colores.avisoTexto : colores.infoTexto, lineHeight: 16 }}>
                    🔧 {a.herramienta}
                    {a.simulada ? " (simulada)" : " (lee la agenda real)"} → {a.resultado}
                  </Text>
                </View>
              ))}
            </View>
          )
        )}
        {cargando ? <ActivityIndicator color={colores.marca} style={{ alignSelf: "flex-start", marginLeft: 8 }} /> : null}
        {error ? <Aviso texto={error} /> : null}
      </ScrollView>

      {fin ? (
        <View style={{ padding: 12 }}>
          <Pressable onPress={empezar} style={{ backgroundColor: colores.marca, borderRadius: radios.medio, paddingVertical: 14, alignItems: "center" }}>
            <Text style={{ color: "#fff", fontWeight: "700", fontSize: 15 }}>Probar de nuevo</Text>
          </Pressable>
        </View>
      ) : modo === "ivr" ? (
        <View style={{ padding: 12, gap: 8, backgroundColor: colores.superficie, borderTopWidth: 1, borderTopColor: colores.borde }}>
          {opciones.length ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
              {opciones.map((o) => (
                <Pressable
                  key={o.tecla}
                  onPress={() => marcar(o.tecla)}
                  disabled={cargando}
                  style={{ backgroundColor: colores.marcaSuave, borderRadius: 999, paddingVertical: 8, paddingHorizontal: 14 }}
                >
                  <Text style={{ color: colores.marcaTexto, fontWeight: "700" }}>
                    {o.tecla} · {o.etiqueta}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          ) : null}
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
            {TECLADO.map((t) => (
              <Pressable
                key={t}
                onPress={() => marcar(t)}
                disabled={cargando}
                style={{ width: "22%", paddingVertical: 10, borderRadius: radios.medio, backgroundColor: colores.superficie3, alignItems: "center" }}
              >
                <Text style={{ fontSize: 18, fontWeight: "600", color: colores.texto }}>{t}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : (
        <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8, padding: 12, backgroundColor: colores.superficie, borderTopWidth: 1, borderTopColor: colores.borde }}>
          <TextInput
            value={texto}
            onChangeText={setTexto}
            placeholder="Escribe lo que diría el cliente…"
            placeholderTextColor={colores.placeholder}
            selectionColor={colores.marca}
            multiline
            maxLength={600}
            style={{ flex: 1, maxHeight: 110, borderWidth: 1, borderColor: colores.bordeFuerte, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10, fontSize: 15, color: colores.texto }}
          />
          <Pressable
            onPress={escribir}
            disabled={!texto.trim() || cargando}
            style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: colores.marca, alignItems: "center", justifyContent: "center", opacity: !texto.trim() || cargando ? 0.4 : 1 }}
          >
            <Text style={{ color: "#fff", fontSize: 20 }}>➤</Text>
          </Pressable>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}
