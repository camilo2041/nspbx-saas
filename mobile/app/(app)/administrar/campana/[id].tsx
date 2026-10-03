import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Alert, ScrollView, Text, TextInput, View } from "react-native";

import { peticion } from "@/src/api/client";
import {
  AvisoHorario,
  avance,
  Campana,
  camposCampana,
  columnasDe,
  cuerpoCampana,
  ESTADO_CAMPANA,
  ESTADO_NUMERO,
  Estadisticas,
  inicialCampana,
  INTENCIONES,
  leerNumeros,
  NumeroCampana,
  ResultadoCarga,
} from "@/src/campanas";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, Buscador, CampoDef, EstadoVacio, Esqueleto, Fila, FiltroChips, Hoja, HojaFormulario, Pantalla } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { AgentesCampana } from "@/src/AgentesCampana";
import { ListasCampana } from "@/src/ListasCampana";
import { radios, useColores } from "@/src/tema";
import { BarraProgreso, Boton, FilaMenu, Metrica, Pildora, Seccion, Tarjeta } from "@/src/ui";

const POR_PAGINA = 50;
const CAMPOS_NUMERO: CampoDef[] = [{ clave: "phone", etiqueta: "Teléfono", tipo: "telefono" }];

export default function DetalleCampana() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const c = useColores();

  const camp = useDatos<Campana>(`/api/campaigns/${id}`, { ttl: 5_000 });
  const est = useDatos<Estadisticas>(`/api/campaigns/${id}/stats`, { ttl: 3_000 });
  const troncales = useDatos<{ id: number; name: string }[]>("/api/trunks", { ttl: 60_000 });
  const bots = useDatos<{ id: number; name: string }[]>("/api/voicebots", { ttl: 60_000 });

  const [q, setQ] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [estado, setEstado] = useState("");
  const [limite, setLimite] = useState(POR_PAGINA);
  const qs = new URLSearchParams({ limit: String(limite) });
  if (busqueda) qs.set("search", busqueda);
  if (estado) qs.set("estado", estado);
  const nums = useDatos<NumeroCampana[]>(`/api/campaigns/${id}/numbers?${qs}`, { ttl: 3_000 });

  const [trabajando, setTrabajando] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [editando, setEditando] = useState(false);
  const [cargarAbierto, setCargarAbierto] = useState(false);
  const [pegado, setPegado] = useState("");
  const [resultado, setResultado] = useState<ResultadoCarga | null>(null);
  const [errorCarga, setErrorCarga] = useState("");
  const [numero, setNumero] = useState<NumeroCampana | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setBusqueda(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  const campana = camp.datos;
  const stats = est.datos;
  const enCurso = campana?.status === "running";

  // En curso, el avance se actualiza solo cada 5 segundos.
  useEffect(() => {
    if (!enCurso) return;
    const t = setInterval(() => {
      est.recargar();
      nums.recargar();
      camp.recargar();
    }, 5_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enCurso]);

  const todo = () => {
    invalidar("/api/campaigns");
    camp.recargar();
    est.recargar();
    nums.recargar();
  };

  const accion = async (nombre: "start" | "stop" | "retry") => {
    setTrabajando(nombre);
    setError("");
    try {
      await peticion(`/api/campaigns/${id}/${nombre}`, { method: "POST" });
      exito();
      todo();
    } catch (err) {
      fallo();
      setError(err instanceof Error ? err.message : "No se pudo completar la acción");
    } finally {
      setTrabajando(null);
    }
  };

  const guardar = async (v: Record<string, unknown>) => {
    await peticion(`/api/campaigns/${id}`, { method: "PUT", body: cuerpoCampana(v) });
    setEditando(false);
    todo();
  };

  const eliminar = () =>
    Alert.alert("Eliminar campaña", `Se borrará "${campana?.name}" con todos sus números. Las citas y deudas que cargó no se tocan.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/campaigns/${id}`, { method: "DELETE" });
            exito();
            invalidar("/api/campaigns");
            router.back();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const vaciar = () =>
    Alert.alert("Vaciar la lista", `Se quitarán los ${stats?.total ?? 0} números de la campaña. Las citas que ya se cargaron en la Agenda no se tocan.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Vaciar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/campaigns/${id}/numbers`, { method: "DELETE" });
            exito();
            todo();
          } catch (err) {
            Alert.alert("No se pudo vaciar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const columnas = columnasDe(campana?.message_template);

  const subir = async () => {
    const { filas, error: errorLectura } = leerNumeros(pegado, columnas);
    if (errorLectura) {
      setErrorCarga(errorLectura);
      return;
    }
    if (!filas.length) return;
    setTrabajando("cargar");
    setErrorCarga("");
    try {
      setResultado(await peticion<ResultadoCarga>(`/api/campaigns/${id}/numbers`, { method: "POST", body: { numbers: filas } }));
      exito();
      todo();
    } catch (err) {
      fallo();
      setErrorCarga(err instanceof Error ? err.message : "No se pudieron cargar los números");
    } finally {
      setTrabajando(null);
    }
  };

  const guardarNumero = async (v: Record<string, unknown>) => {
    if (!numero) return;
    await peticion(`/api/campaigns/${id}/numbers/${numero.id}`, { method: "PUT", body: { phone: String(v.phone ?? "").trim() } });
    setNumero(null);
    todo();
  };

  const quitarNumero = () => {
    if (!numero) return;
    const n = numero;
    Alert.alert("Quitar número", `Se quitará ${n.phone} de la campaña.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Quitar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/campaigns/${id}/numbers/${n.id}`, { method: "DELETE" });
            exito();
            setNumero(null);
            todo();
          } catch (err) {
            Alert.alert("No se pudo quitar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  if (!campana) {
    return (
      <Pantalla>
        <Stack.Screen options={{ title: "Campaña" }} />
        {camp.error ? <Aviso texto={camp.error} /> : <Esqueleto alto={160} />}
      </Pantalla>
    );
  }

  const e = ESTADO_CAMPANA[campana.status] ?? { texto: campana.status, tono: "neutro" as const };
  const pct = avance(stats);
  const reintentables = (stats?.done ?? 0) + (stats?.failed ?? 0) + (stats?.busy ?? 0) + (stats?.noanswer ?? 0);
  const troncal = troncales.datos?.find((t) => t.id === campana.trunk_id)?.name;
  const bot = bots.datos?.find((b) => b.id === campana.voicebot_id)?.name;
  const intencion = INTENCIONES.find((i) => i.valor === (campana.ai_intent || "confirmar"))?.etiqueta;

  return (
    <>
      <Stack.Screen options={{ title: campana.name }} />
      <Pantalla refrescando={camp.refrescando} onRefrescar={todo}>
        <AvisoHorario />
        <Tarjeta style={{ gap: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <Text style={{ flex: 1, fontSize: 13, color: c.textoSecundario }}>{intencion}</Text>
            <Pildora texto={e.texto} tono={e.tono} />
          </View>
          <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8 }}>
            <Text style={{ fontSize: 34, fontWeight: "800", color: c.texto, fontVariant: ["tabular-nums"] }}>{pct}%</Text>
            <Text style={{ fontSize: 13, color: c.textoSecundario, marginBottom: 6 }}>gestionado de {stats?.total ?? 0} números</Text>
          </View>
          <BarraProgreso valor={pct} tono={enCurso ? "ok" : "marca"} alto={10} />
          {stats && (campana.max_calls_per_day || campana.max_minutes_per_day) ? (
            <Text style={{ fontSize: 12.5, color: c.textoSecundario }}>
              Hoy: {stats.llamadas_hoy ?? 0}
              {campana.max_calls_per_day ? ` de ${campana.max_calls_per_day}` : ""} llamadas · {stats.minutos_hoy ?? 0}
              {campana.max_minutes_per_day ? ` de ${campana.max_minutes_per_day}` : ""} min
            </Text>
          ) : null}
        </Tarjeta>

        {stats?.tope_alcanzado ? <Aviso tono="aviso" texto={stats.tope_alcanzado} /> : null}
        {(stats?.en_espera ?? 0) > 0 || (stats?.no_llamar ?? 0) > 0 ? (
          <Aviso
            tono="info"
            texto={[
              (stats?.en_espera ?? 0) > 0 ? `${stats?.en_espera} pendiente(s) esperando su próximo intento o con la lista en pausa` : "",
              (stats?.no_llamar ?? 0) > 0 ? `${stats?.no_llamar} en la lista de no llamar (no se marcan)` : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          />
        ) : null}
        {error ? <Aviso texto={error} /> : null}

        <View style={{ flexDirection: "row", gap: 10 }}>
          {enCurso ? (
            <Boton titulo="Detener" icono="detener" variante="peligro" style={{ flex: 1 }} cargando={trabajando === "stop"} onPress={() => accion("stop")} />
          ) : (
            <Boton
              titulo="Iniciar"
              icono="reproducir"
              variante="ok"
              style={{ flex: 1 }}
              cargando={trabajando === "start"}
              deshabilitado={!stats?.pending}
              onPress={() => accion("start")}
            />
          )}
          {!enCurso && reintentables > 0 ? (
            <Boton titulo="Reintentar" icono="refrescar" variante="suave" style={{ flex: 1 }} cargando={trabajando === "retry"} onPress={() => accion("retry")} />
          ) : null}
        </View>

        <View style={{ flexDirection: "row", gap: 10 }}>
          <Metrica etiqueta="Pendientes" valor={stats?.pending ?? "—"} icono="horario" tono="aviso" />
          <Metrica etiqueta="En llamada" valor={stats?.dialing ?? "—"} icono="enLlamada" tono="info" />
        </View>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Metrica etiqueta="Completados" valor={(stats?.done ?? 0) + (stats?.answered ?? 0)} icono="ok" tono="ok" />
          <Metrica
            etiqueta="Sin éxito"
            valor={(stats?.failed ?? 0) + (stats?.busy ?? 0) + (stats?.noanswer ?? 0)}
            icono="perdida"
            tono="peligro"
          />
        </View>

        {stats?.predictivo ? (
          <Seccion titulo={`Marcador de hoy${stats.predictivo.nivel != null ? ` · ${stats.predictivo.nivel} por agente libre` : ""}`} sinTarjeta>
            <View style={{ gap: 10 }}>
              <View style={{ flexDirection: "row", gap: 10 }}>
                <Metrica etiqueta="Intentos" valor={stats.predictivo.intentos} icono="enLlamada" tono="info" />
                <Metrica etiqueta="Contestadas" valor={stats.predictivo.contestadas} icono="ok" tono="ok" />
              </View>
              <View style={{ flexDirection: "row", gap: 10 }}>
                <Metrica etiqueta="Con agente" valor={stats.predictivo.asignadas} icono="usuarios" tono="marca" />
                <Metrica
                  etiqueta="Abandono"
                  valor={stats.predictivo.abandono_pct == null ? "—" : `${stats.predictivo.abandono_pct} %`}
                  icono="perdida"
                  tono={stats.predictivo.abandono_pct != null && stats.predictivo.abandono_pct > (campana.abandono_objetivo ?? 3) ? "peligro" : "ok"}
                  detalle={`${stats.predictivo.abandonadas} hoy`}
                />
              </View>
              <Text style={{ fontSize: 13, color: c.textoSecundario }}>
                Ahora: {stats.predictivo.timbrando} timbrando · {stats.predictivo.en_espera} esperando agente
              </Text>
            </View>
          </Seccion>
        ) : null}

        {campana.metodo && campana.metodo !== "voizbot" ? <AgentesCampana campaignId={String(id)} /> : null}

        <ListasCampana campaignId={String(id)} version={stats?.total ?? 0} onCambio={() => est.recargar()} />

        <Seccion titulo="Configuración">
          <FilaMenu titulo="Troncal" icono="troncal" valor={troncal ?? "Sin troncal"} />
          <FilaMenu titulo="Voizbot" icono="bot" valor={bot ?? "Sin voizbot"} />
          <FilaMenu titulo="Llamadas a la vez" icono="usuarios" valor={String(campana.max_concurrency)} />
          <FilaMenu titulo="Reintentos" icono="refrescar" valor={String(campana.retries)} />
          <FilaMenu titulo="Editar campaña" icono="editar" tono="marca" onPress={() => setEditando(true)} />
          <FilaMenu titulo="Eliminar campaña" icono="eliminar" peligro onPress={eliminar} ultima />
        </Seccion>

        <Seccion
          titulo={`Números (${stats?.total ?? 0})`}
          sinTarjeta
          accion={
            (stats?.total ?? 0) > 0 && !enCurso ? <Boton titulo="Vaciar" variante="texto" chico onPress={vaciar} /> : undefined
          }
        >
          <View style={{ gap: 10 }}>
            <Boton
              titulo="Agregar números"
              icono="agregar"
              variante="contorno"
              onPress={() => {
                setResultado(null);
                setErrorCarga("");
                setCargarAbierto(true);
              }}
            />
            <Buscador valor={q} onChange={setQ} placeholder="Buscar teléfono o dato" />
            <FiltroChips
              valor={estado}
              onChange={setEstado}
              opciones={[
                { valor: "", etiqueta: "Todos" },
                ...["pending", "dialing", "done", "failed", "busy", "noanswer"].map((k) => ({ valor: k, etiqueta: ESTADO_NUMERO[k].texto })),
              ]}
            />
            {nums.datos && nums.datos.length === 0 ? (
              <EstadoVacio icono="contactos" titulo={busqueda || estado ? "Ningún número coincide" : "Sin números cargados"} />
            ) : null}
            {(nums.datos ?? []).map((n) => {
              const en = ESTADO_NUMERO[n.status] ?? { texto: n.status, tono: "neutro" as const };
              const datos = Object.entries(n.vars)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ");
              return (
                <Fila
                  key={n.id}
                  titulo={n.phone}
                  subtitulo={n.last_error || datos || `${n.attempts} intento(s)`}
                  derecha={<Pildora texto={en.texto} tono={en.tono} />}
                  onPress={() => setNumero(n)}
                />
              );
            })}
            {nums.datos && nums.datos.length >= limite ? (
              <Boton titulo="Cargar más" variante="suave" onPress={() => setLimite((l) => Math.min(l + POR_PAGINA, 500))} />
            ) : null}
          </View>
        </Seccion>
      </Pantalla>

      <HojaFormulario
        visible={editando}
        titulo="Editar campaña"
        campos={camposCampana(troncales.datos ?? [], bots.datos ?? [])}
        inicial={inicialCampana(campana)}
        onGuardar={guardar}
        onCerrar={() => setEditando(false)}
      />

      <HojaFormulario
        visible={!!numero}
        titulo={numero?.phone ?? ""}
        campos={CAMPOS_NUMERO}
        inicial={{ phone: numero?.phone ?? "" }}
        onGuardar={guardarNumero}
        onCerrar={() => setNumero(null)}
        onEliminar={quitarNumero}
      />

      <Hoja visible={cargarAbierto} titulo="Agregar números" onCerrar={() => setCargarAbierto(false)}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 12 }} keyboardShouldPersistTaps="handled">
          <Aviso
            tono="ok"
            texto={
              columnas.length
                ? `Una línea por número: teléfono; ${columnas.join("; ")}. Con "," también sirve, como lo exporte Excel.`
                : "Un teléfono por línea. Si quieres un saludo con el nombre de cada cliente, edita la campaña y escribe algo como «Hola {cliente}» en el mensaje."
            }
          />
          <TextInput
            value={pegado}
            onChangeText={setPegado}
            multiline
            textAlignVertical="top"
            autoCapitalize="none"
            autoCorrect={false}
            placeholder={columnas.length ? `3011234567; ${columnas.map(() => "…").join("; ")}` : "3011234567\n3017654321"}
            placeholderTextColor={c.placeholder}
            selectionColor={c.marca}
            style={{
              minHeight: 160,
              borderWidth: 1,
              borderColor: c.bordeFuerte,
              borderRadius: radios.medio,
              padding: 12,
              fontSize: 15,
              fontFamily: "monospace",
              color: c.texto,
              backgroundColor: c.superficie,
            }}
          />
          {errorCarga ? <Aviso texto={errorCarga} /> : null}
          {resultado ? (
            <Aviso
              tono={resultado.bloqueados?.length || resultado.agenda_omitidas.length ? "aviso" : "ok"}
              texto={[
                `${resultado.added} agregado(s)`,
                resultado.updated ? `${resultado.updated} actualizado(s)` : "",
                resultado.agenda_creadas ? `${resultado.agenda_creadas} cita(s) en la Agenda` : "",
                ...(resultado.bloqueados ?? []).map((b) => `${b.phone}: ${b.motivo}`),
                ...resultado.agenda_omitidas.map((o) => `${o.phone}: ${o.motivo}`),
              ]
                .filter(Boolean)
                .join("\n")}
            />
          ) : null}
          <Boton titulo="Agregar" icono="agregar" onPress={subir} cargando={trabajando === "cargar"} deshabilitado={!pegado.trim()} />
          {pegado ? <Boton titulo="Limpiar" variante="texto" onPress={() => setPegado("")} /> : null}
        </ScrollView>
      </Hoja>

    </>
  );
}
