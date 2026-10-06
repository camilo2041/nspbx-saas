/**
 * Lo del Dashboard del panel que no son llamadas: cuánto hay configurado,
 * el estado del motor telefónico y los recursos del servidor. Cada parte
 * se pide solo si el rol la puede ver (las mismas rutas que el backend le
 * negaría con 403).
 */
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { Text, View } from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { useDatos } from "@/src/datos";
import { useColores } from "@/src/tema";
import { BarraProgreso, FilaMenu, Pildora, Seccion, Tono } from "@/src/ui";

interface Recursos {
  cpu: { porcentaje: number; nucleos: number };
  memoria: { total_gb: number; usado_gb: number; porcentaje: number };
  discos: { nombre: string; total_gb: number; usado_gb: number; libre_gb: number; porcentaje: number }[];
}

const tonoUso = (p: number): Tono => (p >= 90 ? "peligro" : p >= 75 ? "aviso" : "ok");

function Medidor({ titulo, porcentaje, detalle }: { titulo: string; porcentaje: number; detalle: string }) {
  const c = useColores();
  return (
    <View style={{ gap: 6, paddingHorizontal: 14, paddingVertical: 10 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: 14, fontWeight: "600", color: c.texto }}>{titulo}</Text>
        <Text style={{ fontSize: 14, fontWeight: "700", color: c.texto, fontVariant: ["tabular-nums"] }}>{Math.round(porcentaje)}%</Text>
      </View>
      <BarraProgreso valor={porcentaje} tono={tonoUso(porcentaje)} />
      <Text style={{ fontSize: 12, color: c.textoSecundario }}>{detalle}</Text>
    </View>
  );
}

export function ResumenCentral() {
  const router = useRouter();
  const { puede, tieneModulo } = useAuth();
  const veInfra = puede("telefonia:gestionar") && tieneModulo("pbx");
  const veBots = puede("voizbots:ver") && tieneModulo("voicebot");
  const veCampanas = puede("campanas:gestionar") && tieneModulo("voicebot");
  const veAjustes = puede("ajustes:gestionar");

  const troncales = useDatos<unknown[]>(veInfra ? "/api/trunks" : null, { ttl: 60_000 });
  const extensiones = useDatos<unknown[]>(veInfra ? "/api/extensions" : null, { ttl: 60_000 });
  const bots = useDatos<unknown[]>(veBots ? "/api/voicebots" : null, { ttl: 60_000 });
  const campanas = useDatos<{ status: string }[]>(veCampanas ? "/api/campaigns" : null, { ttl: 15_000 });
  const motor = useDatos<Record<string, string | number>>(veAjustes ? "/api/system/status" : null, { ttl: 15_000 });
  const recursos = useDatos<Recursos>(veAjustes ? "/api/system/recursos" : null, { ttl: 5_000 });

  // CPU y memoria cambian rápido: se refrescan solos mientras la pantalla está abierta.
  useEffect(() => {
    if (!veAjustes) return;
    const t = setInterval(() => recursos.recargar(), 8_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [veAjustes]);

  const cuentas = [
    veInfra && { titulo: "Proveedores", valor: troncales.datos?.length, icono: "troncal" as const, ruta: "/administrar/troncales" },
    veInfra && { titulo: "Extensiones", valor: extensiones.datos?.length, icono: "extension" as const, ruta: "/administrar/extensiones" },
    veBots && { titulo: "Voizbots", valor: bots.datos?.length, icono: "bot" as const, ruta: "/administrar/bots" },
    veCampanas && {
      titulo: "Campañas",
      valor: campanas.datos?.length,
      detalle: campanas.datos ? `${campanas.datos.filter((x) => x.status === "running").length} en curso` : undefined,
      icono: "campana" as const,
      ruta: "/administrar/campanas",
    },
  ].filter(Boolean) as { titulo: string; valor?: number; detalle?: string; icono: "troncal" | "extension" | "bot" | "campana"; ruta: string }[];

  const r = recursos.datos;

  return (
    <>
      {cuentas.length ? (
        <Seccion titulo="Tu central">
          {cuentas.map((x, i) => (
            <FilaMenu
              key={x.titulo}
              titulo={x.titulo}
              detalle={x.detalle}
              icono={x.icono}
              tono="marca"
              valor={x.valor === undefined ? "…" : String(x.valor)}
              onPress={() => router.push(x.ruta as never)}
              ultima={i === cuentas.length - 1}
            />
          ))}
        </Seccion>
      ) : null}

      {veAjustes && (motor.datos || motor.error) ? (
        <Seccion titulo="Motor telefónico">
          {motor.datos ? (
            <>
              <FilaMenu titulo="FreeSWITCH" icono="servidor" derecha={<Pildora texto="Responde" tono="ok" />} />
              {motor.datos.current_sessions !== undefined ? (
                <FilaMenu
                  titulo="Llamadas activas"
                  icono="enLlamada"
                  valor={`${motor.datos.current_sessions}${motor.datos.max_sessions ? ` de ${motor.datos.max_sessions}` : ""}`}
                />
              ) : null}
              {motor.datos.uptime ? <FilaMenu titulo="Encendido hace" icono="horario" valor={String(motor.datos.uptime)} /> : null}
              {motor.datos.version ? <FilaMenu titulo="Versión" icono="info" valor={String(motor.datos.version)} ultima /> : null}
            </>
          ) : (
            <FilaMenu titulo="FreeSWITCH" detalle={motor.error} icono="servidor" tono="peligro" derecha={<Pildora texto="No responde" tono="peligro" />} ultima />
          )}
        </Seccion>
      ) : null}

      {r ? (
        <Seccion titulo="Recursos del servidor">
          <Medidor titulo="CPU" porcentaje={r.cpu.porcentaje} detalle={`${r.cpu.nucleos} núcleos`} />
          <Medidor titulo="Memoria" porcentaje={r.memoria.porcentaje} detalle={`${r.memoria.usado_gb} de ${r.memoria.total_gb} GB`} />
          {r.discos.map((d) => (
            <Medidor key={d.nombre} titulo={`Disco · ${d.nombre}`} porcentaje={d.porcentaje} detalle={`${d.libre_gb} GB libres de ${d.total_gb} GB`} />
          ))}
        </Seccion>
      ) : null}
    </>
  );
}
