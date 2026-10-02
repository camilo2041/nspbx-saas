import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { AvisoHorario, avance, Campana, camposCampana, cuerpoCampana, ESTADO_CAMPANA, inicialCampana, INTENCIONES } from "@/src/campanas";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, EstadoVacio, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { Icono } from "@/src/Icono";
import { crearEstilos, useColores } from "@/src/tema";
import { BarraProgreso, Boton, CajaIcono, Pildora, Tarjeta } from "@/src/ui";

export default function Campanas() {
  const router = useRouter();
  const c = useColores();
  const e = useEstilos();
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Campana[]>("/api/campaigns/list/detail", { ttl: 10_000 });
  const troncales = useDatos<{ id: number; name: string }[]>("/api/trunks", { ttl: 60_000 });
  const bots = useDatos<{ id: number; name: string }[]>("/api/voicebots", { ttl: 60_000 });
  const [creando, setCreando] = useState(false);

  const crear = async (v: Record<string, unknown>) => {
    const nueva = await peticion<Campana>("/api/campaigns", { method: "POST", body: cuerpoCampana(v) });
    invalidar("/api/campaigns");
    setCreando(false);
    recargar();
    router.push({ pathname: "/administrar/campana/[id]", params: { id: String(nueva.id) } });
  };

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <AvisoHorario />
        <Boton titulo="Nueva campaña" icono="agregar" onPress={() => setCreando(true)} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio icono="campana" titulo="No hay campañas" texto="Crea la primera para lanzar una marcación masiva con tu voizbot." />
        ) : null}
        {(datos ?? []).map((camp) => {
          const est = ESTADO_CAMPANA[camp.status] ?? { texto: camp.status, tono: "neutro" as const };
          const pct = avance(camp.stats);
          const enCurso = camp.status === "running";
          const intencion = INTENCIONES.find((i) => i.valor === (camp.ai_intent || "confirmar"))?.etiqueta;
          return (
            <Tarjeta key={camp.id} style={{ gap: 12 }} onPress={() => router.push({ pathname: "/administrar/campana/[id]", params: { id: String(camp.id) } })}>
              <View style={e.fila}>
                <CajaIcono icono={camp.ai_intent === "cobranza" ? "dinero" : "calendario"} tono={enCurso ? "ok" : "marca"} />
                <View style={{ flex: 1 }}>
                  <Text style={e.nombre} numberOfLines={1}>
                    {camp.name}
                  </Text>
                  <Text style={e.detalle} numberOfLines={1}>
                    {intencion}
                    {camp.voicebot_name ? ` · ${camp.voicebot_name}` : ""}
                  </Text>
                </View>
                <Pildora texto={est.texto} tono={est.tono} />
              </View>
              <BarraProgreso valor={pct} tono={enCurso ? "ok" : "marca"} />
              <View style={e.fila}>
                <Text style={e.detalle}>
                  {camp.stats?.total ?? 0} números · {camp.stats?.pending ?? 0} pendientes
                  {enCurso && camp.stats?.dialing ? ` · ${camp.stats.dialing} en llamada` : ""}
                </Text>
                <View style={{ flex: 1 }} />
                <Text style={e.pct}>{pct}%</Text>
                <Icono nombre="derecha" tam={16} color={c.placeholder} />
              </View>
            </Tarjeta>
          );
        })}
      </Pantalla>

      <HojaFormulario
        visible={creando}
        titulo="Nueva campaña"
        campos={camposCampana(troncales.datos ?? [], bots.datos ?? [])}
        inicial={inicialCampana(null)}
        textoGuardar="Crear campaña"
        onGuardar={crear}
        onCerrar={() => setCreando(false)}
      />
    </>
  );
}

const useEstilos = crearEstilos((c) => ({
  fila: { flexDirection: "row", alignItems: "center", gap: 12 },
  nombre: { fontSize: 16, fontWeight: "700", color: c.texto },
  detalle: { fontSize: 12.5, color: c.textoSecundario },
  pct: { fontSize: 13, fontWeight: "700", color: c.texto, fontVariant: ["tabular-nums"] },
}));
