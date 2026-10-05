/**
 * Componentes base de la app, con el mismo lenguaje visual del panel web:
 * tarjetas con borde fino, azul de marca (NSIT) para la acción principal, tonos
 * semánticos (ok, aviso, peligro, info) con su fondo suave.
 *
 * Todo toma los colores del tema activo (claro u oscuro).
 */
import { ReactNode, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  Text,
  TextInput,
  TextInputProps,
  TextStyle,
  View,
  ViewStyle,
} from "react-native";

import { Icono, NombreIcono } from "@/src/Icono";
import { toque } from "@/src/haptico";
import { crearEstilos, Paleta, radios, sombraDe, useColores, useTema } from "@/src/tema";

export type Tono = "marca" | "ok" | "aviso" | "peligro" | "info" | "neutro";

/** [fondo suave, texto, color pleno] de cada tono. */
export function colorDeTono(c: Paleta, tono: Tono): [string, string, string] {
  switch (tono) {
    case "marca":
      return [c.marcaSuave, c.marcaTexto, c.marca];
    case "ok":
      return [c.okSuave, c.okTexto, c.ok];
    case "aviso":
      return [c.avisoSuave, c.avisoTexto, c.aviso];
    case "peligro":
      return [c.peligroSuave, c.peligroTexto, c.peligro];
    case "info":
      return [c.infoSuave, c.infoTexto, c.info];
    default:
      return [c.superficie3, c.textoSuave, c.textoSecundario];
  }
}

/** Tarjeta con borde fino, como las del panel web. Con `onPress` es tocable. */
export function Tarjeta({
  children,
  style,
  onPress,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
}) {
  const e = useEstilos();
  if (!onPress) return <View style={[e.tarjeta, style]}>{children}</View>;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [e.tarjeta, pressed && e.presionada, style]}>
      {children}
    </Pressable>
  );
}

/** Logo cuadrado de marca, igual al de la pantalla de acceso del panel. */
export function Logo({ tam = 56 }: { tam?: number }) {
  const e = useEstilos();
  return (
    <View style={[e.logo, { width: tam, height: tam, borderRadius: tam * 0.28 }]}>
      <Text style={[e.logoTexto, { fontSize: tam * 0.36 }]}>NS</Text>
    </View>
  );
}

export type VarianteBoton = "marca" | "ok" | "peligro" | "suave" | "contorno" | "texto";

export function Boton({
  titulo,
  onPress,
  variante = "marca",
  icono,
  chico,
  cargando,
  deshabilitado,
  style,
}: {
  titulo: string;
  onPress: () => void;
  variante?: VarianteBoton;
  icono?: NombreIcono;
  chico?: boolean;
  cargando?: boolean;
  deshabilitado?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const c = useColores();
  const e = useEstilos();
  const apagado = deshabilitado || cargando;
  const [fondo, colorTexto, borde] = {
    marca: [c.marca, c.sobreMarca, c.marca],
    ok: [c.ok, c.sobreColor, c.ok],
    peligro: [c.peligro, c.sobreColor, c.peligro],
    suave: [c.superficie3, c.texto, c.superficie3],
    contorno: [c.superficie, c.texto, c.bordeFuerte],
    texto: ["transparent", c.marcaTexto, "transparent"],
  }[variante];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!apagado, busy: !!cargando }}
      onPress={onPress}
      disabled={apagado}
      style={({ pressed }) => [
        e.boton,
        chico && e.botonChico,
        { backgroundColor: fondo, borderColor: borde },
        variante === "marca" && !apagado && sombraDe(c, 2),
        apagado && { opacity: 0.5 },
        pressed && { transform: [{ scale: 0.98 }], opacity: 0.88 },
        style,
      ]}
    >
      {cargando ? (
        <ActivityIndicator color={colorTexto} />
      ) : (
        <>
          {icono ? <Icono nombre={icono} tam={chico ? 16 : 19} color={colorTexto} /> : null}
          <Text style={[e.botonTexto, chico && e.botonTextoChico, { color: colorTexto }]}>{titulo}</Text>
        </>
      )}
    </Pressable>
  );
}

/** Botón redondo con solo un ícono (barra de acciones, controles de llamada). */
export function BotonIcono({
  icono,
  onPress,
  etiqueta,
  tono = "neutro",
  activo,
  relleno,
  tam = 44,
  deshabilitado,
  style,
}: {
  icono: NombreIcono;
  onPress: () => void;
  /** Para lectores de pantalla. */
  etiqueta: string;
  tono?: Tono;
  activo?: boolean;
  /** Fondo de color pleno (colgar, contestar). */
  relleno?: boolean;
  tam?: number;
  deshabilitado?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const c = useColores();
  const [suave, texto, pleno] = colorDeTono(c, tono);
  const lleno = relleno || activo;
  const fondo = lleno ? (tono === "neutro" ? c.marca : pleno) : tono === "neutro" ? c.superficie3 : suave;
  const color = lleno ? (tono === "neutro" || tono === "marca" ? c.sobreMarca : c.sobreColor) : tono === "neutro" ? c.texto : texto;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={etiqueta}
      accessibilityState={{ selected: !!activo, disabled: !!deshabilitado }}
      onPress={() => {
        toque();
        onPress();
      }}
      disabled={deshabilitado}
      hitSlop={6}
      style={({ pressed }) => [
        { width: tam, height: tam, borderRadius: tam / 2, backgroundColor: fondo, alignItems: "center", justifyContent: "center" },
        relleno && sombraDe(c, 2),
        deshabilitado && { opacity: 0.4 },
        pressed && { transform: [{ scale: 0.94 }], opacity: 0.85 },
        style,
      ]}
    >
      <Icono nombre={icono} tam={Math.round(tam * 0.46)} color={color} />
    </Pressable>
  );
}

/** Ícono sobre un cuadrito de color suave (encabezados de fila, métricas). */
export function CajaIcono({ icono, tono = "marca", tam = 40 }: { icono: NombreIcono; tono?: Tono; tam?: number }) {
  const c = useColores();
  const [suave, texto] = colorDeTono(c, tono);
  return (
    <View style={{ width: tam, height: tam, borderRadius: tam * 0.3, backgroundColor: suave, alignItems: "center", justifyContent: "center" }}>
      <Icono nombre={icono} tam={Math.round(tam * 0.5)} color={texto} />
    </View>
  );
}

/** Campo con etiqueta fija arriba (no depende del placeholder para explicarse). */
export function Campo({
  etiqueta,
  icono,
  ayuda,
  error,
  secureTextEntry,
  style,
  ...props
}: {
  etiqueta: string;
  icono?: NombreIcono;
  ayuda?: string;
  error?: string;
} & TextInputProps) {
  const { c, oscuro } = useTema();
  const e = useEstilos();
  const [foco, setFoco] = useState(false);
  const [ver, setVer] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <Text style={e.etiqueta}>{etiqueta}</Text>
      <View style={[e.campo, foco && { borderColor: c.marca }, !!error && { borderColor: c.peligro }]}>
        {icono ? <Icono nombre={icono} tam={18} color={c.textoSecundario} /> : null}
        <TextInput
          placeholderTextColor={c.placeholder}
          selectionColor={c.marca}
          keyboardAppearance={oscuro ? "dark" : "light"}
          secureTextEntry={secureTextEntry && !ver}
          onFocus={(ev) => {
            setFoco(true);
            props.onFocus?.(ev);
          }}
          onBlur={(ev) => {
            setFoco(false);
            props.onBlur?.(ev);
          }}
          style={[e.campoTexto, style as StyleProp<TextStyle>]}
          {...props}
        />
        {secureTextEntry ? (
          <Pressable onPress={() => setVer((v) => !v)} hitSlop={10} accessibilityLabel={ver ? "Ocultar" : "Mostrar"}>
            <Icono nombre={ver ? "ocultar" : "ver"} tam={20} color={c.textoSecundario} />
          </Pressable>
        ) : null}
      </View>
      {error ? <Text style={[e.ayuda, { color: c.peligroTexto }]}>{error}</Text> : ayuda ? <Text style={e.ayuda}>{ayuda}</Text> : null}
    </View>
  );
}

/** Pastilla de estado con punto de color. */
export function Pildora({ texto, tono, icono }: { texto: string; tono: Tono; icono?: NombreIcono }) {
  const c = useColores();
  const e = useEstilos();
  const [fondo, colorTexto, pleno] = colorDeTono(c, tono);
  return (
    <View style={[e.pildora, { backgroundColor: fondo }]}>
      {icono ? <Icono nombre={icono} tam={13} color={colorTexto} /> : <View style={[e.punto, { backgroundColor: pleno }]} />}
      <Text style={[e.pildoraTexto, { color: colorTexto }]}>{texto}</Text>
    </View>
  );
}

/** Bloque con título chico arriba y su contenido agrupado en una tarjeta. */
export function Seccion({
  titulo,
  accion,
  children,
  sinTarjeta,
}: {
  titulo?: string;
  accion?: ReactNode;
  children: ReactNode;
  sinTarjeta?: boolean;
}) {
  const e = useEstilos();
  return (
    <View style={{ gap: 8 }}>
      {titulo || accion ? (
        <View style={e.seccionCabecera}>
          {titulo ? <Text style={e.seccionTitulo}>{titulo}</Text> : <View />}
          {accion}
        </View>
      ) : null}
      {sinTarjeta ? children : <View style={e.grupo}>{children}</View>}
    </View>
  );
}

/**
 * Fila de un grupo (menú, ajustes, detalle): ícono, título, detalle y a la
 * derecha un valor, un control o la flecha si navega.
 */
export function FilaMenu({
  titulo,
  detalle,
  icono,
  tono = "neutro",
  derecha,
  valor,
  onPress,
  peligro,
  ultima,
}: {
  titulo: string;
  detalle?: string;
  icono?: NombreIcono;
  tono?: Tono;
  derecha?: ReactNode;
  valor?: string;
  onPress?: () => void;
  peligro?: boolean;
  ultima?: boolean;
}) {
  const c = useColores();
  const e = useEstilos();
  const contenido = (
    <>
      {icono ? <CajaIcono icono={icono} tono={peligro ? "peligro" : tono} tam={34} /> : null}
      <View style={{ flex: 1 }}>
        <Text style={[e.filaTitulo, peligro && { color: c.peligroTexto }]} numberOfLines={1}>
          {titulo}
        </Text>
        {detalle ? (
          <Text style={e.filaDetalle} numberOfLines={2}>
            {detalle}
          </Text>
        ) : null}
      </View>
      {valor ? (
        <Text style={e.filaValor} numberOfLines={1} selectable>
          {valor}
        </Text>
      ) : null}
      {derecha}
      {onPress && !derecha ? <Icono nombre="derecha" tam={16} color={c.placeholder} /> : null}
    </>
  );
  const estilo = [e.fila, !ultima && e.filaLinea];
  if (!onPress) return <View style={estilo}>{contenido}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [...estilo, pressed && { backgroundColor: c.superficie2 }]}
    >
      {contenido}
    </Pressable>
  );
}

/** Indicador numérico (métricas, resúmenes). */
export function Metrica({
  etiqueta,
  valor,
  icono,
  tono = "marca",
  detalle,
  style,
}: {
  etiqueta: string;
  valor: string | number;
  icono?: NombreIcono;
  tono?: Tono;
  detalle?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const e = useEstilos();
  return (
    <View style={[e.tarjeta, { flex: 1, gap: 10, padding: 14 }, style]}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={e.metricaEtiqueta} numberOfLines={1}>
          {etiqueta}
        </Text>
        {icono ? <CajaIcono icono={icono} tono={tono} tam={30} /> : null}
      </View>
      <Text style={e.metricaValor} numberOfLines={1} adjustsFontSizeToFit>
        {valor}
      </Text>
      {detalle ? <Text style={e.filaDetalle}>{detalle}</Text> : null}
    </View>
  );
}

/** Título grande de pantalla con subtítulo y una acción opcional a la derecha. */
export function Titulo({ titulo, subtitulo, accion }: { titulo: string; subtitulo?: string; accion?: ReactNode }) {
  const e = useEstilos();
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 12, marginBottom: 4 }}>
      <View style={{ flex: 1 }}>
        <Text style={e.titulo}>{titulo}</Text>
        {subtitulo ? <Text style={e.subtitulo}>{subtitulo}</Text> : null}
      </View>
      {accion}
    </View>
  );
}

const useEstilos = crearEstilos((c) => ({
  tarjeta: {
    backgroundColor: c.superficie,
    borderRadius: radios.grande,
    borderWidth: 1,
    borderColor: c.borde,
    padding: 16,
    ...sombraDe(c, 1),
  },
  presionada: { backgroundColor: c.superficie2 },
  logo: { backgroundColor: c.marca, alignItems: "center", justifyContent: "center", ...sombraDe(c, 2) },
  logoTexto: { color: c.sobreMarca, fontWeight: "800", letterSpacing: 0.5 },
  boton: {
    flexDirection: "row",
    gap: 8,
    borderRadius: radios.medio,
    borderWidth: 1,
    paddingVertical: 13,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
  },
  botonChico: { minHeight: 36, paddingVertical: 7, paddingHorizontal: 12, borderRadius: radios.chico },
  botonTexto: { fontSize: 16, fontWeight: "600" },
  botonTextoChico: { fontSize: 13.5 },
  etiqueta: { fontSize: 12.5, fontWeight: "600", color: c.textoSuave },
  campo: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1,
    borderColor: c.bordeFuerte,
    borderRadius: radios.medio,
    paddingHorizontal: 14,
    backgroundColor: c.superficie,
  },
  campoTexto: { flex: 1, paddingVertical: 12, fontSize: 16, color: c.texto },
  ayuda: { fontSize: 12, color: c.textoSecundario, lineHeight: 16 },
  pildora: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radios.pildora,
  },
  punto: { width: 7, height: 7, borderRadius: 4 },
  pildoraTexto: { fontSize: 12, fontWeight: "600" },
  seccionCabecera: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4 },
  seccionTitulo: { fontSize: 12, fontWeight: "700", color: c.textoSecundario, letterSpacing: 0.6, textTransform: "uppercase" },
  grupo: {
    backgroundColor: c.superficie,
    borderRadius: radios.grande,
    borderWidth: 1,
    borderColor: c.borde,
    overflow: "hidden",
    ...sombraDe(c, 1),
  },
  fila: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12, paddingHorizontal: 14, minHeight: 52 },
  filaLinea: { borderBottomWidth: 1, borderBottomColor: c.borde },
  filaTitulo: { fontSize: 15, fontWeight: "600", color: c.texto },
  filaDetalle: { fontSize: 12.5, color: c.textoSecundario, marginTop: 2, lineHeight: 17 },
  filaValor: { fontSize: 14, color: c.textoSecundario, maxWidth: "45%" },
  metricaEtiqueta: { flex: 1, fontSize: 12.5, fontWeight: "600", color: c.textoSecundario },
  metricaValor: { fontSize: 26, fontWeight: "800", color: c.texto, letterSpacing: -0.5, fontVariant: ["tabular-nums"] },
  titulo: { fontSize: 26, fontWeight: "800", color: c.texto, letterSpacing: -0.4 },
  subtitulo: { fontSize: 14, color: c.textoSecundario, marginTop: 2 },
}));

/** Pestañas dentro de una pantalla (Recientes / Contactos, Gestión / Agenda…). */
export function Segmentado<T extends string>({
  opciones,
  valor,
  onChange,
}: {
  opciones: { valor: T; etiqueta: string; icono?: NombreIcono }[];
  valor: T;
  onChange: (v: T) => void;
}) {
  const c = useColores();
  return (
    <View style={{ flexDirection: "row", backgroundColor: c.superficie3, borderRadius: radios.medio, padding: 3, gap: 3 }} accessibilityRole="tablist">
      {opciones.map((o) => {
        const activo = o.valor === valor;
        return (
          <Pressable
            key={o.valor}
            accessibilityRole="tab"
            accessibilityState={{ selected: activo }}
            onPress={() => {
              toque();
              onChange(o.valor);
            }}
            style={{
              flex: 1,
              flexDirection: "row",
              gap: 6,
              justifyContent: "center",
              alignItems: "center",
              paddingVertical: 9,
              borderRadius: radios.chico,
              backgroundColor: activo ? c.superficie : "transparent",
              borderWidth: activo ? 1 : 0,
              borderColor: c.borde,
            }}
          >
            {o.icono ? <Icono nombre={o.icono} tam={16} color={activo ? c.marcaTexto : c.textoSecundario} /> : null}
            <Text style={{ fontSize: 13.5, fontWeight: "700", color: activo ? c.texto : c.textoSecundario }} numberOfLines={1}>
              {o.etiqueta}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Barra de avance (0 a 100). */
export function BarraProgreso({ valor, tono = "marca", alto = 8 }: { valor: number; tono?: Tono; alto?: number }) {
  const c = useColores();
  const color = colorDeTono(c, tono)[2];
  return (
    <View style={{ height: alto, borderRadius: alto / 2, backgroundColor: c.superficie3, overflow: "hidden" }}>
      <View style={{ height: alto, width: `${Math.max(0, Math.min(100, valor))}%`, backgroundColor: color, borderRadius: alto / 2 }} />
    </View>
  );
}
