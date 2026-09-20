import { useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { conversacionAsistente } from "@/src/datos";
import { Aviso } from "@/src/gestion";
import { fallo, impacto, toque } from "@/src/haptico";
import { colores, radios } from "@/src/tema";

// Pantallas de la app a las que el asistente puede mandar, con el permiso que pide cada una.
const DESTINOS: Record<string, { ruta: string; etiqueta: string; permiso: string | null }> = {
  "/": { ruta: "/", etiqueta: "Teléfono", permiso: null },
  "/softphone": { ruta: "/", etiqueta: "Teléfono", permiso: "softphone:usar" },
  "/calls": { ruta: "/llamadas", etiqueta: "Llamadas", permiso: "llamadas:ver_propias" },
  "/extensions": { ruta: "/administrar/extensiones", etiqueta: "Extensiones", permiso: "telefonia:gestionar" },
  "/trunks": { ruta: "/administrar/troncales", etiqueta: "Troncales", permiso: "telefonia:gestionar" },
  "/users": { ruta: "/administrar/usuarios", etiqueta: "Usuarios", permiso: "usuarios:gestionar" },
  "/voicebots": { ruta: "/administrar/bots", etiqueta: "Voizbots", permiso: "voizbots:ver" },
  "/settings": { ruta: "/settings", etiqueta: "Cuenta", permiso: null },
};

const SUGERENCIAS = ["¿Cómo van las llamadas?", "¿Cómo creo una extensión?", "¿Cómo activo las llamadas internacionales?", "¿Qué es una troncal?"];

function Texto({ texto, color }: { texto: string; color: string }) {
  const en = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
      p.startsWith("**") && p.endsWith("**") ? (
        <Text key={i} style={{ fontWeight: "700" }}>
          {p.slice(2, -2)}
        </Text>
      ) : (
        p
      )
    );
  return (
    <View style={{ gap: 4 }}>
      {texto.split("\n").filter((l) => l.trim()).map((l, i) => {
        const li = l.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)/);
        return (
          <Text key={i} style={{ color, fontSize: 15, lineHeight: 21 }}>
            {li ? "•  " : ""}
            {en(li ? li[1] : l)}
          </Text>
        );
      })}
    </View>
  );
}

export default function Asistente() {
  const router = useRouter();
  const { puede } = useAuth();
  const [mensajes, setMensajes] = useState(conversacionAsistente.lista);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);
  const scroll = useRef<ScrollView>(null);

  const guardar = (m: typeof mensajes) => {
    conversacionAsistente.lista = m;
    setMensajes(m);
  };

  const enviar = useCallback(
    async (contenido: string) => {
      const t = contenido.trim().slice(0, 2000);
      if (!t || pensando) return;
      impacto();
      const conUsuario = [...mensajes, { role: "user" as const, content: t }];
      guardar(conUsuario);
      setTexto("");
      setPensando(true);
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 80);
      try {
        const r = await peticion<{ reply: string }>("/api/assistant/chat", {
          method: "POST",
          body: { messages: conUsuario.filter((m) => !m.error).slice(-12).map(({ role, content }) => ({ role, content })) },
        });
        guardar([...conUsuario, { role: "assistant", content: r.reply }]);
      } catch (e) {
        fallo();
        guardar([...conUsuario, { role: "assistant", content: e instanceof ApiError ? e.message : "No se pudo conectar con el asistente.", error: true }]);
      } finally {
        setPensando(false);
        setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 80);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mensajes, pensando]
  );

  const partir = (contenido: string) => {
    const rutas: string[] = [];
    const limpio = contenido.replace(/\[\[ir:(\/[a-z-]*)\]\]/g, (_, r: string) => {
      const d = DESTINOS[r];
      if (d && (d.permiso === null || puede(d.permiso)) && !rutas.includes(r)) rutas.push(r);
      return "";
    });
    return { limpio: limpio.trim(), rutas };
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colores.fondo }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView ref={scroll} contentContainerStyle={{ padding: 16, gap: 12, flexGrow: 1 }} keyboardShouldPersistTaps="handled">
        {mensajes.length === 0 ? (
          <View style={{ alignItems: "center", gap: 10, paddingVertical: 28 }}>
            <Text style={{ fontSize: 44 }}>✨</Text>
            <Text style={{ fontSize: 18, fontWeight: "700", color: colores.texto }}>¿En qué te ayudo?</Text>
            <Text style={{ fontSize: 14, color: colores.textoSecundario, textAlign: "center", lineHeight: 20, paddingHorizontal: 20 }}>
              Te explico cómo usar la central y te cuento cómo van tus llamadas. Solo consulto: los cambios los haces tú.
            </Text>
            <View style={{ gap: 8, alignSelf: "stretch", marginTop: 8 }}>
              {SUGERENCIAS.map((s) => (
                <Pressable
                  key={s}
                  onPress={() => enviar(s)}
                  style={{ backgroundColor: colores.superficie, borderWidth: 1, borderColor: colores.borde, borderRadius: radios.medio, paddingVertical: 12, paddingHorizontal: 14 }}
                >
                  <Text style={{ color: colores.textoSuave, fontSize: 14.5 }}>{s}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {mensajes.map((m, i) => {
          const { limpio, rutas } = m.role === "assistant" ? partir(m.content) : { limpio: m.content, rutas: [] };
          const mio = m.role === "user";
          return (
            <View key={i} style={{ alignSelf: mio ? "flex-end" : "flex-start", maxWidth: "88%", gap: 8 }}>
              <View
                style={{
                  backgroundColor: mio ? colores.marca : m.error ? colores.peligroSuave : colores.superficie,
                  borderWidth: mio ? 0 : 1,
                  borderColor: colores.borde,
                  borderRadius: 18,
                  borderBottomRightRadius: mio ? 4 : 18,
                  borderBottomLeftRadius: mio ? 18 : 4,
                  paddingHorizontal: 14,
                  paddingVertical: 10,
                }}
              >
                {mio ? (
                  <Text style={{ color: "#fff", fontSize: 15, lineHeight: 21 }}>{limpio}</Text>
                ) : (
                  <Texto texto={limpio} color={m.error ? colores.peligroTexto : colores.textoSuave} />
                )}
              </View>
              {rutas.length ? (
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {rutas.map((r) => (
                    <Pressable
                      key={r}
                      onPress={() => {
                        toque();
                        router.dismiss();
                        router.navigate(DESTINOS[r].ruta as never);
                      }}
                      style={{ backgroundColor: colores.marcaSuave, borderRadius: 999, paddingVertical: 7, paddingHorizontal: 14 }}
                    >
                      <Text style={{ color: colores.marcaTexto, fontWeight: "700", fontSize: 13 }}>Abrir {DESTINOS[r].etiqueta} →</Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </View>
          );
        })}
        {pensando ? <ActivityIndicator color={colores.marca} style={{ alignSelf: "flex-start", marginLeft: 8 }} /> : null}
        {mensajes.length > 0 ? (
          <Pressable onPress={() => guardar([])} style={{ alignSelf: "center", padding: 8 }}>
            <Text style={{ fontSize: 12, color: colores.textoSecundario }}>Empezar una conversación nueva</Text>
          </Pressable>
        ) : null}
        {mensajes.some((m) => m.error) ? <Aviso tono="aviso" texto="Si el asistente no responde, un administrador debe configurar el modelo de IA en Ajustes del panel web." /> : null}
      </ScrollView>

      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8, padding: 12, backgroundColor: colores.superficie, borderTopWidth: 1, borderTopColor: colores.borde }}>
        <TextInput
          value={texto}
          onChangeText={setTexto}
          placeholder="Escribe tu pregunta…"
          placeholderTextColor={colores.placeholder}
          selectionColor={colores.marca}
          multiline
          maxLength={2000}
          style={{ flex: 1, maxHeight: 110, borderWidth: 1, borderColor: colores.bordeFuerte, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10, fontSize: 15, color: colores.texto }}
        />
        <Pressable
          onPress={() => enviar(texto)}
          disabled={!texto.trim() || pensando}
          style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: colores.marca, alignItems: "center", justifyContent: "center", opacity: !texto.trim() || pensando ? 0.4 : 1 }}
        >
          <Text style={{ color: "#fff", fontSize: 20 }}>➤</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}
