import { useState } from "react";
import { Alert, ScrollView, Switch, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { Ajustes, Seccion as DefSeccion, secciones } from "@/src/ajustes";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, Esqueleto, Hoja, HojaFormulario, Pantalla } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Pildora, Seccion } from "@/src/ui";

interface EstadoSalientes {
  bloqueo: string | null;
  minutos_hoy: number;
  cupo_diario: number | null;
}

interface Diagnostico {
  esl_ok: boolean;
  sip_ws_ok: boolean;
  public_ip: string | null;
  trunks: { id: number; name: string; gateway_host: string; state: string | null; contact_ip: string | null; contact_no_alcanzable: boolean }[];
}

interface Mantenimiento {
  last_backup_at: string | null;
  last_backup_ok: boolean | null;
  last_backup_error: string | null;
  backups_count: number;
  backups_size_mb: number;
  recordings_count: number;
  recordings_size_gb: number;
}

type Voz = { id: string; label: string };

function fecha(iso: string | null) {
  if (!iso) return "Nunca";
  return new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function AjustesScreen() {
  const c = useColores();
  const aj = useDatos<Ajustes>("/api/system/settings", { ttl: 10_000 });
  const sal = useDatos<EstadoSalientes>("/api/system/salientes", { ttl: 10_000 });
  const colas = useDatos<{ id: number; name: string }[]>("/api/queues", { ttl: 60_000 });
  const vozEdge = useDatos<Voz[]>("/api/voicebots/tts/voices?provider=edge", { ttl: 300_000 });
  const vozDg = useDatos<Voz[]>("/api/voicebots/tts/voices?provider=deepgram", { ttl: 300_000 });
  const vozEl = useDatos<Voz[]>("/api/voicebots/tts/voices?provider=elevenlabs", { ttl: 300_000 });
  const infra = aj.datos?.puede_infraestructura !== false;
  const mant = useDatos<Mantenimiento>(infra && aj.datos ? "/api/system/maintenance" : null, { ttl: 30_000 });

  const [abierta, setAbierta] = useState<DefSeccion | null>(null);
  const [pausando, setPausando] = useState(false);
  const [colgando, setColgando] = useState(false);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  const [diag, setDiag] = useState<Diagnostico | null>(null);
  const [diagAbierto, setDiagAbierto] = useState(false);
  const [diagCargando, setDiagCargando] = useState(false);
  const [respaldando, setRespaldando] = useState(false);

  const todas = secciones({
    colas: colas.datos ?? [],
    voces: { edge: vozEdge.datos ?? [], deepgram: vozDg.datos ?? [], elevenlabs: vozEl.datos ?? [] },
  }).filter((s) => infra || !s.infra);

  const refrescar = () => {
    invalidar("/api/system");
    aj.recargar();
    sal.recargar();
    if (infra) mant.recargar();
  };

  const guardar = async (s: DefSeccion, v: Record<string, unknown>) => {
    const cuerpo = s.aCuerpo ? s.aCuerpo(v) : v;
    await peticion("/api/system/settings", { method: "PUT", body: cuerpo });
    setAbierta(null);
    setAviso(`${s.titulo}: cambios guardados. Se aplican al vuelo, sin reiniciar nada.`);
    refrescar();
  };

  const pausar = (activar: boolean) => {
    const aplicar = async () => {
      setPausando(true);
      setError("");
      try {
        await peticion("/api/system/settings", { method: "PUT", body: { outbound_paused: activar } });
        exito();
        refrescar();
      } catch (err) {
        fallo();
        setError(err instanceof Error ? err.message : "No se pudo cambiar");
      } finally {
        setPausando(false);
      }
    };
    if (!activar) return aplicar();
    Alert.alert(
      "Pausar las llamadas salientes",
      "Se corta en el acto toda llamada NUEVA hacia afuera: teléfonos, clic para llamar y campañas. Las internas y las entrantes siguen.",
      [
        { text: "Cancelar", style: "cancel" },
        { text: "Pausar", style: "destructive", onPress: aplicar },
      ]
    );
  };

  const colgar = () =>
    Alert.alert("Colgar las salientes en curso", "Se cortan las llamadas que ya están hablando hacia afuera. Las internas y las entrantes no se tocan.", [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Colgar",
        style: "destructive",
        onPress: async () => {
          setColgando(true);
          setError("");
          try {
            await peticion("/api/system/salientes/colgar", { method: "POST" });
            exito();
            setAviso("Salientes en curso colgadas. Pueden tardar unos segundos en cortarse.");
          } catch (err) {
            fallo();
            setError(err instanceof Error ? err.message : "No se pudieron colgar");
          } finally {
            setColgando(false);
          }
        },
      },
    ]);

  const verDiagnostico = async () => {
    setDiagAbierto(true);
    setDiagCargando(true);
    try {
      setDiag(await peticion<Diagnostico>("/api/system/diagnostics"));
    } catch (err) {
      setDiag(null);
      setError(err instanceof Error ? err.message : "No se pudo revisar");
    } finally {
      setDiagCargando(false);
    }
  };

  const respaldar = async () => {
    setRespaldando(true);
    setError("");
    try {
      await peticion("/api/system/maintenance/backup-now", { method: "POST" });
      exito();
      setAviso("Respaldo hecho.");
      mant.recargar();
    } catch (err) {
      fallo();
      setError(err instanceof Error ? err.message : "No se pudo respaldar");
    } finally {
      setRespaldando(false);
    }
  };

  const a = aj.datos;
  const pausadas = !!a?.outbound_paused;

  return (
    <>
      <Pantalla refrescando={aj.refrescando} onRefrescar={refrescar}>
        {aviso ? <Aviso tono="ok" texto={aviso} /> : null}
        {error ? <Aviso texto={error} /> : null}
        {aj.error && !a ? <Aviso texto={aj.error} /> : null}
        {!a && aj.cargando ? <Esqueleto alto={180} /> : null}

        {a ? (
          <>
            <Seccion titulo="Emergencia">
              <View style={{ padding: 14, gap: 12 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <Text style={{ flex: 1, fontSize: 13, color: c.textoSuave, lineHeight: 18 }}>
                    {sal.datos
                      ? `${sal.datos.bloqueo ? `Salientes cortadas: ${sal.datos.bloqueo}.` : "Salientes habilitadas."} Hoy: ${sal.datos.minutos_hoy} min${
                          sal.datos.cupo_diario != null ? ` de ${sal.datos.cupo_diario} del cupo diario` : " (sin cupo diario)"
                        }.`
                      : "Revisando las salientes…"}
                  </Text>
                  <Pildora texto={sal.datos?.bloqueo ? "Cortadas" : "Activas"} tono={sal.datos?.bloqueo ? "peligro" : "ok"} />
                </View>
              </View>
              <FilaMenu
                titulo="Pausar llamadas salientes"
                detalle="Corta toda llamada nueva hacia afuera. Úsalo si sospechas que alguien llama sin permiso."
                icono="emergencia"
                tono="peligro"
                derecha={
                  <Switch
                    value={pausadas}
                    disabled={pausando}
                    onValueChange={pausar}
                    trackColor={{ true: c.peligro, false: c.bordeFuerte }}
                    thumbColor="#fff"
                  />
                }
              />
              <View style={{ padding: 14 }}>
                <Boton titulo="Colgar las salientes en curso" icono="colgar" variante="peligro" cargando={colgando} onPress={colgar} />
              </View>
            </Seccion>

            {infra ? (
              <Seccion titulo="Estado">
                <FilaMenu
                  titulo="Diagnóstico"
                  detalle="Lo que FreeSWITCH y las troncales reportan en vivo"
                  icono="diagnostico"
                  tono="ok"
                  onPress={verDiagnostico}
                  ultima
                />
              </Seccion>
            ) : null}

            <Seccion titulo="Configuración">
              {todas.map((s, i) => (
                <FilaMenu
                  key={s.clave}
                  titulo={s.titulo}
                  detalle={
                    s.clave === "disco" && mant.datos
                      ? `Grabaciones ${mant.datos.recordings_size_gb} GB · respaldos ${(mant.datos.backups_size_mb / 1024).toFixed(2)} GB · último ${fecha(
                          mant.datos.last_backup_at
                        )}`
                      : s.detalle
                  }
                  icono={s.icono}
                  tono={s.tono}
                  derecha={
                    s.clave === "disco" && mant.datos?.last_backup_ok === false ? <Pildora texto="Falló" tono="peligro" /> : undefined
                  }
                  onPress={() => setAbierta(s)}
                  ultima={i === todas.length - 1}
                />
              ))}
            </Seccion>

            {infra ? (
              <Boton titulo="Respaldar ahora" icono="servidor" variante="contorno" cargando={respaldando} onPress={respaldar} />
            ) : null}
            {mant.datos?.last_backup_error ? <Aviso texto={`Último respaldo: ${mant.datos.last_backup_error}`} /> : null}
          </>
        ) : null}
      </Pantalla>

      <HojaFormulario
        visible={!!abierta}
        titulo={abierta?.titulo ?? ""}
        campos={abierta?.campos ?? []}
        inicial={{ ...(a && abierta ? (abierta.aFormulario ? abierta.aFormulario(a) : a) : {}), __infra: infra }}
        onGuardar={(v) => guardar(abierta!, v)}
        onCerrar={() => setAbierta(null)}
      />

      <Hoja visible={diagAbierto} titulo="Diagnóstico" onCerrar={() => setDiagAbierto(false)}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 12 }}>
          {diagCargando && !diag ? <Esqueleto alto={140} /> : null}
          {diag ? (
            <>
              <Seccion>
                <FilaMenu
                  titulo="FreeSWITCH (ESL)"
                  icono="servidor"
                  derecha={<Pildora texto={diag.esl_ok ? "Responde" : "No responde"} tono={diag.esl_ok ? "ok" : "peligro"} />}
                />
                <FilaMenu
                  titulo="WebSocket del softphone"
                  icono="extension"
                  derecha={<Pildora texto={diag.sip_ws_ok ? "Escuchando" : "No responde"} tono={diag.sip_ws_ok ? "ok" : "peligro"} />}
                />
                <FilaMenu titulo="IP pública" icono="mundo" valor={diag.public_ip ?? "—"} ultima />
              </Seccion>
              {diag.trunks.length ? (
                <Seccion titulo="Troncales">
                  {diag.trunks.map((t, i) => (
                    <FilaMenu
                      key={t.id}
                      titulo={t.name}
                      detalle={`${t.gateway_host}${t.contact_ip ? ` · anuncia ${t.contact_ip}` : ""}`}
                      icono="troncal"
                      tono={t.contact_no_alcanzable ? "peligro" : "neutro"}
                      derecha={<Pildora texto={t.state ?? "Sin registrar"} tono={t.state === "REGED" ? "ok" : "peligro"} />}
                      ultima={i === diag.trunks.length - 1}
                    />
                  ))}
                </Seccion>
              ) : null}
              {diag.trunks.some((t) => t.contact_no_alcanzable) ? (
                <Aviso
                  tono="aviso"
                  texto="Una troncal le anuncia al proveedor una IP privada o de CGNAT: se ve «REGED», pero ninguna llamada entrante podrá completarse. Compárala con la IP pública y corrige la configuración de FreeSWITCH."
                />
              ) : null}
              <Boton titulo="Volver a revisar" icono="refrescar" variante="suave" cargando={diagCargando} onPress={verDiagnostico} />
            </>
          ) : null}
        </ScrollView>
      </Hoja>

    </>
  );
}
