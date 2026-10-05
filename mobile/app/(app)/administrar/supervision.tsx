import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { useAuth } from "@/src/auth/AuthContext";
import { Aviso, CampoDef, Hoja, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Metrica, Pildora, Seccion, Segmentado, Tarjeta, Tono } from "@/src/ui";

/**
 * Supervisor en la app: lo mismo que la pantalla Supervisión del panel
 * (frontend/app/supervision/page.tsx). Cifras del wallboard arriba, agentes
 * y campañas en vivo (cada 3 s mientras está a la vista) y, con
 * supervision:intervenir, escuchar, susurrar, intervenir, forzar pausa o
 * salida, nivel en caliente y pausar la campaña. Todo queda en la auditoría.
 */

type Estado = "LISTO" | "PAUSA" | "PREVIA" | "TIMBRANDO" | "EN_LLAMADA" | "DISPO";
type Modo = "escuchar" | "susurrar" | "intervenir";

interface Agente {
  user_id: number;
  nombre: string;
  extension: string | null;
  estado: Estado;
  en_estado_s: number | null;
  audio: boolean;
  pausa: { id: number; nombre: string; max_minutos: number | null } | null;
  pausa_excedida: boolean;
  pausa_pendiente: boolean;
  campanas: { id: number; nombre: string }[];
  campana: string | null;
  telefono: string | null;
  hablado_s: number | null;
  monitoreo: { supervisor_id: number; modo: Modo } | null;
}

interface Hoy {
  intentos: number;
  contestadas: number;
  abandonadas: number;
  abandono_pct: number | null;
}

interface Campana {
  id: number;
  nombre: string;
  metodo: string;
  status: string;
  agentes: { conectados: number; listo: number; pausa: number; timbrando: number; en_llamada: number };
  hopper: number;
  nivel_marcacion: number;
  nivel_max: number;
  nivel_actual: number | null;
  abandono_objetivo: number;
  hoy: Hoy;
  llamadas: { timbrando: number; en_espera: number } | null;
  ultimos_15: { contacto_pct: number | null; abandono_pct: number | null; ring_s: number | null } | null;
}

interface Resumen {
  agentes: { conectados: number; listos: number; en_llamada: number; en_pausa: number; pausas_excedidas: number };
  llamadas: { en_espera: number };
  hoy: Hoy;
}

interface MiMonitoreo {
  agente_id: number;
  modo: Modo;
  contestado: boolean;
}

const ESTADOS: Record<Estado, { texto: string; tono: Tono }> = {
  LISTO: { texto: "Listo", tono: "ok" },
  PAUSA: { texto: "En pausa", tono: "aviso" },
  PREVIA: { texto: "Vista previa", tono: "info" },
  TIMBRANDO: { texto: "Timbrando", tono: "info" },
  EN_LLAMADA: { texto: "En llamada", tono: "marca" },
  DISPO: { texto: "Disposición", tono: "neutro" },
};

const MODOS: { valor: Modo; etiqueta: string }[] = [
  { valor: "escuchar", etiqueta: "Escuchar" },
  { valor: "susurrar", etiqueta: "Susurrar" },
  { valor: "intervenir", etiqueta: "Intervenir" },
];

const METODOS: Record<string, string> = {
  manual: "Manual",
  vista_previa: "Vista previa",
  progresivo: "Progresivo",
  proporcional: "Proporcional",
  predictivo: "Predictivo",
};

function reloj(s: number | null | undefined): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`;
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${v} %`);

export default function Supervision() {
  const c = useColores();
  const { puede } = useAuth();
  const interviene = puede("supervision:intervenir");
  const [resumen, setResumen] = useState<Resumen | null>(null);
  const [agentes, setAgentes] = useState<Agente[] | null>(null);
  const [campanas, setCampanas] = useState<Campana[] | null>(null);
  const [monitor, setMonitor] = useState<MiMonitoreo | null>(null);
  const [error, setError] = useState("");
  const [vista, setVista] = useState<"agentes" | "campanas">("agentes");
  const [elegido, setElegido] = useState<Agente | null>(null);
  const [pausaPara, setPausaPara] = useState<Agente | null>(null);
  const [nivelPara, setNivelPara] = useState<Campana | null>(null);
  const [codigos, setCodigos] = useState<{ id: number; nombre: string; activo: boolean }[]>([]);
  const [trabajando, setTrabajando] = useState("");
  const vivo = useRef(true);

  const cargar = useCallback(async () => {
    try {
      const [r, a, cs, m] = await Promise.all([
        peticion<Resumen>("/api/supervision/resumen"),
        peticion<Agente[]>("/api/supervision/agentes"),
        peticion<Campana[]>("/api/supervision/campanas"),
        interviene ? peticion<MiMonitoreo | null>("/api/supervision/monitoreo") : Promise.resolve(null),
      ]);
      if (!vivo.current) return;
      setResumen(r);
      setAgentes(a);
      setCampanas(cs);
      setMonitor(m);
      setError("");
    } catch (e) {
      if (vivo.current) setError(e instanceof Error ? e.message : "No se pudo cargar la supervisión");
    }
  }, [interviene]);

  // Cada 3 s mientras la pantalla está a la vista; al salir, se detiene.
  useFocusEffect(
    useCallback(() => {
      vivo.current = true;
      cargar();
      const t = setInterval(cargar, 3000);
      return () => {
        vivo.current = false;
        clearInterval(t);
      };
    }, [cargar])
  );

  const accion = async (clave: string, fn: () => Promise<unknown>) => {
    setTrabajando(clave);
    try {
      await fn();
      exito();
      await cargar();
    } catch (e) {
      fallo();
      Alert.alert("No se pudo", e instanceof Error ? e.message : "Inténtalo de nuevo.");
    } finally {
      setTrabajando("");
    }
  };

  const monitorear = (a: Agente, modo: Modo) =>
    accion(`mon-${a.user_id}`, async () => {
      await peticion(`/api/supervision/agentes/${a.user_id}/monitorear`, { method: "POST", body: { modo } });
      setElegido(null);
    });

  const sacar = (a: Agente) => {
    const enLlamada = a.estado === "EN_LLAMADA" || a.estado === "TIMBRANDO";
    Alert.alert(
      "Sacar de la sesión",
      enLlamada ? `${a.nombre} está en una llamada. ¿Cortarla y sacarlo?` : `¿Sacar a ${a.nombre} de la sesión de agente?`,
      [
        { text: "Cancelar", style: "cancel" },
        {
          text: "Sacar",
          style: "destructive",
          onPress: () =>
            accion(`sacar-${a.user_id}`, async () => {
              await peticion(`/api/supervision/agentes/${a.user_id}/sacar`, { method: "POST", body: { cortar_llamada: enLlamada } });
              setElegido(null);
            }),
        },
      ]
    );
  };

  const abrirPausa = async (a: Agente) => {
    setElegido(null);
    setPausaPara(a);
    try {
      setCodigos((await peticion<{ id: number; nombre: string; activo: boolean }[]>("/api/contact-center/pausas")).filter((p) => p.activo));
    } catch {
      setCodigos([]);
    }
  };

  const monitoreado = monitor ? agentes?.find((a) => a.user_id === monitor.agente_id) : undefined;
  const camposNivel: CampoDef[] =
    nivelPara?.metodo === "predictivo"
      ? [
          { clave: "abandono_objetivo", etiqueta: "Abandono objetivo (%)", tipo: "numero", ayuda: "De 0,5 a 10. Más bajo: marca con más prudencia." },
          { clave: "nivel_max", etiqueta: "Tope de llamadas por agente", tipo: "numero", ayuda: "De 1 a 5." },
        ]
      : [{ clave: "nivel_marcacion", etiqueta: "Llamadas por agente libre", tipo: "numero", ayuda: "De 1 a 5 (1 = progresivo)." }];

  return (
    <Pantalla onRefrescar={cargar}>
      {error ? <Aviso texto={error} /> : null}

      {resumen ? (
        <View style={{ gap: 10 }}>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Conectados" valor={resumen.agentes.conectados} icono="usuarios" tono="marca" />
            <Metrica etiqueta="Listos" valor={resumen.agentes.listos} icono="ok" tono="ok" />
          </View>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="En llamada" valor={resumen.agentes.en_llamada} icono="enLlamada" tono="info" />
            <Metrica
              etiqueta="En pausa"
              valor={resumen.agentes.en_pausa}
              icono="pausa"
              tono={resumen.agentes.pausas_excedidas ? "peligro" : "aviso"}
              detalle={resumen.agentes.pausas_excedidas ? `${resumen.agentes.pausas_excedidas} pasada(s) del máximo` : undefined}
            />
          </View>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Esperando agente" valor={resumen.llamadas.en_espera} icono="horario" tono={resumen.llamadas.en_espera ? "aviso" : "neutro"} />
            <Metrica
              etiqueta="Abandono hoy"
              valor={pct(resumen.hoy.abandono_pct)}
              icono="perdida"
              tono={(campanas ?? []).some((x) => x.hoy.abandono_pct != null && x.hoy.abandono_pct > x.abandono_objetivo) ? "peligro" : "ok"}
              detalle={`${resumen.hoy.abandonadas} de ${resumen.hoy.contestadas}`}
            />
          </View>
        </View>
      ) : null}

      {monitor ? (
        <Tarjeta style={{ gap: 10 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Pildora texto={monitor.contestado ? "En la sala" : "Llamándote…"} tono="peligro" />
            <Text style={{ flex: 1, color: c.texto, fontSize: 15 }}>
              Monitoreando a <Text style={{ fontWeight: "700" }}>{monitoreado?.nombre ?? `#${monitor.agente_id}`}</Text>
            </Text>
          </View>
          {!monitor.contestado ? (
            <Text style={{ color: c.textoSecundario, fontSize: 13 }}>Te timbra el teléfono de tu extensión: contesta para entrar a la sala.</Text>
          ) : null}
          <Segmentado
            opciones={MODOS}
            valor={monitor.modo}
            onChange={(modo) => accion("modo", () => peticion("/api/supervision/monitoreo/modo", { method: "POST", body: { modo } }))}
          />
          <Boton
            titulo="Dejar de monitorear"
            variante="peligro"
            cargando={trabajando === "colgar"}
            onPress={() => accion("colgar", () => peticion("/api/supervision/monitoreo/colgar", { method: "POST", body: {} }))}
          />
        </Tarjeta>
      ) : null}

      <Segmentado
        valor={vista}
        onChange={setVista}
        opciones={[
          { valor: "agentes", etiqueta: `Agentes${agentes ? ` (${agentes.length})` : ""}` },
          { valor: "campanas", etiqueta: "Campañas" },
        ]}
      />

      {vista === "agentes" ? (
        !agentes ? (
          <ListaEsqueleto />
        ) : agentes.length === 0 ? (
          <Aviso tono="info" texto="Ningún agente conectado. Aparecen al entrar desde la consola de agente del panel." />
        ) : (
          <Seccion>
            {agentes.map((a, i) => {
              const e = ESTADOS[a.estado];
              const partes = [
                reloj(a.en_estado_s),
                a.pausa?.nombre,
                a.telefono,
                a.campana,
                a.pausa_pendiente ? "pausa al terminar" : null,
                a.monitoreo ? `monitoreado (${a.monitoreo.modo})` : null,
                a.audio ? null : "sin audio",
              ].filter(Boolean);
              return (
                <FilaMenu
                  key={a.user_id}
                  titulo={a.nombre}
                  detalle={partes.join(" · ")}
                  derecha={<Pildora texto={e?.texto ?? a.estado} tono={a.pausa_excedida ? "peligro" : e?.tono ?? "neutro"} />}
                  onPress={interviene ? () => setElegido(a) : undefined}
                  ultima={i === agentes.length - 1}
                />
              );
            })}
          </Seccion>
        )
      ) : !campanas ? (
        <ListaEsqueleto />
      ) : campanas.length === 0 ? (
        <Aviso tono="info" texto="Ninguna campaña con agentes en curso." />
      ) : (
        campanas.map((x) => {
          const sobremarca = x.metodo === "proporcional" || x.metodo === "predictivo";
          const automatica = x.metodo !== "manual" && x.metodo !== "vista_previa";
          const pasado = x.hoy.abandono_pct != null && x.hoy.abandono_pct > x.abandono_objetivo;
          return (
            <Tarjeta key={x.id} style={{ gap: 10 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: c.texto, fontSize: 16, fontWeight: "700" }}>{x.nombre}</Text>
                  <Text style={{ color: c.textoSecundario, fontSize: 13 }}>
                    {METODOS[x.metodo] ?? x.metodo}
                    {x.metodo === "predictivo" && x.nivel_actual != null ? ` · ${x.nivel_actual} por agente libre` : ""}
                    {x.metodo === "proporcional" ? ` · nivel ${x.nivel_marcacion}` : ""}
                  </Text>
                </View>
                <Pildora texto={x.status === "running" ? "En curso" : x.status === "paused" ? "Pausada" : "Detenida"} tono={x.status === "running" ? "ok" : "neutro"} />
              </View>
              <Text style={{ color: c.texto, fontSize: 14 }}>
                {x.agentes.conectados} conectados · {x.agentes.listo} listos · {x.agentes.en_llamada + x.agentes.timbrando} en llamada · {x.agentes.pausa} en pausa
              </Text>
              {sobremarca ? (
                <Text style={{ color: pasado ? c.peligroTexto : c.textoSecundario, fontSize: 13 }}>
                  Hoy: {x.hoy.contestadas} contestadas, abandono {pct(x.hoy.abandono_pct)} (obj. {x.abandono_objetivo} %) · Ahora: {x.llamadas?.timbrando ?? 0} timbrando,{" "}
                  {x.llamadas?.en_espera ?? 0} esperando agente
                </Text>
              ) : null}
              <Text style={{ color: c.textoSecundario, fontSize: 13 }}>
                {x.hopper} lead(s) listos
                {x.ultimos_15 ? ` · 15 min: contacto ${pct(x.ultimos_15.contacto_pct)}, ring ${x.ultimos_15.ring_s ?? "—"} s` : ""}
              </Text>
              {interviene && (sobremarca || automatica) ? (
                <View style={{ flexDirection: "row", gap: 8 }}>
                  {sobremarca ? <Boton titulo="Nivel" variante="suave" chico style={{ flex: 1 }} onPress={() => setNivelPara(x)} /> : null}
                  {automatica ? (
                    <Boton
                      titulo={x.status === "running" ? "Pausar" : "Reanudar"}
                      variante="contorno"
                      chico
                      style={{ flex: 1 }}
                      cargando={trabajando === `camp-${x.id}`}
                      onPress={() =>
                        accion(`camp-${x.id}`, () =>
                          peticion(`/api/supervision/campanas/${x.id}/${x.status === "running" ? "pausar" : "reanudar"}`, { method: "POST", body: {} })
                        )
                      }
                    />
                  ) : null}
                </View>
              ) : null}
            </Tarjeta>
          );
        })
      )}

      <Hoja visible={elegido !== null} titulo={elegido?.nombre ?? ""} onCerrar={() => setElegido(null)}>
        {elegido ? (
          <View style={{ gap: 10, padding: 20, paddingTop: 4 }}>
            {!elegido.audio ? <Aviso tono="aviso" texto="El agente no tiene el audio conectado: no hay sala que escuchar." /> : null}
            {elegido.monitoreo && monitor?.agente_id !== elegido.user_id ? <Aviso tono="info" texto="Otro supervisor lo está monitoreando." /> : null}
            {MODOS.map((m) => (
              <Boton
                key={m.valor}
                titulo={m.etiqueta}
                variante="suave"
                deshabilitado={!elegido.audio || (!!elegido.monitoreo && monitor?.agente_id !== elegido.user_id)}
                cargando={trabajando === `mon-${elegido.user_id}`}
                onPress={() => monitorear(elegido, m.valor)}
              />
            ))}
            <Text style={{ color: c.textoSecundario, fontSize: 12 }}>
              Escuchar: nadie te oye. Susurrar: te oye el agente, no el cliente. Intervenir: hablas con los dos.
            </Text>
            {elegido.estado !== "PAUSA" && !elegido.pausa_pendiente ? <Boton titulo="Forzar pausa" variante="contorno" onPress={() => abrirPausa(elegido)} /> : null}
            <Boton titulo="Sacar de la sesión" variante="peligro" cargando={trabajando === `sacar-${elegido.user_id}`} onPress={() => sacar(elegido)} />
          </View>
        ) : null}
      </Hoja>

      <Hoja visible={pausaPara !== null} titulo={`Pausar a ${pausaPara?.nombre ?? ""}`} onCerrar={() => setPausaPara(null)}>
        {pausaPara ? (
          <View style={{ gap: 10, padding: 20, paddingTop: 4 }}>
            {pausaPara.estado === "EN_LLAMADA" || pausaPara.estado === "TIMBRANDO" || pausaPara.estado === "DISPO" ? (
              <Aviso tono="info" texto="Está en una llamada: no se corta. Pasa a pausa al terminar y disponer." />
            ) : null}
            {[{ id: 0, nombre: "Sin código" }, ...codigos].map((p) => (
              <Boton
                key={p.id}
                titulo={p.nombre}
                variante="suave"
                cargando={trabajando === `pausa-${pausaPara.user_id}-${p.id}`}
                onPress={() =>
                  accion(`pausa-${pausaPara.user_id}-${p.id}`, async () => {
                    await peticion(`/api/supervision/agentes/${pausaPara.user_id}/pausa`, { method: "POST", body: { codigo_pausa_id: p.id || null } });
                    setPausaPara(null);
                  })
                }
              />
            ))}
          </View>
        ) : null}
      </Hoja>

      {nivelPara ? (
        <HojaFormulario
          key={nivelPara.id}
          visible
          titulo={`Nivel de ${nivelPara.nombre}`}
          campos={camposNivel}
          textoGuardar="Aplicar ya"
          inicial={{
            nivel_marcacion: String(nivelPara.nivel_marcacion),
            nivel_max: String(nivelPara.nivel_max),
            abandono_objetivo: String(nivelPara.abandono_objetivo),
          }}
          onGuardar={async (v) => {
            const cuerpo =
              nivelPara.metodo === "predictivo"
                ? { nivel_max: Number(v.nivel_max), abandono_objetivo: Number(v.abandono_objetivo) }
                : { nivel_marcacion: Number(v.nivel_marcacion) };
            await peticion(`/api/supervision/campanas/${nivelPara.id}/nivel`, { method: "PUT", body: cuerpo });
            setNivelPara(null);
            exito();
            cargar();
          }}
          onCerrar={() => setNivelPara(null)}
        />
      ) : null}
    </Pantalla>
  );
}
