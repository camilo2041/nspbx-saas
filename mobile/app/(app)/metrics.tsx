import { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import type { AiUsageSummary, CallLogOut, CallStats } from "@/src/api/types";
import { useAuth } from "@/src/auth/AuthContext";
import { colores } from "@/src/tema";

function Tarjeta({ etiqueta, valor }: { etiqueta: string; valor: string | number }) {
  return (
    <View style={styles.tarjeta}>
      <Text style={styles.tarjetaValor}>{valor}</Text>
      <Text style={styles.tarjetaEtiqueta}>{etiqueta}</Text>
    </View>
  );
}

export default function MetricsScreen() {
  const { puede } = useAuth();
  const verLlamadas = puede("llamadas:ver_propias") || puede("llamadas:ver_todas");
  const verConsumoIa = puede("consumo_ia:ver");

  const [stats, setStats] = useState<CallStats | null>(null);
  const [llamadas, setLlamadas] = useState<CallLogOut[]>([]);
  const [ia, setIa] = useState<AiUsageSummary | null>(null);
  const [refrescando, setRefrescando] = useState(false);

  const cargar = useCallback(async () => {
    if (verLlamadas) {
      const [s, l] = await Promise.all([
        peticion<CallStats>("/api/calls/stats"),
        peticion<CallLogOut[]>("/api/calls?limit=20"),
      ]);
      setStats(s);
      setLlamadas(l);
    }
    if (verConsumoIa) {
      setIa(await peticion<AiUsageSummary>("/api/ai-usage/summary?days=30"));
    }
  }, [verLlamadas, verConsumoIa]);

  useEffect(() => {
    cargar().catch(() => {});
  }, [cargar]);

  const refrescar = async () => {
    setRefrescando(true);
    await cargar().catch(() => {});
    setRefrescando(false);
  };

  if (!verLlamadas && !verConsumoIa) {
    return (
      <View style={styles.centro}>
        <Text style={styles.info}>Tu rol no tiene permiso para ver métricas.</Text>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.lista}
      contentContainerStyle={styles.contenido}
      refreshControl={<RefreshControl refreshing={refrescando} onRefresh={refrescar} />}
      data={verLlamadas ? llamadas : []}
      keyExtractor={(item) => String(item.id)}
      ListHeaderComponent={
        <View>
          {stats && (
            <View>
              <Text style={styles.seccion}>Mis llamadas</Text>
              <View style={styles.fila}>
                <Tarjeta etiqueta="Total" valor={stats.total} />
                <Tarjeta etiqueta="Contestadas" valor={stats.answered} />
                <Tarjeta etiqueta="No contestadas" valor={stats.no_answer} />
              </View>
              <View style={styles.fila}>
                <Tarjeta etiqueta="Ocupado" valor={stats.busy} />
                <Tarjeta etiqueta="Minutos hablados" valor={stats.talk_minutes} />
              </View>
            </View>
          )}

          {ia && (
            <View>
              <Text style={styles.seccion}>Consumo IA (30 días)</Text>
              <View style={styles.fila}>
                <Tarjeta etiqueta="Llamadas" valor={ia.calls} />
                <Tarjeta etiqueta="Resueltas" valor={ia.resolved} />
                <Tarjeta etiqueta="Contención" valor={`${Math.round(ia.containment_rate * 100)}%`} />
              </View>
              <View style={styles.fila}>
                <Tarjeta etiqueta="Costo total" valor={`$${ia.cost_usd.toFixed(2)}`} />
                <Tarjeta etiqueta="Costo/llamada" valor={`$${ia.cost_per_call.toFixed(3)}`} />
              </View>
            </View>
          )}

          {verLlamadas && <Text style={styles.seccion}>Últimas llamadas</Text>}
        </View>
      }
      renderItem={({ item }) => (
        <View style={styles.llamada}>
          <Text style={styles.llamadaNumero}>
            {item.direction === "inbound" ? "⬇️" : "⬆️"} {item.caller_number || item.callee_number || "—"}
          </Text>
          <Text style={styles.llamadaDetalle}>
            {item.status} · {Math.round(item.billsec / 60)} min
          </Text>
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  lista: { flex: 1, backgroundColor: colores.fondo },
  contenido: { padding: 16, gap: 8 },
  centro: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  info: { textAlign: "center", color: colores.textoSecundario, fontSize: 15 },
  seccion: { fontSize: 17, fontWeight: "700", marginTop: 16, marginBottom: 8, color: colores.texto },
  fila: { flexDirection: "row", gap: 8, marginBottom: 8 },
  tarjeta: { flex: 1, backgroundColor: "#f5f5f7", borderRadius: 10, padding: 12, alignItems: "center" },
  tarjetaValor: { fontSize: 20, fontWeight: "700", color: colores.texto },
  tarjetaEtiqueta: { fontSize: 12, color: colores.textoSecundario, textAlign: "center" },
  llamada: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#eee" },
  llamadaNumero: { fontSize: 15, fontWeight: "600", color: colores.texto },
  llamadaDetalle: { fontSize: 13, color: colores.textoSecundario },
});
