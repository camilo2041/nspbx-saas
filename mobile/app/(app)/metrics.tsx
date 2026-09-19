import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import type { AiUsageSummary, CallLogOut, CallStats } from "@/src/api/types";
import { useAuth } from "@/src/auth/AuthContext";
import { colores } from "@/src/tema";
import { Pildora, Tarjeta } from "@/src/ui";

function Dato({ etiqueta, valor, tono }: { etiqueta: string; valor: string | number; tono?: string }) {
  return (
    <View style={estilos.dato}>
      <Text style={[estilos.datoValor, tono ? { color: tono } : null]}>{valor}</Text>
      <Text style={estilos.datoEtiqueta}>{etiqueta}</Text>
    </View>
  );
}

const ESTADOS: Record<string, { texto: string; tono: "ok" | "aviso" | "peligro" | "neutro" }> = {
  answered: { texto: "Contestada", tono: "ok" },
  no_answer: { texto: "Sin respuesta", tono: "aviso" },
  busy: { texto: "Ocupado", tono: "aviso" },
  failed: { texto: "Fallida", tono: "peligro" },
  cancelled: { texto: "Cancelada", tono: "neutro" },
  rejected: { texto: "Rechazada", tono: "peligro" },
};

function fechaCorta(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return d.toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function duracion(seg: number): string {
  const m = Math.floor(seg / 60);
  const s = seg % 60;
  return m > 0 ? `${m} min ${s}s` : `${s}s`;
}

export default function MetricasScreen() {
  const { puede } = useAuth();
  const verTodas = puede("llamadas:ver_todas");
  const verLlamadas = puede("llamadas:ver_propias") || verTodas;
  const verConsumoIa = puede("consumo_ia:ver");

  const [stats, setStats] = useState<CallStats | null>(null);
  const [llamadas, setLlamadas] = useState<CallLogOut[]>([]);
  const [ia, setIa] = useState<AiUsageSummary | null>(null);
  const [cargando, setCargando] = useState(true);
  const [refrescando, setRefrescando] = useState(false);
  const [error, setError] = useState("");

  const cargar = useCallback(async () => {
    setError("");
    try {
      if (verLlamadas) {
        const [s, l] = await Promise.all([
          peticion<CallStats>("/api/calls/stats"),
          peticion<CallLogOut[]>("/api/calls?limit=30"),
        ]);
        setStats(s);
        setLlamadas(l);
      }
      if (verConsumoIa) {
        setIa(await peticion<AiUsageSummary>("/api/ai-usage/summary?days=30"));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las métricas");
    }
  }, [verLlamadas, verConsumoIa]);

  useEffect(() => {
    cargar().finally(() => setCargando(false));
  }, [cargar]);

  if (!verLlamadas && !verConsumoIa) {
    return (
      <View style={estilos.centro}>
        <Tarjeta style={{ alignItems: "center", gap: 8 }}>
          <Text style={{ fontSize: 32 }}>🔒</Text>
          <Text style={estilos.titulo}>Sin acceso a métricas</Text>
          <Text style={estilos.texto}>Tu rol no tiene permiso para ver las métricas. Pídelo a un administrador.</Text>
        </Tarjeta>
      </View>
    );
  }

  return (
    <ScrollView
      style={{ backgroundColor: colores.fondo }}
      contentContainerStyle={estilos.contenido}
      refreshControl={
        <RefreshControl
          refreshing={refrescando}
          colors={[colores.marca]}
          onRefresh={async () => {
            setRefrescando(true);
            await cargar();
            setRefrescando(false);
          }}
        />
      }
    >
      {cargando ? <ActivityIndicator color={colores.marca} style={{ marginTop: 40 }} /> : null}

      {error ? (
        <View style={estilos.error}>
          <Text style={estilos.errorTexto}>{error}</Text>
        </View>
      ) : null}

      {stats ? (
        <Tarjeta style={{ gap: 14 }}>
          <Text style={estilos.seccion}>{verTodas ? "Llamadas de la empresa" : "Mis llamadas"}</Text>
          <View style={estilos.rejilla}>
            <Dato etiqueta="Total" valor={stats.total} />
            <Dato etiqueta="Contestadas" valor={stats.answered} tono={colores.ok} />
            <Dato etiqueta="Sin respuesta" valor={stats.no_answer} tono={colores.aviso} />
          </View>
          <View style={estilos.rejilla}>
            <Dato etiqueta="Ocupado" valor={stats.busy} />
            <Dato etiqueta="Fallidas" valor={stats.failed} tono={colores.peligro} />
            <Dato etiqueta="Min. hablados" valor={stats.talk_minutes} tono={colores.marca} />
          </View>
        </Tarjeta>
      ) : null}

      {ia ? (
        <Tarjeta style={{ gap: 14 }}>
          <Text style={estilos.seccion}>Consumo de IA · 30 días</Text>
          <View style={estilos.rejilla}>
            <Dato etiqueta="Llamadas" valor={ia.calls} />
            <Dato etiqueta="Resueltas" valor={ia.resolved} tono={colores.ok} />
            <Dato etiqueta="Contención" valor={`${Math.round(ia.containment_rate * 100)}%`} />
          </View>
          <View style={estilos.rejilla}>
            <Dato etiqueta="Costo total" valor={`$${ia.cost_usd.toFixed(2)}`} tono={colores.marca} />
            <Dato etiqueta="Por llamada" valor={`$${ia.cost_per_call.toFixed(3)}`} />
            <Dato etiqueta="Por minuto" valor={`$${ia.cost_per_minute.toFixed(3)}`} />
          </View>
        </Tarjeta>
      ) : null}

      {verLlamadas ? (
        <Tarjeta style={{ paddingVertical: 8 }}>
          <Text style={[estilos.seccion, { paddingVertical: 8 }]}>Últimas llamadas</Text>
          {!cargando && llamadas.length === 0 ? <Text style={estilos.texto}>Todavía no hay llamadas registradas.</Text> : null}
          {llamadas.map((l, i) => {
            const entrante = l.direction === "inbound";
            const est = ESTADOS[l.status] ?? { texto: l.status, tono: "neutro" as const };
            return (
              <View key={l.id} style={[estilos.llamada, i > 0 && estilos.llamadaBorde]}>
                <Text style={estilos.flecha}>{entrante ? "↙️" : "↗️"}</Text>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={estilos.llamadaNumero} numberOfLines={1}>
                    {(entrante ? l.caller_name || l.caller_number : l.callee_number) || "Desconocido"}
                  </Text>
                  <Text style={estilos.llamadaDetalle}>
                    {fechaCorta(l.started_at)}
                    {l.billsec > 0 ? ` · ${duracion(l.billsec)}` : ""}
                  </Text>
                </View>
                <Pildora texto={est.texto} tono={est.tono} />
              </View>
            );
          })}
        </Tarjeta>
      ) : null}
    </ScrollView>
  );
}

const estilos = StyleSheet.create({
  contenido: { padding: 16, gap: 14 },
  centro: { flex: 1, justifyContent: "center", padding: 20, backgroundColor: colores.fondo },
  titulo: { fontSize: 17, fontWeight: "700", color: colores.texto },
  texto: { fontSize: 14, color: colores.textoSecundario, textAlign: "center", lineHeight: 20 },
  seccion: { fontSize: 15, fontWeight: "700", color: colores.texto },
  rejilla: { flexDirection: "row", gap: 8 },
  dato: { flex: 1, backgroundColor: colores.superficie2, borderRadius: 12, padding: 10, gap: 2 },
  datoValor: { fontSize: 21, fontWeight: "800", color: colores.texto },
  datoEtiqueta: { fontSize: 11, color: colores.textoSecundario },
  llamada: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10 },
  llamadaBorde: { borderTopWidth: 1, borderTopColor: colores.borde },
  flecha: { fontSize: 18 },
  llamadaNumero: { fontSize: 15, fontWeight: "600", color: colores.texto },
  llamadaDetalle: { fontSize: 12, color: colores.textoSecundario },
  error: { backgroundColor: colores.peligroSuave, borderRadius: 10, padding: 12 },
  errorTexto: { color: colores.peligroTexto, fontSize: 13 },
});
