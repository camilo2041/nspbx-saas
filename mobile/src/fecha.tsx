/**
 * Fechas de la app.
 *
 * El backend guarda las fechas de negocio (citas, vencimientos) SIN zona: son
 * la hora local de la empresa. Por eso acá se manejan como texto
 * "AAAA-MM-DDTHH:MM" y nunca pasan por toISOString(), que las convertiría a
 * UTC (la cita de las 10:00 quedaba a las 15:00).
 */
import DateTimePicker, { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import { useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";

import { toque } from "@/src/haptico";
import { Icono } from "@/src/Icono";
import { radios, useTema } from "@/src/tema";

const dos = (n: number) => String(n).padStart(2, "0");

/** Date -> "AAAA-MM-DDTHH:MM" (o solo la fecha) en hora local. */
export function aTextoLocal(d: Date, conHora = true): string {
  const f = `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  return conHora ? `${f}T${dos(d.getHours())}:${dos(d.getMinutes())}` : f;
}

/** "AAAA-MM-DD[THH:MM[:SS]]" sin zona -> Date en hora local. */
export function deTextoLocal(s: string | null | undefined): Date | null {
  if (!s) return null;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] ?? 0), Number(m[5] ?? 0));
}

export function fechaLarga(s: string | null | undefined, conHora = true): string {
  const d = deTextoLocal(s);
  if (!d) return "—";
  const f = d.toLocaleDateString("es-CO", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  return conHora ? `${f} · ${d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}` : f;
}

export function horaCorta(s: string | null | undefined): string {
  const d = deTextoLocal(s);
  return d ? d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" }) : "";
}

/**
 * Campo de fecha (o fecha y hora). En Android abre los diálogos del sistema;
 * en iOS despliega el calendario debajo del campo.
 */
export function SelectorFecha({
  etiqueta,
  valor,
  onChange,
  conHora = true,
  opcional,
  ayuda,
}: {
  etiqueta: string;
  valor: string;
  onChange: (v: string) => void;
  conHora?: boolean;
  /** Se puede dejar vacío (muestra "Quitar"). */
  opcional?: boolean;
  ayuda?: string;
}) {
  const { c, oscuro } = useTema();
  const [abiertoIos, setAbiertoIos] = useState(false);
  const actual = deTextoLocal(valor);

  const abrir = () => {
    toque();
    const base = actual ?? new Date();
    if (Platform.OS !== "android") {
      if (!actual) onChange(aTextoLocal(base, conHora));
      setAbiertoIos((v) => !v);
      return;
    }
    DateTimePickerAndroid.open({
      value: base,
      mode: "date",
      onValueChange: (_e, dia) => {
        if (!conHora) {
          onChange(aTextoLocal(dia, false));
          return;
        }
        DateTimePickerAndroid.open({
          value: dia,
          mode: "time",
          is24Hour: false,
          onValueChange: (_e2, hora) => {
            const d = new Date(dia);
            d.setHours(hora.getHours(), hora.getMinutes(), 0, 0);
            onChange(aTextoLocal(d, true));
          },
        });
      },
    });
  };

  return (
    <View style={{ gap: 6 }}>
      <Text style={{ fontSize: 12.5, fontWeight: "600", color: c.textoSuave }}>{etiqueta}</Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${etiqueta}: ${actual ? fechaLarga(valor, conHora) : "sin fecha"}`}
          onPress={abrir}
          style={({ pressed }) => ({
            flex: 1,
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            borderWidth: 1,
            borderColor: abiertoIos ? c.marca : c.bordeFuerte,
            borderRadius: radios.medio,
            paddingHorizontal: 14,
            paddingVertical: 13,
            backgroundColor: pressed ? c.superficie2 : c.superficie,
          })}
        >
          <Icono nombre="calendario" tam={18} color={c.textoSecundario} />
          <Text style={{ flex: 1, fontSize: 16, color: actual ? c.texto : c.placeholder }}>
            {actual ? fechaLarga(valor, conHora) : "Elegir fecha"}
          </Text>
        </Pressable>
        {opcional && actual ? (
          <Pressable
            onPress={() => {
              setAbiertoIos(false);
              onChange("");
            }}
            style={{ justifyContent: "center", paddingHorizontal: 12, borderRadius: radios.medio, backgroundColor: c.superficie3 }}
          >
            <Text style={{ fontSize: 12, fontWeight: "700", color: c.textoSuave }}>Quitar</Text>
          </Pressable>
        ) : null}
      </View>
      {Platform.OS === "ios" && abiertoIos && actual ? (
        <DateTimePicker
          value={actual}
          mode={conHora ? "datetime" : "date"}
          display="inline"
          themeVariant={oscuro ? "dark" : "light"}
          accentColor={c.marca}
          onValueChange={(_e, d) => onChange(aTextoLocal(d, conHora))}
        />
      ) : null}
      {ayuda ? <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16 }}>{ayuda}</Text> : null}
    </View>
  );
}

/** Segundos como "4,2 s" o "1:05" (desde un minuto). null → "—". */
export function tiempoCorto(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "—";
  if (segundos < 60) return `${segundos.toLocaleString("es-CO", { maximumFractionDigits: 1 })} s`;
  const total = Math.round(segundos);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
