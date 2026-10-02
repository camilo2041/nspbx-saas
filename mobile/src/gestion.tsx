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

import { SelectorFecha } from "@/src/fecha";
import { exito, fallo, toque } from "@/src/haptico";
import { Icono, NombreIcono } from "@/src/Icono";
import { radios, useColores } from "@/src/tema";
import { Boton, CajaIcono, Tarjeta } from "@/src/ui";

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
  const c = useColores();
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
      style={[{ height: alto, width: ancho ?? "100%", borderRadius: 8, backgroundColor: c.superficie3, opacity: op }, style]}
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
  icono: NombreIcono;
  titulo: string;
  texto?: string;
  accion?: ReactNode;
}) {
  const c = useColores();
  return (
    <View style={{ alignItems: "center", paddingVertical: 48, paddingHorizontal: 24, gap: 8 }}>
      <CajaIcono icono={icono} tono="neutro" tam={64} />
      <Text style={{ fontSize: 17, fontWeight: "700", color: c.texto, textAlign: "center" }}>{titulo}</Text>
      {texto ? (
        <Text style={{ fontSize: 14, color: c.textoSecundario, textAlign: "center", lineHeight: 20 }}>{texto}</Text>
      ) : null}
      {accion ? <View style={{ marginTop: 8 }}>{accion}</View> : null}
    </View>
  );
}

/** Aviso fijo cuando se muestran datos guardados por no haber red. */
export function AvisoSinConexion() {
  return <Aviso tono="aviso" texto="Sin conexión: se muestran los últimos datos guardados." />;
}

export function Aviso({ texto, tono = "peligro" }: { texto: string; tono?: "peligro" | "ok" | "aviso" | "info" }) {
  const c = useColores();
  const paleta = {
    peligro: [c.peligroSuave, c.peligroTexto],
    ok: [c.okSuave, c.okTexto],
    aviso: [c.avisoSuave, c.avisoTexto],
    info: [c.infoSuave, c.infoTexto],
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
  const c = useColores();
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
              backgroundColor: activo ? c.marca : c.superficie,
              borderWidth: 1,
              borderColor: activo ? c.marca : c.borde,
            }}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: activo ? c.sobreMarca : c.textoSuave }}>{o.etiqueta}</Text>
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
  const c = useColores();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        backgroundColor: c.superficie,
        borderRadius: radios.medio,
        borderWidth: 1,
        borderColor: c.borde,
        paddingHorizontal: 12,
      }}
    >
      <Icono nombre="buscar" tam={18} color={c.textoSecundario} style={{ marginRight: 8 }} />
      <TextInput
        value={valor}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={c.placeholder}
        selectionColor={c.marca}
        autoCorrect={false}
        autoCapitalize="none"
        style={{ flex: 1, paddingVertical: 11, fontSize: 15, color: c.texto }}
      />
      {valor ? (
        <Pressable onPress={() => onChange("")} hitSlop={10} accessibilityLabel="Borrar la búsqueda">
          <Icono nombre="cerrar" tam={18} color={c.textoSecundario} />
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
  const c = useColores();
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      style={({ pressed }) => [
        {
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          backgroundColor: c.superficie,
          borderRadius: radios.medio,
          borderWidth: 1,
          borderColor: c.borde,
          paddingVertical: 12,
          paddingHorizontal: 14,
        },
        pressed && { backgroundColor: c.superficie2 },
      ]}
    >
      {izquierda}
      <View style={{ flex: 1 }}>
        <Text numberOfLines={1} style={{ fontSize: 15, fontWeight: "600", color: c.texto }}>
          {titulo}
        </Text>
        {subtitulo ? (
          <Text numberOfLines={1} style={{ fontSize: 12.5, color: c.textoSecundario, marginTop: 2 }}>
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
  const c = useColores();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: 14.5, fontWeight: "600", color: c.texto }}>{titulo}</Text>
        {ayuda ? (
          <Text style={{ fontSize: 12, color: c.textoSecundario, marginTop: 2, lineHeight: 16 }}>{ayuda}</Text>
        ) : null}
      </View>
      <Switch
        value={valor}
        onValueChange={(v) => {
          toque();
          onChange(v);
        }}
        trackColor={{ true: c.marca, false: c.bordeFuerte }}
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
  const c = useColores();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: c.fondo }}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 120 }}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefrescar ? (
          <RefreshControl refreshing={!!refrescando} onRefresh={onRefrescar} tintColor={c.marca} colors={[c.marca]} />
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
  const c = useColores();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCerrar} statusBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end" }}>
        <Pressable onPress={onCerrar} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: c.velo }} />
        <View style={{ backgroundColor: c.superficie, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: "90%", paddingTop: 8 }}>
          <View style={{ alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: c.bordeFuerte, marginBottom: 8 }} />
          <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 20, paddingBottom: 8 }}>
            <Text style={{ flex: 1, fontSize: 18, fontWeight: "700", color: c.texto }}>{titulo}</Text>
            <Pressable onPress={onCerrar} hitSlop={12} accessibilityLabel="Cerrar">
              <Icono nombre="cerrar" tam={22} color={c.textoSecundario} />
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
  tipo?: "texto" | "numero" | "secreto" | "conmutador" | "opciones" | "email" | "fecha" | "fechaHora" | "multilinea" | "telefono" | "multiples" | "decimal";
  /** "multiples": muestra el número de orden de cada elegida (el orden importa). */
  conOrden?: boolean;
  /** Fecha que se puede dejar vacía. */
  opcional?: boolean;
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
  extra,
}: {
  visible: boolean;
  titulo: string;
  campos: CampoDef[];
  /** Algo que se calcula en vivo con lo escrito (una vista previa, un aviso). */
  extra?: (valores: Record<string, unknown>) => ReactNode;
  inicial: Record<string, unknown>;
  textoGuardar?: string;
  onGuardar: (valores: Record<string, unknown>) => Promise<void>;
  onCerrar: () => void;
  onEliminar?: () => void;
}) {
  const c = useColores();
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
          .filter((campo) => !campo.visibleSi || campo.visibleSi(valores))
          .map((campo) => {
            const v = valores[campo.clave];
            if (campo.tipo === "conmutador") {
              return <FilaSwitch key={campo.clave} titulo={campo.etiqueta} ayuda={campo.ayuda} valor={!!v} onChange={(x) => poner(campo.clave, x)} />;
            }
            if (campo.tipo === "opciones") {
              return (
                <View key={campo.clave} style={{ gap: 8 }}>
                  <Text style={{ fontSize: 12, fontWeight: "600", color: c.textoSuave }}>{campo.etiqueta}</Text>
                  {campo.opciones?.map((o) => {
                    const activo = v === o.valor;
                    return (
                      <Pressable
                        key={o.valor}
                        onPress={() => {
                          toque();
                          poner(campo.clave, o.valor);
                        }}
                        style={{
                          borderWidth: 1.5,
                          borderColor: activo ? c.marca : c.borde,
                          backgroundColor: activo ? c.marcaSuave : c.superficie,
                          borderRadius: radios.medio,
                          padding: 12,
                        }}
                      >
                        <Text style={{ fontWeight: "600", color: activo ? c.marcaTexto : c.texto }}>{o.etiqueta}</Text>
                        {o.detalle ? (
                          <Text style={{ fontSize: 12, color: c.textoSecundario, marginTop: 2, lineHeight: 16 }}>{o.detalle}</Text>
                        ) : null}
                      </Pressable>
                    );
                  })}
                  {campo.ayuda ? <Text style={{ fontSize: 12, color: c.textoSecundario }}>{campo.ayuda}</Text> : null}
                </View>
              );
            }
            if (campo.tipo === "multiples") {
              // Valor: lista separada por comas, en el orden en que se marcaron.
              const elegidas = String(v ?? "").split(",").filter(Boolean);
              return (
                <View key={campo.clave} style={{ gap: 8 }}>
                  <Text style={{ fontSize: 12, fontWeight: "600", color: c.textoSuave }}>{campo.etiqueta}</Text>
                  {campo.opciones?.length ? null : (
                    <Text style={{ fontSize: 13, color: c.textoSecundario }}>No hay opciones para elegir todavía.</Text>
                  )}
                  {campo.opciones?.map((o) => {
                    const pos = elegidas.indexOf(o.valor);
                    const activo = pos >= 0;
                    return (
                      <Pressable
                        key={o.valor}
                        accessibilityRole="checkbox"
                        accessibilityState={{ checked: activo }}
                        onPress={() => {
                          toque();
                          poner(campo.clave, (activo ? elegidas.filter((x) => x !== o.valor) : [...elegidas, o.valor]).join(","));
                        }}
                        style={{
                          flexDirection: "row",
                          alignItems: "center",
                          gap: 10,
                          borderWidth: 1.5,
                          borderColor: activo ? c.marca : c.borde,
                          backgroundColor: activo ? c.marcaSuave : c.superficie,
                          borderRadius: radios.medio,
                          padding: 12,
                        }}
                      >
                        <Icono nombre={activo ? "ok" : "noMarcado"} tam={20} color={activo ? c.marca : c.placeholder} />
                        <View style={{ flex: 1 }}>
                          <Text style={{ fontWeight: "600", color: activo ? c.marcaTexto : c.texto }}>{o.etiqueta}</Text>
                          {o.detalle ? <Text style={{ fontSize: 12, color: c.textoSecundario, marginTop: 2 }}>{o.detalle}</Text> : null}
                        </View>
                        {activo && campo.conOrden ? (
                          <Text style={{ fontSize: 12, fontWeight: "800", color: c.marcaTexto }}>#{pos + 1}</Text>
                        ) : null}
                      </Pressable>
                    );
                  })}
                  {campo.ayuda ? <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>{campo.ayuda}</Text> : null}
                </View>
              );
            }
            if (campo.tipo === "fecha" || campo.tipo === "fechaHora") {
              return (
                <SelectorFecha
                  key={campo.clave}
                  etiqueta={campo.etiqueta}
                  valor={v ? String(v) : ""}
                  conHora={campo.tipo === "fechaHora"}
                  opcional={campo.opcional}
                  ayuda={campo.ayuda}
                  onChange={(x) => poner(campo.clave, x)}
                />
              );
            }
            const secreto = campo.tipo === "secreto";
            const multilinea = campo.tipo === "multilinea";
            return (
              <View key={campo.clave} style={{ gap: 6 }}>
                <Text style={{ fontSize: 12, fontWeight: "600", color: c.textoSuave }}>{campo.etiqueta}</Text>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <TextInput
                    value={v === null || v === undefined ? "" : String(v)}
                    onChangeText={(t) => poner(campo.clave, t)}
                    placeholder={campo.placeholder}
                    placeholderTextColor={c.placeholder}
                    selectionColor={c.marca}
                    secureTextEntry={secreto && !mostrar[campo.clave]}
                    keyboardType={
                      campo.tipo === "numero" ? "number-pad" : campo.tipo === "decimal" ? "decimal-pad" : campo.tipo === "email" ? "email-address" : campo.tipo === "telefono" ? "phone-pad" : "default"
                    }
                    multiline={multilinea}
                    textAlignVertical={multilinea ? "top" : undefined}
                    autoCapitalize={multilinea ? "sentences" : "none"}
                    autoCorrect={false}
                    style={{
                      flex: 1,
                      borderWidth: 1,
                      borderColor: c.bordeFuerte,
                      borderRadius: radios.medio,
                      paddingHorizontal: 14,
                      paddingVertical: 12,
                      fontSize: 16,
                      color: c.texto,
                      backgroundColor: c.superficie,
                      minHeight: multilinea ? 96 : undefined,
                    }}
                  />
                  {secreto ? (
                    <Pressable
                      onPress={() => setMostrar((m) => ({ ...m, [campo.clave]: !m[campo.clave] }))}
                      style={{ justifyContent: "center", paddingHorizontal: 10 }}
                    >
                      <Icono nombre={mostrar[campo.clave] ? "ocultar" : "ver"} tam={20} color={c.textoSecundario} />
                    </Pressable>
                  ) : null}
                  {campo.generar ? (
                    <Pressable
                      onPress={() => {
                        toque();
                        poner(campo.clave, claveSegura());
                        setMostrar((m) => ({ ...m, [campo.clave]: true }));
                      }}
                      style={{ justifyContent: "center", paddingHorizontal: 12, borderRadius: radios.medio, backgroundColor: c.superficie3 }}
                    >
                      <Text style={{ fontSize: 12, fontWeight: "700", color: c.textoSuave }}>Generar</Text>
                    </Pressable>
                  ) : null}
                </View>
                {campo.ayuda ? <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>{campo.ayuda}</Text> : null}
              </View>
            );
          })}
        {extra ? extra(valores) : null}
        {error ? <Aviso texto={error} /> : null}
        <Boton titulo={textoGuardar} onPress={guardar} cargando={guardando} />
        {onEliminar ? <Boton titulo="Eliminar" variante="suave" onPress={onEliminar} /> : null}
      </ScrollView>
    </Hoja>
  );
}
