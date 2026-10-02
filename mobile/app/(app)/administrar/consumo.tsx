import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, Buscador, Esqueleto, Fila, Pantalla } from "@/src/gestion";
import { GraficaBarras } from "@/src/GraficaBarras";
import { radios, useColores } from "@/src/tema";
import { Boton, FilaMenu, Metrica, Pildora, Seccion, Segmentado, Tarjeta, Tono } from "@/src/ui";

// Mismos colores de serie que el panel (validados para daltonismo en claro y oscuro).
const C_VOZ = "#ea580c";
const C_MODELO = "#0284c7";

interface Proveedor {
  key: string;
  label: string;
  role: string;
  cost_usd: number;
  share: number;
  tts_chars: number;
  stt_seconds: number;
  tokens: number;
  requests: number;
}

interface Resumen {
  calls: number;
  resolved: number;
  containment_rate: number;
  turns: number;
  cost_usd: number;
  cost_per_call: number;
  cost_per_resolved: number;
  avg_turns: number;
  avg_duration: number;
  cost_per_minute: number;
  providers: Proveedor[];
}

interface Dia extends Record<string, unknown> {
  date: string;
  calls: number;
  cost_voz: number;
  cost_modelo: number;
  cost_usd: number;
}

interface Conversacion {
  id: number;
  phone: string | null;
  started_at: string;
  duration_seconds: number;
  turns: number;
  cost_voz: number;
  cost_modelo: number;
  cost_usd: number;
  outcome: string;
  resolved: boolean;
}

const RESULTADO: Record<string, { texto: string; tono: Tono }> = {
  completed: { texto: "Completada", tono: "ok" },
  no_speech: { texto: "Sin respuesta", tono: "aviso" },
  max_turns: { texto: "Sin cerrar", tono: "aviso" },
  hangup: { texto: "Colgó", tono: "neutro" },
  error: { texto: "Error", tono: "peligro" },
};

const usd = (n: number) => `US$ ${n.toFixed(n < 1 ? 3 : 2)}`;
const miles = (n: number) => n.toLocaleString("es-CO");
const dur = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const diaCorto = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("es-CO", { day: "numeric", month: "short" });
const POR_PAGINA = 25;

export default function Consumo() {
  const c = useColores();
  const [dias, setDias] = useState<"7" | "14" | "30">("14");
  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [limite, setLimite] = useState(POR_PAGINA);

  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const resumen = useDatos<Resumen>(`/api/ai-usage/summary?days=${dias}`, { ttl: 30_000 });
  const diario = useDatos<Dia[]>(`/api/ai-usage/daily?days=${dias}`, { ttl: 30_000 });
  const conv = useDatos<Conversacion[]>(`/api/ai-usage/calls?limit=${limite}${busqueda ? `&search=${encodeURIComponent(busqueda)}` : ""}`, {
    ttl: 30_000,
  });
  const r = resumen.datos;

  const refrescar = () => {
    resumen.recargar();
    diario.recargar();
    conv.recargar();
  };

  return (
    <Pantalla refrescando={resumen.refrescando} onRefrescar={refrescar}>
      <Segmentado
        valor={dias}
        onChange={setDias}
        opciones={[
          { valor: "7", etiqueta: "7 días" },
          { valor: "14", etiqueta: "14 días" },
          { valor: "30", etiqueta: "30 días" },
        ]}
      />
      {resumen.sinConexion ? <AvisoSinConexion /> : null}
      {resumen.error && !r ? <Aviso texto={resumen.error} /> : null}
      {r && r.calls === 0 ? (
        <Aviso
          tono="info"
          texto="Todavía no hay conversaciones con IA en este rango, así que todo aparece en cero. Cada llamada del voizbot queda medida acá: voz, transcripción, tokens del modelo y si resolvió una gestión."
        />
      ) : null}

      {!r && resumen.cargando ? <Esqueleto alto={220} /> : null}
      {r ? (
        <>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Llamadas con IA" valor={miles(r.calls)} icono="bot" tono="info" />
            <Metrica etiqueta={`Costo · ${dias} días`} valor={usd(r.cost_usd)} icono="dinero" tono="marca" detalle={`${usd(r.cost_per_call)} por llamada`} />
          </View>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Por gestión resuelta" valor={usd(r.cost_per_resolved)} icono="ok" tono="ok" detalle={`${miles(r.resolved)} resueltas`} />
            <Metrica
              etiqueta="Contención"
              valor={`${Math.round(r.containment_rate * 100)}%`}
              icono="tendencia"
              tono="ok"
              detalle="Resueltas sin pasar a un humano"
            />
          </View>
        </>
      ) : null}

      <Tarjeta style={{ gap: 6 }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>Costo diario</Text>
        <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 16, marginBottom: 4 }}>
          Estimado con las tarifas de Ajustes; las unidades medidas son exactas.
        </Text>
        {diario.datos ? (
          <GraficaBarras
            datos={diario.datos}
            series={[
              { clave: "cost_voz", etiqueta: "Voz y transcripción", color: C_VOZ },
              { clave: "cost_modelo", etiqueta: "Modelo", color: C_MODELO },
            ]}
            etiquetaX={(d) => diaCorto(d.date)}
            formato={usd}
          />
        ) : (
          <Esqueleto alto={160} />
        )}
      </Tarjeta>

      <Tarjeta style={{ gap: 6 }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>Llamadas por día</Text>
        {diario.datos ? (
          <GraficaBarras
            datos={diario.datos}
            series={[{ clave: "calls", etiqueta: "Llamadas", color: C_MODELO }]}
            etiquetaX={(d) => diaCorto(d.date)}
            formato={(n) => miles(n)}
            alto={110}
          />
        ) : (
          <Esqueleto alto={120} />
        )}
      </Tarjeta>

      {r ? (
        <Seccion titulo="Conversación">
          <FilaMenu titulo="Turnos de conversación" icono="audio" valor={miles(r.turns)} />
          <FilaMenu titulo="Turnos por llamada" icono="tendencia" valor={String(r.avg_turns)} />
          <FilaMenu titulo="Duración media" icono="horario" valor={dur(r.avg_duration)} />
          <FilaMenu titulo="Costo por minuto" icono="dinero" valor={usd(r.cost_per_minute)} ultima />
        </Seccion>
      ) : null}

      {r?.providers.length ? (
        <Seccion titulo="Por proveedor">
          {r.providers.map((p, i) => {
            const unidades = [
              p.tts_chars ? `${miles(p.tts_chars)} caracteres` : "",
              p.stt_seconds ? `${miles(p.stt_seconds)} s transcritos` : "",
              p.tokens ? `${miles(p.tokens)} tokens` : "",
              p.requests ? `${miles(p.requests)} consultas` : "",
            ].filter(Boolean);
            return (
              <View key={p.key} style={{ padding: 14, gap: 8, borderBottomWidth: i === r.providers.length - 1 ? 0 : 1, borderBottomColor: c.borde }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <View
                    style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: p.role.toLowerCase().includes("modelo") ? C_MODELO : C_VOZ }}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: 15, fontWeight: "600", color: c.texto }}>{p.label}</Text>
                    <Text style={{ fontSize: 12, color: c.textoSecundario }}>{p.role}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto, fontVariant: ["tabular-nums"] }}>{usd(p.cost_usd)}</Text>
                    <Text style={{ fontSize: 12, color: c.textoSecundario }}>{Math.round(p.share * 100)}% del total</Text>
                  </View>
                </View>
                <View style={{ height: 6, borderRadius: radios.chico, backgroundColor: c.superficie3, overflow: "hidden" }}>
                  <View
                    style={{
                      height: 6,
                      width: `${Math.round(p.share * 100)}%`,
                      backgroundColor: p.role.toLowerCase().includes("modelo") ? C_MODELO : C_VOZ,
                    }}
                  />
                </View>
                <Text style={{ fontSize: 12, color: c.textoSecundario }}>
                  {unidades.join(" · ")}
                  {p.key === "edge" ? " · voz gratuita: no suma al costo" : ""}
                </Text>
              </View>
            );
          })}
        </Seccion>
      ) : null}

      <Seccion titulo="Conversaciones" sinTarjeta>
        <View style={{ gap: 8 }}>
          <Buscador valor={q} onChange={setQ} placeholder="Buscar teléfono" />
          {conv.datos && conv.datos.length === 0 ? (
            <Text style={{ fontSize: 13, color: c.textoSecundario, textAlign: "center", paddingVertical: 12 }}>
              {busqueda ? "Ninguna conversación con ese teléfono." : "Sin conversaciones todavía."}
            </Text>
          ) : null}
          {(conv.datos ?? []).map((x) => {
            const res = RESULTADO[x.outcome] ?? { texto: x.outcome, tono: "neutro" as const };
            return (
              <Fila
                key={x.id}
                titulo={x.phone ?? "Sin número"}
                subtitulo={`${new Date(x.started_at).toLocaleString("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · ${dur(
                  x.duration_seconds
                )} · ${x.turns} turnos · ${usd(x.cost_usd)}`}
                derecha={<Pildora texto={res.texto} tono={res.tono} />}
              />
            );
          })}
          {conv.datos && conv.datos.length >= limite ? (
            <Boton titulo="Cargar más" variante="suave" onPress={() => setLimite((l) => Math.min(l + POR_PAGINA, 500))} />
          ) : null}
        </View>
      </Seccion>
    </Pantalla>
  );
}
