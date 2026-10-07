import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { guia, guiaPorId, NOMBRE_PANTALLA, useGuiaEnCurso } from "@/src/guias";
import { toque } from "@/src/haptico";
import { Icono } from "@/src/Icono";
import { radios, sombraDe, useColores } from "@/src/tema";

/**
 * La guía en curso, en una tarjeta pequeña sobre la barra de pestañas. No
 * tapa la pantalla ni bloquea nada: dice qué hacer en este paso, lleva a la
 * pantalla correcta si hace falta y se puede achicar o cerrar.
 */
export function GuiaFlotante() {
  const c = useColores();
  const router = useRouter();
  const ruta = usePathname();
  const insets = useSafeAreaInsets();
  const enCurso = useGuiaEnCurso();
  const [chica, setChica] = useState(false);
  const g = enCurso ? guiaPorId(enCurso.id) : undefined;
  if (!g || !enCurso) return null;

  const total = g.pasos.length;
  const terminada = enCurso.paso >= total;
  const paso = terminada ? null : g.pasos[enCurso.paso];
  const fuera = !!paso && ruta !== paso.ruta;
  const boton = (texto: string, onPress: () => void, principal = false) => (
    <Pressable
      onPress={() => {
        toque();
        onPress();
      }}
      style={{ paddingVertical: 7, paddingHorizontal: 12, borderRadius: 999, backgroundColor: principal ? c.marca : "transparent" }}
    >
      <Text style={{ fontSize: 13, fontWeight: "700", color: principal ? c.sobreMarca : c.textoSuave }}>{texto}</Text>
    </Pressable>
  );

  return (
    <View
      pointerEvents="box-none"
      style={{ position: "absolute", left: 12, right: 80, bottom: 64 + insets.bottom }}
    >
      {chica ? (
        <Pressable
          onPress={() => setChica(false)}
          style={{ alignSelf: "flex-start", backgroundColor: c.superficie, borderColor: c.borde, borderWidth: 1, borderRadius: 999, paddingVertical: 8, paddingHorizontal: 14, ...sombraDe(c, 2) }}
        >
          <Text style={{ fontSize: 13, fontWeight: "700", color: c.marcaTexto }}>
            Guía: paso {Math.min(enCurso.paso + 1, total)} de {total}
          </Text>
        </Pressable>
      ) : (
        <View
          accessibilityRole="summary"
          style={{ backgroundColor: c.superficie, borderColor: c.borde, borderWidth: 1, borderRadius: radios.grande, padding: 14, gap: 6, ...sombraDe(c, 3) }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text numberOfLines={1} style={{ flex: 1, fontSize: 11, fontWeight: "700", letterSpacing: 0.5, color: c.textoSecundario }}>
              {g.titulo.toUpperCase()}
            </Text>
            <Pressable onPress={() => setChica(true)} hitSlop={10} accessibilityLabel="Achicar la guía">
              <Icono nombre="ocultar" tam={16} color={c.textoSecundario} />
            </Pressable>
            <Pressable onPress={guia.salir} hitSlop={10} accessibilityLabel="Salir de la guía">
              <Icono nombre="cerrar" tam={16} color={c.textoSecundario} />
            </Pressable>
          </View>
          {terminada ? (
            <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>¡Listo! ✓</Text>
          ) : fuera ? (
            <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>Ve a «{NOMBRE_PANTALLA[paso!.ruta] ?? paso!.ruta}»</Text>
          ) : (
            <>
              <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>{paso!.titulo}</Text>
              <Text style={{ fontSize: 14, lineHeight: 20, color: c.textoSuave }}>{paso!.texto}</Text>
            </>
          )}
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
            <Text style={{ fontSize: 12, color: c.textoSecundario }}>
              {Math.min(enCurso.paso + 1, total)} / {total}
            </Text>
            <View style={{ flex: 1 }} />
            {enCurso.paso > 0 && !terminada ? boton("Atrás", () => guia.mover(-1)) : null}
            {terminada
              ? boton("Cerrar", guia.salir, true)
              : fuera
                ? boton("Llévame", () => router.navigate(paso!.ruta as never), true)
                : boton(enCurso.paso === total - 1 ? "Terminar" : "Siguiente", () => guia.mover(1), true)}
          </View>
        </View>
      )}
    </View>
  );
}
