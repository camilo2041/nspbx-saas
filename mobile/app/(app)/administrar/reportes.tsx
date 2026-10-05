import { useState } from "react";
import { Alert, Share, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, CampoDef, Esqueleto, FiltroChips, HojaFormulario, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Metrica, Pildora, Seccion, Segmentado } from "@/src/ui";

/**
 * Reportes del contact center: lo mismo que la pantalla Reportes del panel
 * (frontend/app/reportes/page.tsx), con el CSV para compartir y los
 * programados por correo. Ver backend/app/services/reportes.py.
 */

type Vista = "agentes" | "campanas" | "disposiciones" | "cumplimiento";
type Rango = "hoy" | "ayer" | "7" | "30";

const VISTAS: { valor: Vista; etiqueta: string }[] = [
  { valor: "agentes", etiqueta: "Agentes" },
  { valor: "campanas", etiqueta: "Campañas" },
  { valor: "disposiciones", etiqueta: "Dispos." },
  { valor: "cumplimiento", etiqueta: "Cumplim." },
];

const RANGOS: { valor: Rango; etiqueta: string }[] = [
  { valor: "hoy", etiqueta: "Hoy" },
  { valor: "ayer", etiqueta: "Ayer" },
  { valor: "7", etiqueta: "Últimos 7 días" },
  { valor: "30", etiqueta: "Últimos 30 días" },
];

const NOMBRE_TIPO: Record<string, string> = { agentes: "Agentes", campanas: "Campañas", disposiciones: "Disposiciones", cumplimiento: "Cumplimiento" };
const FRECUENCIAS: Record<string, string> = { diaria: "Cada día", semanal: "Cada lunes", mensual: "Cada día 1" };

function dia(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fechas(r: Rango): [string, string] {
  const hoy = new Date();
  const menos = (n: number) => {
    const d = new Date(hoy);
    d.setDate(d.getDate() - n);
    return dia(d);
  };
  if (r === "hoy") return [menos(0), menos(0)];
  if (r === "ayer") return [menos(1), menos(1)];
  return [menos(Number(r) - 1), menos(0)];
}

function reloj(s: number | null | undefined) {
  if (s == null) return "—";
  s = Math.round(s);
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`;
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${v} %`);

interface Programado {
  id: number;
  nombre: string;
  tipo: string;
  frecuencia: string;
  hora: number;
  destinatarios: string;
  activo: boolean;
  ultimo_periodo: string | null;
  ultimo_error: string | null;
}

export default function Reportes() {
  const c = useColores();
  const [vista, setVista] = useState<Vista>("agentes");
  const [rango, setRango] = useState<Rango>("7");
  const [desde, hasta] = fechas(rango);
  const ruta = `/api/reportes/${vista}?desde=${desde}&hasta=${hasta}`;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const datos = useDatos<any>(ruta, { ttl: 30_000 });
  const programados = useDatos<{ correo_configurado: boolean; programados: Programado[] }>("/api/reportes/programados", { ttl: 30_000 });
  const [editando, setEditando] = useState<Programado | "nuevo" | null>(null);
  const [compartiendo, setCompartiendo] = useState(false);
  const d = datos.datos;

  const compartir = async (seccion?: string) => {
    setCompartiendo(true);
    try {
      const csv = await peticion<string>(`${ruta}&formato=csv${seccion ? `&seccion=${seccion}` : ""}`, { texto: true });
      await Share.share({ title: `${vista}_${desde}_${hasta}.csv`, message: csv });
    } catch (e) {
      Alert.alert("No se pudo exportar", e instanceof Error ? e.message : "Inténtalo de nuevo.");
    } finally {
      setCompartiendo(false);
    }
  };

  const camposProgramado: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "Resultado diario" },
    { clave: "tipo", etiqueta: "Reporte", tipo: "opciones", opciones: Object.entries(NOMBRE_TIPO).map(([valor, etiqueta]) => ({ valor, etiqueta })) },
    {
      clave: "frecuencia",
      etiqueta: "Cuándo",
      tipo: "opciones",
      opciones: [
        { valor: "diaria", etiqueta: "Cada día", detalle: "Con el día anterior" },
        { valor: "semanal", etiqueta: "Cada lunes", detalle: "Con la semana anterior" },
        { valor: "mensual", etiqueta: "Cada día 1", detalle: "Con el mes anterior" },
      ],
    },
    { clave: "hora", etiqueta: "Hora (0 a 23)", tipo: "numero" },
    { clave: "destinatarios", etiqueta: "Para", placeholder: "gerencia@empresa.com, calidad@empresa.com", ayuda: "Hasta 10 correos, separados por coma." },
    { clave: "activo", etiqueta: "Activo", tipo: "conmutador" },
  ];

  return (
    <Pantalla refrescando={datos.refrescando} onRefrescar={() => { invalidar("/api/reportes"); datos.recargar(); programados.recargar(); }}>
      <Segmentado opciones={VISTAS} valor={vista} onChange={setVista} />
      <FiltroChips opciones={RANGOS} valor={rango} onChange={setRango} />
      {datos.error && !d ? <Aviso texto={datos.error} /> : null}
      {!d && datos.cargando ? <Esqueleto alto={200} /> : null}

      {d && vista === "agentes" ? (
        <>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Conectados" valor={reloj(d.total.login_s)} icono="horario" tono="marca" />
            <Metrica etiqueta="Ocupación" valor={pct(d.total.ocupacion_pct)} icono="tendencia" tono="info" detalle={`${d.total.llamadas} llamadas`} />
          </View>
          <Seccion titulo="Agentes">
            {d.filas.length === 0 ? (
              <View style={{ padding: 14 }}>
                <Text style={{ color: c.textoSecundario }}>Sin actividad de agentes en el rango.</Text>
              </View>
            ) : (
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              d.filas.map((f: any, i: number) => (
                <FilaMenu
                  key={f.user_id}
                  titulo={f.nombre}
                  detalle={`Conectado ${reloj(f.login_s)} · pausa ${reloj(f.pausa_s)} · ${f.llamadas} llamadas · AHT ${reloj(f.aht_s)}`}
                  derecha={<Pildora texto={pct(f.ocupacion_pct)} tono="info" />}
                  ultima={i === d.filas.length - 1}
                />
              ))
            )}
          </Seccion>
        </>
      ) : null}

      {d && vista === "campanas" ? (
        <>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Metrica etiqueta="Contacto" valor={pct(d.total.contacto_pct)} icono="enLlamada" tono="info" detalle={`${d.total.contestadas} de ${d.total.intentos}`} />
            <Metrica etiqueta="Conversión" valor={pct(d.total.conversion_pct)} icono="ok" tono="ok" detalle={`Abandono ${pct(d.total.abandono_pct)}`} />
          </View>
          <Seccion titulo="Campañas">
            {d.filas.length === 0 ? (
              <View style={{ padding: 14 }}>
                <Text style={{ color: c.textoSecundario }}>Sin llamadas de campañas en el rango.</Text>
              </View>
            ) : (
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              d.filas.map((f: any, i: number) => (
                <FilaMenu
                  key={f.campaign_id}
                  titulo={f.nombre}
                  detalle={`${f.intentos} intentos · ${f.contestadas} contestadas · abandono ${pct(f.abandono_pct)} · ring ${f.ring_promedio_s ?? "—"} s · ${f.ventas + f.promesas} ventas/promesas`}
                  derecha={<Pildora texto={pct(f.conversion_pct)} tono="ok" />}
                  ultima={i === d.filas.length - 1}
                />
              ))
            )}
          </Seccion>
        </>
      ) : null}

      {d && vista === "disposiciones" ? (
        <Seccion titulo={`Disposiciones (${d.total}) · callbacks ${d.callbacks.hechos}/${d.callbacks.total}`}>
          {d.filas.length === 0 ? (
            <View style={{ padding: 14 }}>
              <Text style={{ color: c.textoSecundario }}>Sin disposiciones en el rango.</Text>
            </View>
          ) : (
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            d.filas.map((f: any, i: number) => (
              <FilaMenu
                key={i}
                titulo={f.disposicion}
                detalle={`${f.grupo} · ${f.categoria ?? ""}`}
                derecha={<Text style={{ color: c.texto, fontWeight: "700" }}>{f.cantidad}</Text>}
                ultima={i === d.filas.length - 1}
              />
            ))
          )}
        </Seccion>
      ) : null}

      {d && vista === "cumplimiento" ? (
        <>
          <Aviso
            tono={d.abandono_incumplido ? "peligro" : "ok"}
            texto={d.abandono_incumplido ? `${d.abandono_incumplido} día(s) con abandono sobre el objetivo` : "Abandono dentro del objetivo todos los días"}
          />
          <Aviso
            tono={d.fuera_de_horario_total ? "peligro" : "ok"}
            texto={d.fuera_de_horario_total ? `${d.fuera_de_horario_total} llamada(s) fuera del horario permitido` : "Ninguna llamada fuera de horario"}
          />
          <Aviso
            tono={d.contactos_semana_total ? "aviso" : "ok"}
            texto={
              d.contactos_semana_total
                ? `${d.contactos_semana_total} número(s) con más de ${d.max_contactos_semana} contacto(s) en una semana (cobranza)`
                : "Ningún número pasó del tope de contactos por semana"
            }
          />
          <Text style={{ fontSize: 12, color: c.textoSecundario }}>
            Ley 2300: confirma con tu abogado el tope que aplica; se ajusta en el panel. El detalle va en los CSV.
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Boton titulo="Abandono" variante="suave" chico style={{ flex: 1 }} cargando={compartiendo} onPress={() => compartir("abandono")} />
            <Boton titulo="Contactos" variante="suave" chico style={{ flex: 1 }} cargando={compartiendo} onPress={() => compartir("contactos_semana")} />
            <Boton titulo="Horario" variante="suave" chico style={{ flex: 1 }} cargando={compartiendo} onPress={() => compartir("fuera_de_horario")} />
          </View>
        </>
      ) : null}

      {d && vista !== "cumplimiento" ? <Boton titulo="Compartir CSV" icono="enviar" variante="suave" cargando={compartiendo} onPress={() => compartir()} /> : null}

      <Seccion titulo="Programados por correo" accion={<Boton titulo="Nuevo" icono="agregar" variante="texto" chico onPress={() => setEditando("nuevo")} />}>
        {programados.datos && !programados.datos.correo_configurado ? (
          <View style={{ padding: 14 }}>
            <Aviso tono="aviso" texto="El correo saliente no está configurado en el servidor: se guardan pero no se envían." />
          </View>
        ) : null}
        {(programados.datos?.programados ?? []).length === 0 ? (
          <View style={{ padding: 14 }}>
            <Text style={{ color: c.textoSecundario, fontSize: 13 }}>Ninguno. Salen solos con el CSV adjunto, del período ya cerrado.</Text>
          </View>
        ) : (
          programados.datos!.programados.map((p, i) => (
            <FilaMenu
              key={p.id}
              titulo={p.nombre}
              detalle={`${NOMBRE_TIPO[p.tipo]} · ${FRECUENCIAS[p.frecuencia]} ${String(p.hora).padStart(2, "0")}:00 · ${p.destinatarios}${p.ultimo_error ? ` · Error: ${p.ultimo_error}` : ""}`}
              derecha={<Pildora texto={p.activo ? p.ultimo_periodo ?? "Activo" : "Inactivo"} tono={p.ultimo_error ? "peligro" : p.activo ? "ok" : "neutro"} />}
              onPress={() => setEditando(p)}
              ultima={i === programados.datos!.programados.length - 1}
            />
          ))
        )}
      </Seccion>

      <HojaFormulario
        key={editando === "nuevo" ? "nuevo" : editando?.id ?? "x"}
        visible={editando !== null}
        titulo={editando === "nuevo" ? "Nuevo reporte programado" : "Editar reporte programado"}
        campos={camposProgramado}
        inicial={
          editando && editando !== "nuevo"
            ? { nombre: editando.nombre, tipo: editando.tipo, frecuencia: editando.frecuencia, hora: editando.hora, destinatarios: editando.destinatarios, activo: editando.activo }
            : { nombre: "", tipo: "campanas", frecuencia: "diaria", hora: 7, destinatarios: "", activo: true }
        }
        onGuardar={async (v) => {
          const cuerpo = {
            nombre: String(v.nombre ?? "").trim(),
            tipo: String(v.tipo),
            frecuencia: String(v.frecuencia),
            hora: Math.min(23, Math.max(0, Number(v.hora) || 0)),
            destinatarios: String(v.destinatarios ?? ""),
            activo: !!v.activo,
          };
          if (!cuerpo.nombre) throw new Error("Ponle un nombre.");
          if (editando === "nuevo") await peticion("/api/reportes/programados", { method: "POST", body: cuerpo });
          else if (editando) await peticion(`/api/reportes/programados/${editando.id}`, { method: "PUT", body: cuerpo });
          setEditando(null);
          exito();
          invalidar("/api/reportes/programados");
          programados.recargar();
        }}
        onEliminar={
          editando && editando !== "nuevo"
            ? () =>
                Alert.alert("Borrar", `¿Borrar «${editando.nombre}»?`, [
                  { text: "Cancelar", style: "cancel" },
                  {
                    text: "Borrar",
                    style: "destructive",
                    onPress: async () => {
                      await peticion(`/api/reportes/programados/${editando.id}`, { method: "DELETE" });
                      setEditando(null);
                      invalidar("/api/reportes/programados");
                      programados.recargar();
                    },
                  },
                ])
            : undefined
        }
        onCerrar={() => setEditando(null)}
      />
    </Pantalla>
  );
}
