/**
 * Lo que comparten la lista y el detalle de campañas: tipos, formulario,
 * estados y el lector de números pegados (mismo formato que el panel web:
 * "teléfono; dato1; dato2", con ";" o ",").
 */
import { useDatos } from "@/src/datos";
import { fechaLarga } from "@/src/fecha";
import { Aviso, CampoDef } from "@/src/gestion";
import { Tono } from "@/src/ui";

export interface Estadisticas {
  total: number;
  pending: number;
  dialing: number;
  answered: number;
  busy: number;
  noanswer: number;
  failed: number;
  done: number;
  active_calls: number;
  /** En la lista de no llamar: no se marcan. */
  no_llamar?: number;
  /** Pendientes que esperan su próximo intento o cuya lista está pausada. */
  en_espera?: number;
  llamadas_hoy?: number;
  minutos_hoy?: number;
  tope_alcanzado?: string | null;
}

export interface Campana {
  id: number;
  name: string;
  trunk_id: number | null;
  voicebot_id: number | null;
  max_concurrency: number;
  retries: number;
  max_calls_per_day: number | null;
  max_minutes_per_day: number | null;
  message_template: string | null;
  ai_intent: string | null;
  /** Minutos de espera antes de volver a marcar, por resultado. */
  reglas_reciclaje?: Partial<Record<"busy" | "noanswer" | "failed", number>> | null;
  status: string;
  trunk_name?: string | null;
  voicebot_name?: string | null;
  stats?: Estadisticas;
}

export interface NumeroCampana {
  id: number;
  phone: string;
  status: string;
  attempts: number;
  last_error: string | null;
  vars: Record<string, string>;
}

export interface ResultadoCarga {
  added: number;
  updated: number;
  total: number;
  agenda_creadas: number;
  agenda_omitidas: { phone: string; motivo: string }[];
  bloqueados?: { phone: string; motivo: string }[];
}

export const INTENCIONES = [
  { valor: "confirmar", etiqueta: "Confirmar cita" },
  { valor: "reagendar", etiqueta: "Reagendar cita" },
  { valor: "cancelar", etiqueta: "Cancelar cita" },
  { valor: "agendar", etiqueta: "Agendar cita nueva" },
  { valor: "cobranza", etiqueta: "Cobranza de cartera" },
];

export const ESTADO_CAMPANA: Record<string, { texto: string; tono: Tono }> = {
  idle: { texto: "Detenida", tono: "neutro" },
  running: { texto: "En curso", tono: "ok" },
  paused: { texto: "Pausada", tono: "aviso" },
  done: { texto: "Completada", tono: "info" },
};

export const ESTADO_NUMERO: Record<string, { texto: string; tono: Tono }> = {
  pending: { texto: "Pendiente", tono: "aviso" },
  dialing: { texto: "Marcando", tono: "info" },
  answered: { texto: "Contestó", tono: "ok" },
  done: { texto: "Completada", tono: "ok" },
  busy: { texto: "Ocupado", tono: "peligro" },
  noanswer: { texto: "Sin respuesta", tono: "neutro" },
  failed: { texto: "Falló", tono: "peligro" },
};

/** Porcentaje de números ya gestionados (ni pendientes ni marcando). */
export function avance(s?: Estadisticas): number {
  if (!s || !s.total) return 0;
  return Math.round(((s.total - s.pending - s.dialing) / s.total) * 100);
}

export function camposCampana(troncales: { id: number; name: string }[], bots: { id: number; name: string }[]): CampoDef[] {
  return [
    { clave: "name", etiqueta: "Nombre", placeholder: "Confirmación de citas de octubre" },
    {
      clave: "ai_intent",
      etiqueta: "Qué resuelve el voizbot",
      tipo: "opciones",
      opciones: INTENCIONES,
      ayuda: "Cobranza informa la deuda y registra promesas de pago; el resto trabaja sobre la agenda de citas.",
    },
    {
      clave: "trunk_id",
      etiqueta: "Troncal",
      tipo: "opciones",
      opciones: [{ valor: "", etiqueta: "Sin troncal" }, ...troncales.map((t) => ({ valor: String(t.id), etiqueta: t.name }))],
    },
    {
      clave: "voicebot_id",
      etiqueta: "Voizbot",
      tipo: "opciones",
      opciones: [{ valor: "", etiqueta: "Sin voizbot" }, ...bots.map((b) => ({ valor: String(b.id), etiqueta: b.name }))],
    },
    { clave: "max_concurrency", etiqueta: "Llamadas a la vez", tipo: "numero", ayuda: "De 1 a 100." },
    { clave: "retries", etiqueta: "Reintentos por número", tipo: "numero", ayuda: "De 0 a 10." },
    {
      clave: "espera_busy",
      etiqueta: "Si estaba ocupado, reintentar a los (minutos)",
      tipo: "numero",
      placeholder: "En la vuelta siguiente",
    },
    { clave: "espera_noanswer", etiqueta: "Si no contestó, reintentar a los (minutos)", tipo: "numero", placeholder: "En la vuelta siguiente" },
    {
      clave: "espera_failed",
      etiqueta: "Si falló, reintentar a los (minutos)",
      tipo: "numero",
      placeholder: "En la vuelta siguiente",
      ayuda: "Hasta 7 días (10080). Cuántas veces sigue siendo «Reintentos».",
    },
    {
      clave: "max_calls_per_day",
      etiqueta: "Tope de llamadas por día",
      tipo: "numero",
      placeholder: "Sin tope",
      ayuda: "Al llegar, la campaña espera al día siguiente sin dar números por fallidos. Vacío = sin tope.",
    },
    {
      clave: "max_minutes_per_day",
      etiqueta: "Tope de minutos por día",
      tipo: "numero",
      placeholder: "Sin tope",
      ayuda: "Minutos hablados por la troncal en el día. Vacío = sin tope.",
    },
    {
      clave: "message_template",
      etiqueta: "Mensaje de apertura (opcional)",
      tipo: "multilinea",
      placeholder: "Hola {cliente}, te recuerdo tu cita del {fecha}. ¿La confirmas?",
      ayuda:
        "Las {variables} se rellenan con los datos de cada número. En cobranza el bot abre siempre confirmando identidad sin revelar la deuda; {cliente}, {monto}, {vencimiento} y {factura} cargan la deuda en Cobranza.",
    },
  ];
}

export function inicialCampana(c?: Campana | null): Record<string, unknown> {
  return {
    name: c?.name ?? "",
    ai_intent: c?.ai_intent || "confirmar",
    trunk_id: c?.trunk_id ? String(c.trunk_id) : "",
    voicebot_id: c?.voicebot_id ? String(c.voicebot_id) : "",
    max_concurrency: c?.max_concurrency ?? 5,
    retries: c?.retries ?? 0,
    max_calls_per_day: c?.max_calls_per_day ?? "",
    max_minutes_per_day: c?.max_minutes_per_day ?? "",
    message_template: c?.message_template ?? "",
    espera_busy: c?.reglas_reciclaje?.busy ?? "",
    espera_noanswer: c?.reglas_reciclaje?.noanswer ?? "",
    espera_failed: c?.reglas_reciclaje?.failed ?? "",
  };
}

const numeroOVacio = (v: unknown) => (String(v ?? "").trim() ? Number(v) : null);

export function cuerpoCampana(v: Record<string, unknown>) {
  const nombre = String(v.name ?? "").trim();
  if (!nombre) throw new Error("Ponle un nombre a la campaña.");
  return {
    name: nombre,
    ai_intent: String(v.ai_intent || "confirmar"),
    trunk_id: v.trunk_id ? Number(v.trunk_id) : null,
    voicebot_id: v.voicebot_id ? Number(v.voicebot_id) : null,
    max_concurrency: Number(v.max_concurrency) || 1,
    retries: Number(v.retries) || 0,
    max_calls_per_day: numeroOVacio(v.max_calls_per_day),
    max_minutes_per_day: numeroOVacio(v.max_minutes_per_day),
    message_template: String(v.message_template ?? "").trim() || null,
    reglas_reciclaje: reglasDe(v),
  };
}

function reglasDe(v: Record<string, unknown>) {
  const reglas: Record<string, number> = {};
  for (const resultado of ["busy", "noanswer", "failed"] as const) {
    const n = Number(v[`espera_${resultado}`]);
    if (String(v[`espera_${resultado}`] ?? "").trim() && n > 0) reglas[resultado] = Math.round(n);
  }
  return Object.keys(reglas).length ? reglas : null;
}

/** {variables} del mensaje de apertura, en orden y sin repetir. */
export function columnasDe(plantilla: string | null | undefined): string[] {
  return Array.from(new Set(Array.from((plantilla ?? "").matchAll(/\{(\w+)\}/g), (m) => m[1])));
}

/**
 * Convierte lo pegado en filas para el backend. Si una línea trae más datos
 * que {variables} tiene el mensaje, se avisa en vez de perderlos en silencio
 * (mismo criterio que el panel).
 */
export function leerNumeros(texto: string, columnas: string[]): { filas: { phone: string; vars: Record<string, string> }[]; error?: string } {
  const lineas = texto
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .filter((l, i) => !(i === 0 && l.toLowerCase().startsWith("telefono")));
  const partes = lineas.map((l) => l.split(l.includes(";") ? ";" : ",").map((p) => p.trim()));
  const deMas = partes.filter(([, ...valores]) => valores.length > columnas.length).length;
  if (deMas) {
    return {
      filas: [],
      error: columnas.length
        ? `${deMas} línea(s) traen más datos de los que usa el mensaje de apertura (${columnas.join(", ")}). Revísalas o agrega la {variable} que falta editando la campaña.`
        : `${deMas} línea(s) traen datos además del teléfono, pero el mensaje de apertura no tiene ninguna {variable}: se perderían. Edita la campaña y agrega algo como {cliente} al mensaje.`,
    };
  }
  const filas = partes
    .map(([phone, ...valores]) => {
      const vars: Record<string, string> = {};
      columnas.forEach((nombre, i) => {
        if (valores[i]) vars[nombre] = valores[i];
      });
      return { phone, vars };
    })
    .filter((f) => f.phone);
  return { filas };
}

/** Avisa si ahora las campañas no pueden marcar (franja de Ajustes o Ley 2300 en cobranza). */
export function AvisoHorario() {
  const { datos } = useDatos<{
    cobranza: { puede_marcar: boolean; proxima_apertura: string | null };
    otras: { puede_marcar: boolean; proxima_apertura: string | null };
    festivo_hoy: boolean;
  }>("/api/campaigns/horario", { ttl: 60_000 });
  if (!datos || (datos.cobranza.puede_marcar && datos.otras.puede_marcar)) return null;
  const cuando = (iso: string | null) => (iso ? fechaLarga(iso) : "sin franja en los próximos días (revisa Ajustes)");
  return (
    <Aviso
      tono="aviso"
      texto={
        (datos.festivo_hoy ? "Hoy es festivo. " : "") +
        (!datos.otras.puede_marcar
          ? `Fuera del horario de marcación: las campañas retoman el ${cuando(datos.otras.proxima_apertura)}.`
          : `Las campañas de cobranza esperan la franja de la Ley 2300: retoman el ${cuando(datos.cobranza.proxima_apertura)}.`)
      }
    />
  );
}
