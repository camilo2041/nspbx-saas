import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, EstadoVacio, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { toque } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { BarraProgreso, Boton, Metrica, Pildora, Tarjeta, Tono } from "@/src/ui";

interface Criterio {
  id: number;
  nombre: string;
  descripcion: string | null;
  peso: number;
  activo: boolean;
}

interface Evaluacion {
  id: number;
  call_id: number;
  puntajes: Record<string, number>;
  total_pct: number;
  comentario: string | null;
  origen: "manual" | "ia";
  evaluador: string | null;
  created_at: string | null;
}

const NOTAS: Record<number, { texto: string; tono: Tono }> = {
  0: { texto: "No cumple", tono: "peligro" },
  1: { texto: "A medias", tono: "aviso" },
  2: { texto: "Cumple", tono: "ok" },
};

const tonoDe = (pct: number): Tono => (pct >= 85 ? "ok" : pct >= 60 ? "aviso" : "peligro");

function fecha(s: string | null): string {
  if (!s) return "";
  const d = new Date(s.endsWith("Z") ? s : `${s}Z`);
  return d.toLocaleDateString("es-CO", { day: "numeric", month: "short", year: "numeric" });
}

/**
 * Mis evaluaciones de calidad: lo que el supervisor calificó de mis llamadas
 * (pantalla Calidad del panel, pestaña «Mis evaluaciones»).
 */
export default function MisEvaluaciones() {
  const c = useColores();
  const router = useRouter();
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<{
    criterios: Criterio[];
    evaluaciones: Evaluacion[];
  }>("/api/calidad/mias");
  const [abierta, setAbierta] = useState<number | null>(null);

  const evals = datos?.evaluaciones ?? [];
  const nombres = Object.fromEntries((datos?.criterios ?? []).map((x) => [String(x.id), x.nombre]));
  const promedio = evals.length ? Math.round((10 * evals.reduce((a, e) => a + e.total_pct, 0)) / evals.length) / 10 : null;

  return (
    <Pantalla refrescando={refrescando} onRefrescar={recargar}>
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {cargando ? <ListaEsqueleto /> : null}
      {!cargando && datos && evals.length === 0 ? (
        <EstadoVacio
          icono="ok"
          titulo="Todavía no te han evaluado"
          texto="Cuando tu supervisor califique una de tus llamadas, vas a ver acá el resultado y sus comentarios."
        />
      ) : null}
      {promedio !== null ? (
        <View style={{ flexDirection: "row", gap: 12 }}>
          <Metrica etiqueta="Promedio" valor={`${promedio}%`} tono={tonoDe(promedio)} />
          <Metrica etiqueta="Evaluaciones" valor={String(evals.length)} tono="marca" />
        </View>
      ) : null}
      {evals.map((ev) => (
        <Tarjeta
          key={ev.id}
          onPress={() => {
            toque();
            setAbierta(abierta === ev.id ? null : ev.id);
          }}
          style={{ gap: 10 }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>{fecha(ev.created_at)}</Text>
              <Text style={{ fontSize: 12.5, color: c.textoSecundario, marginTop: 2 }}>
                {ev.evaluador ? `Evaluó ${ev.evaluador}` : "Evaluación"}
                {ev.origen === "ia" ? " · con ayuda de IA" : ""}
              </Text>
            </View>
            <Pildora texto={`${ev.total_pct}%`} tono={tonoDe(ev.total_pct)} />
          </View>
          <BarraProgreso valor={ev.total_pct} tono={tonoDe(ev.total_pct)} />
          {ev.comentario ? <Text style={{ fontSize: 14, color: c.textoSuave, lineHeight: 20 }}>“{ev.comentario}”</Text> : null}
          {abierta === ev.id ? (
            <View style={{ gap: 8, borderTopWidth: 1, borderTopColor: c.borde, paddingTop: 10 }}>
              {Object.entries(ev.puntajes).map(([cid, nota]) => (
                <View key={cid} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <Text style={{ flex: 1, fontSize: 13.5, color: c.texto }}>{nombres[cid] ?? "Criterio"}</Text>
                  <Pildora texto={NOTAS[nota]?.texto ?? String(nota)} tono={NOTAS[nota]?.tono ?? "neutro"} />
                </View>
              ))}
              <Boton chico titulo="Ver la llamada" variante="contorno" onPress={() => router.push(`/llamada/${ev.call_id}`)} />
            </View>
          ) : null}
        </Tarjeta>
      ))}
    </Pantalla>
  );
}
