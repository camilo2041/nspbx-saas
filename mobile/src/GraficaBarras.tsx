/**
 * Barras por día, apiladas por serie (o una sola serie). Sin librería de
 * gráficas: son Views, así siguen el tema y no suman un módulo nativo.
 *
 * Reglas (las mismas del panel): marcas finas con el extremo redondeado
 * anclado a la base, 2 px de aire entre segmentos, rejilla discreta, leyenda
 * siempre que hay más de una serie, y el valor exacto al tocar una barra
 * (no un número encima de cada una). Los colores de serie son los del panel
 * (naranja y azul de la marca NSIT), validados para daltonismo en claro y en
 * oscuro.
 */
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { toque } from "@/src/haptico";
import { useColores } from "@/src/tema";

export interface Serie {
  clave: string;
  etiqueta: string;
  color: string;
}

export function GraficaBarras<T extends Record<string, unknown>>({
  datos,
  series,
  etiquetaX,
  formato,
  alto = 140,
}: {
  datos: T[];
  series: Serie[];
  /** Texto del eje X de cada fila (fecha corta). */
  etiquetaX: (fila: T) => string;
  formato: (n: number) => string;
  alto?: number;
}) {
  const c = useColores();
  const [elegida, setElegida] = useState<number | null>(null);
  const total = (f: T) => series.reduce((s, x) => s + (Number(f[x.clave]) || 0), 0);
  const maximo = Math.max(0, ...datos.map(total));
  const sel = elegida !== null ? datos[elegida] : null;

  return (
    <View style={{ gap: 10 }}>
      {series.length > 1 ? (
        <View style={{ flexDirection: "row", gap: 16, flexWrap: "wrap" }}>
          {series.map((s) => (
            <View key={s.clave} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <View style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: s.color }} />
              <Text style={{ fontSize: 12, color: c.textoSuave }}>{s.etiqueta}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* Detalle del día tocado (o una pista si no hay ninguno). */}
      <Text style={{ fontSize: 12.5, color: sel ? c.texto : c.textoSecundario, minHeight: 18 }}>
        {sel
          ? `${etiquetaX(sel)}: ${series.map((s) => `${series.length > 1 ? s.etiqueta + " " : ""}${formato(Number(sel[s.clave]) || 0)}`).join(" · ")}${
              series.length > 1 ? ` · total ${formato(total(sel))}` : ""
            }`
          : maximo > 0
            ? "Toca una barra para ver el detalle del día."
            : "Sin datos en este rango."}
      </Text>

      <View style={{ height: alto, flexDirection: "row", alignItems: "flex-end", gap: 3 }}>
        {/* Rejilla: solo la línea de base y la del máximo, discretas. */}
        <View style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 1, backgroundColor: c.borde }} />
        <View style={{ position: "absolute", left: 0, right: 0, top: 0, height: 1, backgroundColor: c.borde, opacity: 0.6 }} />
        {maximo > 0 ? (
          <Text style={{ position: "absolute", right: 0, top: 2, fontSize: 10.5, color: c.textoSecundario }}>{formato(maximo)}</Text>
        ) : null}
        {datos.map((f, i) => {
          const t = total(f);
          const activa = elegida === i;
          return (
            <Pressable
              key={i}
              accessibilityRole="button"
              accessibilityLabel={`${etiquetaX(f)}: ${series.map((s) => `${s.etiqueta} ${formato(Number(f[s.clave]) || 0)}`).join(", ")}`}
              onPress={() => {
                toque();
                setElegida(activa ? null : i);
              }}
              hitSlop={{ top: 8, bottom: 8 }}
              style={{ flex: 1, height: "100%", justifyContent: "flex-end", opacity: elegida === null || activa ? 1 : 0.45 }}
            >
              {/* Segmentos de abajo hacia arriba; 2 px de aire entre ellos. */}
              <View style={{ gap: 2 }}>
                {[...series].reverse().map((s, k, arr) => {
                  const v = Number(f[s.clave]) || 0;
                  if (!v || !maximo) return null;
                  const h = Math.max(2, (v / maximo) * (alto - 18));
                  // Solo el segmento de más arriba lleva el extremo redondeado.
                  const arriba = k === arr.findIndex((x) => (Number(f[x.clave]) || 0) > 0);
                  return (
                    <View
                      key={s.clave}
                      style={{
                        height: h,
                        backgroundColor: s.color,
                        borderTopLeftRadius: arriba ? 4 : 0,
                        borderTopRightRadius: arriba ? 4 : 0,
                      }}
                    />
                  );
                })}
                {t === 0 ? <View style={{ height: 2, backgroundColor: c.borde }} /> : null}
              </View>
            </Pressable>
          );
        })}
      </View>

      {datos.length ? (
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={{ fontSize: 11, color: c.textoSecundario }}>{etiquetaX(datos[0])}</Text>
          <Text style={{ fontSize: 11, color: c.textoSecundario }}>{etiquetaX(datos[datos.length - 1])}</Text>
        </View>
      ) : null}
    </View>
  );
}
