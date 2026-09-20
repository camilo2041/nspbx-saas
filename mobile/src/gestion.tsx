/**
 * Componentes de las pantallas de gestión (listas, filtros, hojas y formularios).
 * Comparten el aspecto de src/ui.tsx.
 */
import { ReactNode, useEffect, useRef, useState } from "react";
import {
  Animated,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleProp,
  Switch,
  Text,
  TextInput,
  View,
  ViewStyle,
} from "react-native";

import { exito, fallo, toque } from "@/src/haptico";
import { colores, radios } from "@/src/tema";
import { Boton, Tarjeta } from "@/src/ui";

/** Bloque gris que pulsa mientras carga: se ve la forma de la pantalla y no un círculo girando. */
export function Esqueleto({
  alto = 16,
  ancho,
  style,
}: {
  alto?: number;
  ancho?: number | `${number}%`;
  style?: StyleProp<ViewStyle>;
}) {
  const op = useRef(new Animated.Value(0.45)).current;
  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(op, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(op, { toValue: 0.45, duration: 700, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [op]);
  return (
    <Animated.View
      style={[{ height: alto, width: ancho ?? "100%", borderRadius: 8, backgroundColor: colores.superficie3, opacity: op }, style]}
    />
  );
}

export function ListaEsqueleto({ filas = 5 }: { filas?: number }) {
  return (
    <View style={{ gap: 10 }}>
      {Array.from({ length: filas }).map((_, i) => (
        <Tarjeta key={i} style={{ flexDirection: "row", alignItems: "center", gap: 12, padding: 14 }}>
          <Esqueleto alto={40} ancho={40} style={{ borderRadius: 20 }} />
          <View style={{ flex: 1, gap: 8 }}>
            <Esqueleto alto={14} ancho="60%" />
            <Esqueleto alto={11} ancho="35%" />
          </View>
        </Tarjeta>
      ))}
    </View>
  );
}

export function EstadoVacio({
  icono,
  titulo,
  texto,
  accion,
}: {
  icono: string;
  titulo: string;
  texto?: string;
  accion?: ReactNode;
}) {
  return (
    <View style={{ alignItems: "center", paddingVertical: 48, paddingHorizontal: 24, gap: 8 }}>
      <Text style={{ fontSize: 40 }}>{icono}</Text>
      <Text style={{ fontSize: 17, fontWeight: "700", color: colores.texto, textAlign: "center" }}>{titulo}</Text>
      {texto ? (
        <Text style={{ fontSize: 14, color: colores.textoSecundario, textAlign: "center", lineHeight: 20 }}>{texto}</Text>
      ) : null}
      {accion ? <View style={{ marginTop: 8 }}>{accion}</View> : null}
    </View>
  );
}

/** Aviso fijo cuando se muestran datos guardados por no haber red. */
export function AvisoSinConexion() {
  return <Aviso tono="aviso" texto="Sin conexión: se muestran los últimos datos guardados." />;
}

export function Aviso({ texto, tono = "peligro" }: { texto: string; tono?: "peligro" | "ok" | "aviso" }) {
  const paleta = {
    peligro: [colores.peligroSuave, colores.peligroTexto],
    ok: [colores.okSuave, colores.okTexto],
    aviso: [colores.avisoSuave, colores.avisoTexto],
  }[tono];
  return (
    <View style={{ backgroundColor: paleta[0], borderRadius: radios.medio, padding: 12 }}>
      <Text style={{ color: paleta[1], fontSize: 13, lineHeight: 18 }}>{texto}</Text>
    </View>
  );
}

const PALETA_AVATAR = ["#ea580c", "#0284c7", "#059669", "#7c3aed", "#db2777", "#0d9488", "#d97706"];

export function Avatar({ nombre, tam = 40 }: { nombre: string; tam?: number }) {
  const limpio = (nombre || "?").trim();
  const partes = limpio.split(/\s+/);
  const iniciales = ((partes[0]?.[0] ?? "?") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
  let h = 0;
  for (const c of limpio) h = (h * 31 + c.charCodeAt(0)) % 997;
  const color = PALETA_AVATAR[h % PALETA_AVATAR.length];
  return (
    <View
      style={{ width: tam, height: tam, borderRadius: tam / 2, backgroundColor: color + "22", alignItems: "center", justifyContent: "center" }}
    >
      <Text style={{ color, fontWeight: "700", fontSize: tam * 0.38 }}>{iniciales}</Text>
    </View>
  );
}

export function FiltroChips<T extends string>({
  opciones,
  valor,
  onChange,
}: {
  opciones: { valor: T; etiqueta: string }[];
  valor: T;
  onChange: (v: T) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingRight: 8 }}>
      {opciones.map((o) => {
        const activo = o.valor === valor;
        return (
          <Pressable
            key={o.valor}
            onPress={() => {
              toque();
              onChange(o.valor);
            }}
            style={{
              paddingHorizontal: 14,
              paddingVertical: 8,
              borderRadius: 999,
              backgroundColor: activo ? colores.marca : colores.superficie,
              borderWidth: 1,
              borderColor: activo ? colores.marca : colores.borde,
            }}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: activo ? "#fff" : colores.textoSuave }}>{o.etiqueta}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export function Buscador({
  valor,
  onChange,
  placeholder = "Buscar",
}: {
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        backgroundColor: colores.superficie,
        borderRadius: radios.medio,
        borderWidth: 1,
        borderColor: colores.borde,
        paddingHorizontal: 12,
      }}
    >
      <Text style={{ fontSize: 16, marginRight: 8 }}>🔍</Text>
      <TextInput
        value={valor}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colores.placeholder}
        selectionColor={colores.marca}
        autoCorrect={false}
        autoCapitalize="none"
        style={{ flex: 1, paddingVertical: 11, fontSize: 15, color: colores.texto }}
      />
      {valor ? (
        <Pressable onPress={() => onChange("")} hitSlop={10}>
          <Text style={{ fontSize: 16, color: colores.textoSecundario }}>✕</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** Fila de lista tocable: avatar, título, subtítulo y algo a la derecha. */
export function Fila({
  titulo,
  subtitulo,
  izquierda,
  derecha,
  onPress,
  onLongPress,
}: {
  titulo: string;
  subtitulo?: string;
  izquierda?: ReactNode;
  derecha?: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      style={({ pressed }) => [
        {
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          backgroundColor: colores.superficie,
          borderRadius: radios.medio,
          borderWidth: 1,
          borderColor: colores.borde,
          paddingVertical: 12,
          paddingHorizontal: 14,
        },
        pressed && { backgroundColor: colores.superficie2 },
      ]}
    >
      {izquierda}
      <View style={{ flex: 1 }}>
        <Text numberOfLines={1} style={{ fontSize: 15, fontWeight: "600", color: colores.texto }}>
          {titulo}
        </Text>
        {subtitulo ? (
          <Text numberOfLines={1} style={{ fontSize: 12.5, color: colores.textoSecundario, marginTop: 2 }}>
            {subtitulo}
          </Text>
        ) : null}
      </View>
      {derecha}
    </Pressable>
  );
}

export function FilaSwitch({
  titulo,
  ayuda,
  valor,
  onChange,
}: {
  titulo: string;
  ayuda?: string;
  valor: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: 14.5, fontWeight: "600", color: colores.texto }}>{titulo}</Text>
        {ayuda ? (
          <Text style={{ fontSize: 12, color: colores.textoSecundario, marginTop: 2, lineHeight: 16 }}>{ayuda}</Text>
        ) : null}
      </View>
      <Switch
        value={valor}
        onValueChange={(v) => {
          toque();
          onChange(v);
        }}
        trackColor={{ true: colores.marca, false: colores.bordeFuerte }}
        thumbColor="#fff"
      />
    </View>
  );
}

/** Contenedor de pantalla con desplazamiento, margen y arrastrar para actualizar. */
export function Pantalla({
  children,
  refrescando,
  onRefrescar,
}: {
  children: ReactNode;
  refrescando?: boolean;
  onRefrescar?: () => void;
}) {
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colores.fondo }}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 120 }}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefrescar ? (
          <RefreshControl refreshing={!!refrescando} onRefresh={onRefrescar} tintColor={colores.marca} colors={[colores.marca]} />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );
}

/** Hoja que sube desde abajo (formularios, detalles, selectores). */
export function Hoja({
  visible,
  titulo,
  onCerrar,
  children,
}: {
  visible: boolean;
  titulo: string;
  onCerrar: () => void;
  children: ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCerrar} statusBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end" }}>
        <Pressable onPress={onCerrar} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(15,23,42,0.5)" }} />
        <View style={{ backgroundColor: colores.superficie, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: "90%", paddingTop: 8 }}>
          <View style={{ alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colores.bordeFuerte, marginBottom: 8 }} />
          <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 20, paddingBottom: 8 }}>
            <Text style={{ flex: 1, fontSize: 18, fontWeight: "700", color: colores.texto }}>{titulo}</Text>
            <Pressable onPress={onCerrar} hitSlop={12}>
              <Text style={{ fontSize: 20, color: colores.textoSecundario }}>✕</Text>
            </Pressable>
          </View>
          {children}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export interface CampoDef {
  clave: string;
  etiqueta: string;
  tipo?: "texto" | "numero" | "secreto" | "conmutador" | "opciones" | "email";
  ayuda?: string;
  opciones?: { valor: string; etiqueta: string; detalle?: string }[];
  /** Solo se muestra si devuelve true (según lo ya escrito). */
  visibleSi?: (v: Record<string, unknown>) => boolean;
  placeholder?: string;
  /** Botón "Generar" que rellena una clave segura. */
  generar?: boolean;
}

function claveSegura(largo = 14): string {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  let s = "";
  for (let i = 0; i < largo; i++) s += abc[Math.floor(Math.random() * abc.length)];
  return s;
}

/**
 * Formulario en una hoja. `onGuardar` lanza el motivo del error: el mensaje del
 * servidor se muestra tal cual, arriba del botón, y la hoja no se cierra.
 */
export function HojaFormulario({
  visible,
  titulo,
  campos,
  inicial,
  textoGuardar = "Guardar",
  onGuardar,
  onCerrar,
  onEliminar,
}: {
  visible: boolean;
  titulo: string;
  campos: CampoDef[];
  inicial: Record<string, unknown>;
  textoGuardar?: string;
  onGuardar: (valores: Record<string, unknown>) => Promise<void>;
  onCerrar: () => void;
  onEliminar?: () => void;
}) {
  const [valores, setValores] = useState<Record<string, unknown>>(inicial);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [mostrar, setMostrar] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (visible) {
      setValores(inicial);
      setError("");
      setMostrar({});
    }
    // solo al abrir: `inicial` cambia de identidad en cada render del padre
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const poner = (k: string, v: unknown) => setValores((a) => ({ ...a, [k]: v }));

  const guardar = async () => {
    setError("");
    setGuardando(true);
    try {
      await onGuardar(valores);
      exito();
    } catch (e) {
      fallo();
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Hoja visible={visible} titulo={titulo} onCerrar={onCerrar}>
      <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 8, gap: 16 }} keyboardShouldPersistTaps="handled">
        {campos
          .filter((c) => !c.visibleSi || c.visibleSi(valores))
          .map((c) => {
            const v = valores[c.clave];
            if (c.tipo === "conmutador") {
              return <FilaSwitch key={c.clave} titulo={c.etiqueta} ayuda={c.ayuda} valor={!!v} onChange={(x) => poner(c.clave, x)} />;
            }
            if (c.tipo === "opciones") {
              return (
                <View key={c.clave} style={{ gap: 8 }}>
                  <Text style={{ fontSize: 12, fontWeight: "600", color: colores.textoSuave }}>{c.etiqueta}</Text>
                  {c.opciones?.map((o) => {
                    const activo = v === o.valor;
                    return (
                      <Pressable
                        key={o.valor}
                        onPress={() => {
                          toque();
                          poner(c.clave, o.valor);
                        }}
                        style={{
                          borderWidth: 1.5,
                          borderColor: activo ? colores.marca : colores.borde,
                          backgroundColor: activo ? colores.marcaSuave : colores.superficie,
                          borderRadius: radios.medio,
                          padding: 12,
                        }}
                      >
                        <Text style={{ fontWeight: "600", color: activo ? colores.marcaTexto : colores.texto }}>{o.etiqueta}</Text>
                        {o.detalle ? (
                          <Text style={{ fontSize: 12, color: colores.textoSecundario, marginTop: 2, lineHeight: 16 }}>{o.detalle}</Text>
                        ) : null}
                      </Pressable>
                    );
                  })}
                  {c.ayuda ? <Text style={{ fontSize: 12, color: colores.textoSecundario }}>{c.ayuda}</Text> : null}
                </View>
              );
            }
            const secreto = c.tipo === "secreto";
            return (
              <View key={c.clave} style={{ gap: 6 }}>
                <Text style={{ fontSize: 12, fontWeight: "600", color: colores.textoSuave }}>{c.etiqueta}</Text>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <TextInput
                    value={v === null || v === undefined ? "" : String(v)}
                    onChangeText={(t) => poner(c.clave, t)}
                    placeholder={c.placeholder}
                    placeholderTextColor={colores.placeholder}
                    selectionColor={colores.marca}
                    secureTextEntry={secreto && !mostrar[c.clave]}
                    keyboardType={c.tipo === "numero" ? "number-pad" : c.tipo === "email" ? "email-address" : "default"}
                    autoCapitalize="none"
                    autoCorrect={false}
                    style={{
                      flex: 1,
                      borderWidth: 1,
                      borderColor: colores.bordeFuerte,
                      borderRadius: radios.medio,
                      paddingHorizontal: 14,
                      paddingVertical: 12,
                      fontSize: 16,
                      color: colores.texto,
                      backgroundColor: colores.superficie,
                    }}
                  />
                  {secreto ? (
                    <Pressable
                      onPress={() => setMostrar((m) => ({ ...m, [c.clave]: !m[c.clave] }))}
                      style={{ justifyContent: "center", paddingHorizontal: 10 }}
                    >
                      <Text style={{ fontSize: 18 }}>{mostrar[c.clave] ? "🙈" : "👁"}</Text>
                    </Pressable>
                  ) : null}
                  {c.generar ? (
                    <Pressable
                      onPress={() => {
                        toque();
                        poner(c.clave, claveSegura());
                        setMostrar((m) => ({ ...m, [c.clave]: true }));
                      }}
                      style={{ justifyContent: "center", paddingHorizontal: 12, borderRadius: radios.medio, backgroundColor: colores.superficie3 }}
                    >
                      <Text style={{ fontSize: 12, fontWeight: "700", color: colores.textoSuave }}>Generar</Text>
                    </Pressable>
                  ) : null}
                </View>
                {c.ayuda ? <Text style={{ fontSize: 12, color: colores.textoSecundario, lineHeight: 16 }}>{c.ayuda}</Text> : null}
              </View>
            );
          })}
        {error ? <Aviso texto={error} /> : null}
        <Boton titulo={textoGuardar} onPress={guardar} cargando={guardando} />
        {onEliminar ? <Boton titulo="Eliminar" variante="suave" onPress={onEliminar} /> : null}
      </ScrollView>
    </Hoja>
  );
}
