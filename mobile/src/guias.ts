import { useSyncExternalStore } from "react";

/**
 * Guías paso a paso en la app (la versión del teléfono de frontend/lib/guias.ts).
 *
 * Los ids son los mismos que conoce el asistente (backend/app/api/assistant.py,
 * GUIAS): cuando responde con `[[guia:id]]` y la guía existe aquí, aparece el
 * botón «Muéstrame». Solo están las que se pueden hacer desde el teléfono; las
 * demás se ven en el panel web. Una prueba exige que los ids existan en el backend.
 */
export interface PasoGuia {
  /** Pantalla de la app donde se hace el paso. */
  ruta: string;
  titulo: string;
  texto: string;
}

export interface Guia {
  id: string;
  titulo: string;
  descripcion: string;
  palabras: string[];
  permiso: string | null;
  pasos: PasoGuia[];
}

/** Nombre de cada pantalla, para «Llévame a…». */
export const NOMBRE_PANTALLA: Record<string, string> = {
  "/": "Teléfono",
  "/llamadas": "Llamadas",
  "/administrar/agente": "Trabajar",
  "/administrar/buzon": "Buzón de voz",
  "/administrar/supervision": "Supervisión",
  "/administrar/extensiones": "Extensiones",
  "/administrar/usuarios": "Usuarios",
  "/administrar/rutas-entrantes": "Números entrantes",
  "/administrar/troncales": "Proveedor de telefonía",
  "/administrar/colas": "Grupos de atención",
  "/administrar/campanas": "Campañas",
};

export const GUIAS: Guia[] = [
  {
    id: "llamar-softphone",
    titulo: "Hacer una llamada",
    descripcion: "Marcar desde la app, sin teléfono de escritorio.",
    palabras: ["llamar", "llamada", "marcar", "telefono", "hacer"],
    permiso: "softphone:usar",
    pasos: [
      { ruta: "/", titulo: "Marca el número", texto: "Escribe una extensión (1002) o un número de afuera (3001234567) en el teclado." },
      { ruta: "/", titulo: "Llama", texto: "Pulsa el botón verde. Si dice que no hay conexión, revisa los datos o el wifi y espera unos segundos." },
    ],
  },
  {
    id: "trabajar-agente",
    titulo: "Empezar a trabajar como agente",
    descripcion: "Conectarte a campañas y grupos y quedar listo.",
    palabras: ["agente", "trabajar", "listo", "pausa", "consola", "empezar", "turno"],
    permiso: "agente:operar",
    pasos: [
      { ruta: "/administrar/agente", titulo: "Empieza", texto: "Marca las campañas o grupos que vas a atender y pulsa «Empezar a trabajar». Acepta el micrófono si te lo pide." },
      { ruta: "/administrar/agente", titulo: "Listo o en pausa", texto: "Con «Listo» te llegan llamadas; con «Pausa» dejan de llegar. Al colgar, elige cómo terminó la llamada." },
    ],
  },
  {
    id: "saludo-buzon",
    titulo: "Grabar el saludo de mi buzón",
    descripcion: "Con *98 desde el teléfono.",
    palabras: ["buzon", "saludo", "mensaje", "grabar", "contestador", "98"],
    permiso: "softphone:usar",
    pasos: [
      { ruta: "/", titulo: "Marca *98", texto: "Graba tu saludo después del tono y termina con # o colgando. Al final te lo repite." },
    ],
  },
  {
    id: "buzon-remoto",
    titulo: "Escuchar mi buzón desde otro teléfono",
    descripcion: "Ponerle un PIN y marcar *96.",
    palabras: ["buzon", "pin", "remoto", "otro telefono", "celular", "escuchar", "mensajes", "96"],
    permiso: "llamadas:ver_propias",
    pasos: [
      { ruta: "/administrar/buzon", titulo: "Ponle un PIN", texto: "Abajo, en «Escuchar desde otro teléfono», escribe un PIN de 4 a 8 números y guárdalo." },
      { ruta: "/", titulo: "Marca *96", texto: "Desde cualquier extensión: *96, luego tu extensión y #, y tu PIN y #." },
    ],
  },
  {
    id: "escuchar-grabacion",
    titulo: "Escuchar una grabación",
    descripcion: "El audio de una llamada grabada.",
    palabras: ["grabacion", "escuchar", "audio", "grabada"],
    permiso: "llamadas:ver_propias",
    pasos: [
      { ruta: "/llamadas", titulo: "Abre la llamada", texto: "Toca la llamada en la lista: si se grabó, en su detalle aparece el reproductor." },
    ],
  },
  {
    id: "supervisar-agente",
    titulo: "Escuchar o susurrar a un agente",
    descripcion: "Monitorear una llamada en curso.",
    palabras: ["supervisar", "escuchar", "susurrar", "monitorear", "en vivo", "agente"],
    permiso: "supervision:intervenir",
    pasos: [
      { ruta: "/administrar/supervision", titulo: "Elige al agente", texto: "En un agente que está en llamada, elige «Escuchar» (nadie te oye) o «Susurrar» (solo te oye el agente)." },
    ],
  },
  {
    id: "crear-extension",
    titulo: "Crear una extensión",
    descripcion: "Un número interno con su clave.",
    palabras: ["extension", "telefono", "anexo", "sip", "clave", "interno", "crear"],
    permiso: "telefonia:gestionar",
    pasos: [
      { ruta: "/administrar/extensiones", titulo: "Nueva extensión", texto: "Pulsa «Nueva extensión», escribe el número (por ejemplo 1005) y una clave segura, y guarda." },
    ],
  },
  {
    id: "agregar-persona",
    titulo: "Agregar una persona",
    descripcion: "Darle acceso con su rol.",
    palabras: ["usuario", "persona", "agente", "empleado", "acceso", "rol", "agregar"],
    permiso: "usuarios:gestionar",
    pasos: [
      { ruta: "/administrar/usuarios", titulo: "Nuevo usuario", texto: "Pulsa «Nuevo usuario», pon nombre, usuario, clave y rol, y guarda. Comparte la clave de forma segura." },
    ],
  },
  {
    id: "numero-entrante",
    titulo: "Decidir a dónde va un número",
    descripcion: "Tu número a una persona, un grupo o el buzón.",
    palabras: ["numero", "entrante", "did", "ruta", "recibir", "llaman"],
    permiso: "telefonia:gestionar",
    pasos: [
      { ruta: "/administrar/rutas-entrantes", titulo: "Nueva ruta", texto: "Pulsa «Nueva ruta entrante», escribe tu número tal como te lo dio el operador y elige a dónde va." },
    ],
  },
  {
    id: "conectar-proveedor",
    titulo: "Conectar el proveedor de telefonía",
    descripcion: "La línea con tu operador.",
    palabras: ["proveedor", "troncal", "operador", "trunk", "conectar"],
    permiso: "telefonia:gestionar",
    pasos: [
      { ruta: "/administrar/troncales", titulo: "Nueva troncal", texto: "Pulsa «Nueva troncal» y escribe el servidor, usuario y clave que te dio el operador. Con plantillas es más fácil desde el panel web." },
    ],
  },
  {
    id: "crear-grupo",
    titulo: "Crear un grupo de atención",
    descripcion: "Varias personas para el mismo número.",
    palabras: ["grupo", "cola", "atencion", "fila"],
    permiso: "colas:gestionar",
    pasos: [
      { ruta: "/administrar/colas", titulo: "Nueva cola", texto: "Pulsa «Nueva cola», ponle nombre y elige quiénes atienden y cómo suena." },
    ],
  },
  {
    id: "base-predictiva",
    titulo: "Lanzar una campaña predictiva",
    descripcion: "Crearla aquí; el Excel se sube en el panel web.",
    palabras: ["base", "predictiva", "predictivo", "excel", "campana", "marcador", "lanzar"],
    permiso: "campanas:gestionar",
    pasos: [
      { ruta: "/administrar/campanas", titulo: "Nueva campaña", texto: "Pulsa «Nueva campaña», elige «Mis agentes» y el método «Predictivo»." },
      { ruta: "/administrar/campanas", titulo: "Los clientes", texto: "El Excel se sube desde el panel web: Campañas › Ver › Cargar Excel. Desde aquí ves el avance y la inicias." },
    ],
  },
];

export const guiaPorId = (id: string) => GUIAS.find((g) => g.id === id);

const normalizar = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]/g, " ");

/** Búsqueda local, sin IA (la misma regla del panel). */
export function buscarGuias(texto: string, puede: (p: string) => boolean, max = 2): Guia[] {
  const q = ` ${normalizar(texto).replace(/\s+/g, " ")} `;
  const terminos = q.split(" ").filter((t) => t.length > 2);
  if (!terminos.length) return [];
  const coincide = (p: string) =>
    p.includes(" ") ? q.includes(` ${p} `) : terminos.some((t) => t === p || (t.length >= 5 && p.length >= 5 && t.slice(0, 5) === p.slice(0, 5)));
  const puntuadas = GUIAS.filter((g) => g.permiso === null || puede(g.permiso))
    .map((g) => {
      const titulo = ` ${normalizar(g.titulo)} `;
      let puntos = 0;
      for (const p of g.palabras) if (coincide(p)) puntos += p.includes(" ") ? 3 : 2;
      for (const t of terminos) if (titulo.includes(` ${t} `)) puntos += 1;
      return { g, puntos };
    })
    .filter((x) => x.puntos >= 3)
    .sort((a, b) => b.puntos - a.puntos);
  const mejor = puntuadas[0]?.puntos ?? 0;
  return puntuadas.filter((x) => x.puntos >= mejor * 0.6).slice(0, max).map((x) => x.g);
}

// --- La guía en curso: compartida por el asistente y el aviso flotante ---------------------

export interface EnCurso {
  id: string;
  paso: number;
}

let actual: EnCurso | null = null;
const oyentes = new Set<() => void>();

function fijar(e: EnCurso | null) {
  actual = e;
  oyentes.forEach((f) => f());
}

export const guia = {
  iniciar: (id: string) => guiaPorId(id) && fijar({ id, paso: 0 }),
  mover: (delta: number) => actual && fijar({ ...actual, paso: Math.max(0, actual.paso + delta) }),
  salir: () => fijar(null),
};

export function useGuiaEnCurso(): EnCurso | null {
  return useSyncExternalStore(
    (f) => {
      oyentes.add(f);
      return () => oyentes.delete(f);
    },
    () => actual,
    () => actual
  );
}
