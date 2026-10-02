import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import type { AiUsageSummary, CallLogOut, CallStats } from "@/src/api/types";
import { useAuth } from "@/src/auth/AuthContext";
import { ResumenCentral } from "@/src/ResumenCentral";
import { Aviso, EstadoVacio, Esqueleto, Pantalla } from "@/src/gestion";
import { crearEstilos, radios } from "@/src/tema";
import { FilaMenu, Metrica, Pildora, Seccion, Tarjeta, Titulo, Tono } from "@/src/ui";

const ESTADOS: Record<string, { texto: string; tono: Tono }> = {
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

function saludo(): string {
  const h = new Date().getHours();
  return h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches";
}

const usd = (n: number, dec = 2) => `US$ ${n.toFixed(dec)}`;

/** Barra de proporción (contestadas sobre el total). */
function Barra({ valor, tono }: { valor: number; tono: string }) {
  const e = useEstilos();
  return (
    <View style={e.barra}>
      <View style={[e.barraLlena, { width: `${Math.max(0, Math.min(100, valor))}%`, backgroundColor: tono }]} />
    </View>
  );
}

export default function ResumenScreen() {
  const router = useRouter();
  const e = useEstilos();
  const { usuario, puede } = useAuth();
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
          peticion<CallLogOut[]>("/api/calls?limit=8"),
        ]);
        setStats(s);
        setLlamadas(l);
      }
      if (verConsumoIa) {
        setIa(await peticion<AiUsageSummary>("/api/ai-usage/summary?days=30"));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las métricas");
    }
  }, [verLlamadas, verConsumoIa]);

  useEffect(() => {
    cargar().finally(() => setCargando(false));
  }, [cargar]);

  const nombre = (usuario?.full_name || usuario?.username || "").split(" ")[0];

  if (!verLlamadas && !verConsumoIa) {
    return (
      <Pantalla>
        <Titulo titulo={`${saludo()}${nombre ? `, ${nombre}` : ""}`} />
        <EstadoVacio
          icono="candado"
          titulo="Sin acceso a métricas"
          texto="Tu rol no tiene permiso para ver las métricas. Pídelo a un administrador."
        />
        <ResumenCentral />
      </Pantalla>
    );
  }

  const tasa = stats && stats.total > 0 ? Math.round((stats.answered / stats.total) * 100) : 0;

  return (
    <Pantalla
      refrescando={refrescando}
      onRefrescar={async () => {
        setRefrescando(true);
        await cargar();
        setRefrescando(false);
      }}
    >
      <Titulo
        titulo={`${saludo()}${nombre ? `, ${nombre}` : ""}`}
        subtitulo={verTodas ? "Así va la operación de la empresa" : "Así van tus llamadas"}
      />

      {error ? <Aviso texto={error} /> : null}

      {cargando ? (
        <View style={{ gap: 10 }}>
          <View style={e.rejilla}>
            <Esqueleto alto={104} style={{ flex: 1, borderRadius: radios.grande }} />
            <Esqueleto alto={104} style={{ flex: 1, borderRadius: radios.grande }} />
          </View>
          <View style={e.rejilla}>
            <Esqueleto alto={104} style={{ flex: 1, borderRadius: radios.grande }} />
            <Esqueleto alto={104} style={{ flex: 1, borderRadius: radios.grande }} />
          </View>
        </View>
      ) : null}

      {stats ? (
        <>
          <View style={e.rejilla}>
            <Metrica etiqueta="Llamadas" valor={stats.total} icono="telefono" tono="marca" />
            <Metrica etiqueta="Contestadas" valor={stats.answered} icono="ok" tono="ok" />
          </View>
          <View style={e.rejilla}>
            <Metrica etiqueta="Sin respuesta" valor={stats.no_answer + stats.busy} icono="perdida" tono="aviso" />
            <Metrica etiqueta="Min. hablados" valor={stats.talk_minutes} icono="horario" tono="info" />
          </View>
          <Tarjeta style={{ gap: 10 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={e.etiqueta}>Tasa de contestación</Text>
              <Text style={e.porcentaje}>{tasa}%</Text>
            </View>
            <Barra valor={tasa} tono={tasa >= 80 ? e.ok.color : tasa >= 50 ? e.aviso.color : e.peligro.color} />
            {stats.failed > 0 ? <Text style={e.nota}>{stats.failed} fallidas por la red o el destino</Text> : null}
          </Tarjeta>
        </>
      ) : null}

      {ia ? (
        <Seccion titulo="Voizbots · últimos 30 días">
          <FilaMenu titulo="Llamadas atendidas" icono="bot" tono="info" valor={String(ia.calls)} />
          <FilaMenu titulo="Resueltas sin agente" icono="ok" tono="ok" valor={`${ia.resolved} · ${Math.round(ia.containment_rate * 100)}%`} />
          <FilaMenu titulo="Costo total" icono="dinero" tono="marca" valor={usd(ia.cost_usd)} />
          <FilaMenu titulo="Costo por minuto" icono="tendencia" tono="neutro" valor={usd(ia.cost_per_minute, 3)} ultima />
        </Seccion>
      ) : null}

      <ResumenCentral />

      {verLlamadas && !cargando ? (
        <Seccion titulo="Últimas llamadas">
          {llamadas.length === 0 ? (
            <FilaMenu titulo="Todavía no hay llamadas registradas" icono="info" ultima />
          ) : (
            llamadas.map((l, i) => {
              const entrante = l.direction === "inbound";
              const est = ESTADOS[l.status] ?? { texto: l.status, tono: "neutro" as const };
              return (
                <FilaMenu
                  key={l.id}
                  titulo={(entrante ? l.caller_name || l.caller_number : l.callee_number) || "Desconocido"}
                  detalle={`${fechaCorta(l.started_at)}${l.billsec > 0 ? ` · ${duracion(l.billsec)}` : ""}`}
                  icono={entrante ? "entrante" : "saliente"}
                  tono={entrante ? "info" : "ok"}
                  derecha={<Pildora texto={est.texto} tono={est.tono} />}
                  onPress={() => router.push({ pathname: "/llamada/[id]", params: { id: String(l.id) } })}
                  ultima={i === llamadas.length - 1}
                />
              );
            })
          )}
        </Seccion>
      ) : null}
    </Pantalla>
  );
}

const useEstilos = crearEstilos((c) => ({
  rejilla: { flexDirection: "row", gap: 10 },
  etiqueta: { fontSize: 13, fontWeight: "600", color: c.textoSecundario },
  porcentaje: { fontSize: 18, fontWeight: "800", color: c.texto, fontVariant: ["tabular-nums"] },
  nota: { fontSize: 12, color: c.textoSecundario },
  barra: { height: 8, borderRadius: 4, backgroundColor: c.superficie3, overflow: "hidden" },
  barraLlena: { height: 8, borderRadius: 4 },
  ok: { color: c.ok },
  aviso: { color: c.aviso },
  peligro: { color: c.peligro },
}));
