import { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";

import { colores, radios, sombra } from "@/src/tema";

/** Tarjeta blanca con borde fino, como las del panel web. */
export function Tarjeta({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[estilos.tarjeta, style]}>{children}</View>;
}

/** Logo cuadrado de marca, igual al de la pantalla de acceso del panel. */
export function Logo({ tam = 56 }: { tam?: number }) {
  return (
    <View style={[estilos.logo, { width: tam, height: tam, borderRadius: tam * 0.28 }]}>
      <Text style={[estilos.logoTexto, { fontSize: tam * 0.36 }]}>NS</Text>
    </View>
  );
}

type Variante = "marca" | "ok" | "peligro" | "suave";

const FONDO_BOTON: Record<Variante, string> = {
  marca: colores.marca,
  ok: colores.ok,
  peligro: colores.peligro,
  suave: colores.superficie3,
};

export function Boton({
  titulo,
  onPress,
  variante = "marca",
  cargando,
  deshabilitado,
  style,
}: {
  titulo: string;
  onPress: () => void;
  variante?: Variante;
  cargando?: boolean;
  deshabilitado?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const apagado = deshabilitado || cargando;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={apagado}
      style={({ pressed }) => [
        estilos.boton,
        { backgroundColor: FONDO_BOTON[variante] },
        variante === "marca" && !apagado && sombra,
        apagado && { opacity: 0.5 },
        pressed && { transform: [{ scale: 0.98 }], opacity: 0.9 },
        style,
      ]}
    >
      {cargando ? (
        <ActivityIndicator color={variante === "suave" ? colores.texto : "#fff"} />
      ) : (
        <Text style={[estilos.botonTexto, variante === "suave" && { color: colores.texto }]}>{titulo}</Text>
      )}
    </Pressable>
  );
}

/** Campo con etiqueta fija arriba (no depende del placeholder para explicarse). */
export function Campo({ etiqueta, ...props }: { etiqueta: string } & TextInputProps) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={estilos.etiqueta}>{etiqueta}</Text>
      <TextInput
        placeholderTextColor={colores.placeholder}
        selectionColor={colores.marca}
        style={estilos.campo}
        {...props}
      />
    </View>
  );
}

/** Pastilla de estado con punto de color. */
export function Pildora({ texto, tono }: { texto: string; tono: "ok" | "aviso" | "peligro" | "neutro" }) {
  const paleta = {
    ok: [colores.okSuave, colores.okTexto, colores.ok],
    aviso: [colores.avisoSuave, colores.avisoTexto, colores.aviso],
    peligro: [colores.peligroSuave, colores.peligroTexto, colores.peligro],
    neutro: [colores.superficie3, colores.textoSuave, colores.textoSecundario],
  }[tono];
  return (
    <View style={[estilos.pildora, { backgroundColor: paleta[0] }]}>
      <View style={[estilos.punto, { backgroundColor: paleta[2] }]} />
      <Text style={[estilos.pildoraTexto, { color: paleta[1] }]}>{texto}</Text>
    </View>
  );
}

const estilos = StyleSheet.create({
  tarjeta: {
    backgroundColor: colores.superficie,
    borderRadius: radios.grande,
    borderWidth: 1,
    borderColor: colores.borde,
    padding: 16,
    ...sombra,
  },
  logo: { backgroundColor: colores.marca, alignItems: "center", justifyContent: "center", ...sombra },
  logoTexto: { color: colores.sobreMarca, fontWeight: "800", letterSpacing: 0.5 },
  boton: {
    borderRadius: radios.medio,
    paddingVertical: 14,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  botonTexto: { color: "#fff", fontSize: 16, fontWeight: "600" },
  etiqueta: { fontSize: 12, fontWeight: "600", color: colores.textoSuave },
  campo: {
    borderWidth: 1,
    borderColor: colores.bordeFuerte,
    borderRadius: radios.medio,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colores.texto,
    backgroundColor: colores.superficie,
  },
  pildora: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
  },
  punto: { width: 7, height: 7, borderRadius: 4 },
  pildoraTexto: { fontSize: 12, fontWeight: "600" },
});
