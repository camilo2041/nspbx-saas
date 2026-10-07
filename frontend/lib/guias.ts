import { PERMISOS } from "@/lib/types";

/**
 * Guías en pantalla: recorridos cortos que señalan en el panel dónde se hace
 * cada cosa (components/guia.tsx los muestra). Cada paso apunta a un elemento
 * marcado con `data-guia="…"` (o la prop `guia` de los componentes de ui.tsx).
 *
 * Los ids van también en backend/app/api/assistant.py (GUIAS), para que el
 * asistente pueda ofrecerlas con `[[guia:id]]`; una prueba exige que coincidan.
 */
export interface PasoGuia {
  /** Pantalla donde vive el paso. Si la persona está en otra, primero se le señala en el menú. */
  ruta: string;
  /** Valor de `data-guia` del elemento a señalar; sin él, el paso es solo texto. */
  marca?: string;
  titulo: string;
  texto: string;
  /** Al pulsar el elemento señalado se pasa solo al siguiente paso. */
  alPulsar?: boolean;
}

export interface Guia {
  id: string;
  titulo: string;
  descripcion: string;
  /** Palabras con las que alguien la buscaría (sin tildes, en minúscula). */
  palabras: string[];
  permiso: string | null;
  pasos: PasoGuia[];
}

/** Nombre en el menú de cada pantalla, para «entra a X». */
export const NOMBRE_PANTALLA: Record<string, string> = {
  "/softphone": "Softphone",
  "/calls": "Llamadas",
  "/buzon": "Buzón de voz",
  "/agente": "Consola de agente",
  "/supervision": "Supervisión",
  "/calidad": "Calidad",
  "/reportes": "Reportes",
  "/crm": "Clientes (CRM)",
  "/extensions": "Extensiones",
  "/trunks": "Proveedor de telefonía",
  "/inbound-routes": "Números entrantes",
  "/queues": "Grupos de atención",
  "/voicebots": "Voizbots",
  "/campaigns": "Campañas",
  "/users": "Usuarios",
  "/settings": "Ajustes",
};

const CARGAR_EXCEL: PasoGuia[] = [
  {
    ruta: "/campaigns",
    marca: "clientes:elegir-archivo",
    titulo: "Sube el Excel",
    texto:
      "Elige tu archivo .xlsx o .csv. La primera fila debe tener los nombres de las columnas, y una de ellas el teléfono. Antes de cargar te mostramos qué entendimos de cada columna.",
  },
  {
    ruta: "/campaigns",
    marca: "clientes:cargar",
    titulo: "Revisa y carga",
    texto:
      "Confirma cuál columna es el teléfono (y el nombre, si lo hay). Los números repetidos o en «no llamar» se saltan solos. Pulsa «Cargar».",
    alPulsar: true,
  },
];

export const GUIAS: Guia[] = [
  {
    id: "base-predictiva",
    titulo: "Cargar una base y lanzar una campaña predictiva",
    descripcion: "Crear la campaña, subir el Excel de clientes, elegir agentes e iniciar.",
    palabras: ["base", "predictiva", "predictivo", "excel", "campana", "marcador", "cargar", "clientes", "lanzar", "lista"],
    permiso: PERMISOS.campanas,
    pasos: [
      { ruta: "/campaigns", marca: "campanas:nueva", titulo: "Crea la campaña", texto: "Pulsa «+ Nueva campaña».", alPulsar: true },
      { ruta: "/campaigns", marca: "campana:nombre", titulo: "Ponle un nombre", texto: "Uno que la reconozcan los agentes, por ejemplo «Cartera octubre»." },
      {
        ruta: "/campaigns",
        marca: "campana:con-agentes",
        titulo: "¿Quién atiende?",
        texto: "Para predictivo elige «Mis agentes»: la central marca y pasa al agente solo las llamadas que contestan.",
        alPulsar: true,
      },
      {
        ruta: "/campaigns",
        marca: "campana:metodo-predictivo",
        titulo: "Elige «Predictivo»",
        texto: "Marca varios números por agente libre y se ajusta solo para no dejar clientes esperando.",
        alPulsar: true,
      },
      { ruta: "/campaigns", marca: "campana:crear", titulo: "Crea", texto: "Pulsa «Crear». Enseguida se abre el asistente para cargar los clientes.", alPulsar: true },
      ...CARGAR_EXCEL,
      { ruta: "/campaigns", marca: "asistente:siguiente", titulo: "Sigue con los agentes", texto: "Pulsa «Siguiente».", alPulsar: true },
      {
        ruta: "/campaigns",
        titulo: "Marca a los agentes",
        texto:
          "Marca quiénes trabajan la campaña (se guarda al marcar). Después cada uno abre la Consola de agente y pulsa «Empezar a trabajar». Luego pulsa «Siguiente».",
      },
      {
        ruta: "/campaigns",
        marca: "asistente:iniciar",
        titulo: "Revisa e inicia",
        texto: "Lo que esté en rojo impide llamar. Puedes iniciar ya: empieza a marcar en cuanto los agentes entren.",
        alPulsar: true,
      },
    ],
  },
  {
    id: "base-a-campana-existente",
    titulo: "Agregar más clientes a una campaña",
    descripcion: "Subir otro Excel a una campaña que ya existe.",
    palabras: ["agregar", "subir", "excel", "base", "clientes", "campana", "existente", "recargar", "mas"],
    permiso: PERMISOS.campanas,
    pasos: [
      { ruta: "/campaigns", marca: "campana:ver", titulo: "Abre la campaña", texto: "Pulsa «Ver» en la campaña a la que quieres sumar clientes.", alPulsar: true },
      { ruta: "/campaigns", marca: "campana:cargar-excel", titulo: "Cargar Excel", texto: "Pulsa «Cargar Excel».", alPulsar: true },
      ...CARGAR_EXCEL,
    ],
  },
  {
    id: "crear-extension",
    titulo: "Crear una extensión (teléfono)",
    descripcion: "Dar de alta un número interno con su clave para un teléfono o la app.",
    palabras: ["extension", "telefono", "anexo", "sip", "clave", "interno", "crear"],
    permiso: PERMISOS.telefonia,
    pasos: [
      { ruta: "/extensions", marca: "extensiones:nueva", titulo: "Nueva extensión", texto: "Pulsa «+ Nueva extensión».", alPulsar: true },
      {
        ruta: "/extensions",
        titulo: "Número y clave",
        texto:
          "Escribe el número interno (por ejemplo 1005) y una clave segura. El «Nombre» es lo que verán al recibir la llamada. Guarda: con ese número y clave se configura el teléfono o la app.",
      },
    ],
  },
  {
    id: "conectar-proveedor",
    titulo: "Conectar el proveedor de telefonía",
    descripcion: "La troncal con tu operador para llamar a celulares y fijos.",
    palabras: ["proveedor", "troncal", "operador", "trunk", "conectar", "salir", "llamar afuera", "sip"],
    permiso: PERMISOS.telefonia,
    pasos: [
      { ruta: "/trunks", marca: "proveedores:nuevo", titulo: "Conectar proveedor", texto: "Pulsa «+ Conectar proveedor».", alPulsar: true },
      {
        ruta: "/trunks",
        titulo: "Datos del operador",
        texto:
          "Si tu operador está en la lista de plantillas, elígelo y se llena casi todo. Si no, escribe el servidor, usuario y clave que te dio. Guarda y usa «Probar» para confirmar que conecta.",
      },
    ],
  },
  {
    id: "numero-entrante",
    titulo: "Decidir a dónde va un número que llaman",
    descripcion: "Enviar tu número a un grupo, un menú, una persona o el buzón, con horario.",
    palabras: ["numero", "entrante", "did", "ruta", "recibir", "horario", "llaman", "entrada"],
    permiso: PERMISOS.telefonia,
    pasos: [
      { ruta: "/inbound-routes", marca: "entrantes:nuevo", titulo: "Configurar número", texto: "Pulsa «+ Configurar número».", alPulsar: true },
      {
        ruta: "/inbound-routes",
        titulo: "A dónde va",
        texto:
          "Escribe tu número tal como te lo dio el operador. Elige a dónde va la llamada en horario y, si quieres, a dónde va fuera de horario. Guarda.",
      },
    ],
  },
  {
    id: "crear-grupo",
    titulo: "Crear un grupo de atención (cola)",
    descripcion: "Varias personas atienden el mismo número, con música y posición en la fila.",
    palabras: ["grupo", "cola", "queue", "atencion", "agentes", "fila", "musica", "devolucion"],
    permiso: PERMISOS.colas,
    pasos: [
      { ruta: "/queues", marca: "grupos:nuevo", titulo: "Nuevo grupo", texto: "Pulsa «+ Nuevo grupo».", alPulsar: true },
      {
        ruta: "/queues",
        titulo: "Cómo suena y quién atiende",
        texto: "Ponle nombre, elige cómo suena (todos a la vez o por turnos) y a dónde va la llamada si nadie contesta.",
      },
      {
        ruta: "/queues",
        marca: "grupo:devolucion",
        titulo: "Devolución de llamada (opcional)",
        texto: "Si lo activas, quien espera puede marcar 1 para que lo llamen sin perder su turno.",
      },
    ],
  },
  {
    id: "agregar-persona",
    titulo: "Agregar una persona (usuario)",
    descripcion: "Darle acceso al panel con su rol y su extensión.",
    palabras: ["usuario", "persona", "agente", "empleado", "acceso", "rol", "agregar", "crear"],
    permiso: PERMISOS.usuarios,
    pasos: [
      { ruta: "/users", marca: "usuarios:nuevo", titulo: "Agregar persona", texto: "Pulsa «+ Agregar persona».", alPulsar: true },
      {
        ruta: "/users",
        titulo: "Datos y rol",
        texto: "Nombre, usuario y rol (asesor, supervisor…). Puedes crearle la extensión en el mismo paso. Guarda y comparte la clave de forma segura.",
      },
    ],
  },
  {
    id: "crear-ivr",
    titulo: "Crear un menú de opciones (IVR) o un voizbot",
    descripcion: "«Marque 1 para ventas…» o un asistente de voz con IA.",
    palabras: ["ivr", "menu", "opciones", "marque", "voizbot", "bot", "flujo", "asistente de voz"],
    permiso: PERMISOS.voizbotsGestionar,
    pasos: [
      { ruta: "/voicebots", marca: "voizbots:nuevo", titulo: "Nuevo voizbot", texto: "Pulsa «+ Nuevo voizbot» y ponle un nombre.", alPulsar: true },
      {
        ruta: "/voicebots",
        marca: "voizbot:flujo",
        titulo: "Arma el flujo",
        texto:
          "Pulsa «Editar flujo». Con bloques de menú (teclas), horario y destinos (grupo, buzón, número) armas el IVR. Después asígnalo a un número en «Números entrantes».",
      },
    ],
  },
  {
    id: "trabajar-agente",
    titulo: "Empezar a trabajar como agente",
    descripcion: "Conectarse a campañas y grupos y quedar listo para recibir llamadas.",
    palabras: ["agente", "trabajar", "listo", "pausa", "consola", "empezar", "turno"],
    permiso: PERMISOS.agente,
    pasos: [
      {
        ruta: "/agente",
        marca: "agente:empezar",
        titulo: "Empezar a trabajar",
        texto: "Marca las campañas o grupos que vas a atender y pulsa «Empezar a trabajar». Acepta el micrófono si el navegador lo pide.",
        alPulsar: true,
      },
      { ruta: "/agente", marca: "agente:listo", titulo: "Quedar listo", texto: "Con «Listo» empiezan a llegarte llamadas; con «Pausa» dejan de llegar." },
    ],
  },
  {
    id: "escuchar-grabacion",
    titulo: "Escuchar una grabación",
    descripcion: "Buscar una llamada y reproducir su audio.",
    palabras: ["grabacion", "escuchar", "audio", "grabada", "llamada", "descargar"],
    permiso: PERMISOS.llamadasPropias,
    pasos: [
      {
        ruta: "/calls",
        marca: "llamadas:reproducir",
        titulo: "Reproducir",
        texto: "Usa los filtros de arriba para encontrar la llamada y pulsa ▶ en la columna «Grabación». Si no aparece el botón, esa llamada no se grabó.",
      },
    ],
  },
  {
    id: "reporte-entrantes",
    titulo: "Ver el nivel de servicio y el abandono",
    descripcion: "El reporte de llamadas entrantes por grupo y por hora.",
    palabras: ["reporte", "nivel de servicio", "abandono", "entrantes", "espera", "estadisticas", "informe"],
    permiso: PERMISOS.reportes,
    pasos: [
      { ruta: "/reportes", marca: "reportes:entrantes", titulo: "Llamadas entrantes", texto: "Pulsa la pestaña «Llamadas entrantes».", alPulsar: true },
      {
        ruta: "/reportes",
        titulo: "Elige el rango",
        texto: "Ajusta «Desde» y «Hasta» y la meta en segundos. Abajo ves contestadas, abandonadas, espera y nivel de servicio por grupo. Puedes bajarlo en CSV.",
      },
    ],
  },
  {
    id: "evaluar-llamada",
    titulo: "Evaluar la calidad de una llamada",
    descripcion: "Calificar con los criterios de la empresa, a mano o con sugerencia de IA.",
    palabras: ["calidad", "evaluar", "calificar", "monitoreo", "criterios", "nota", "puntaje"],
    permiso: PERMISOS.supervisionVer,
    pasos: [
      { ruta: "/calidad", marca: "calidad:evaluar", titulo: "Elige la llamada", texto: "Pulsa «Evaluar» en una llamada grabada.", alPulsar: true },
      {
        ruta: "/calidad",
        marca: "calidad:sugerir",
        titulo: "Sugerencia de la IA (opcional)",
        texto: "La IA escucha y propone una nota por criterio. Revisa, corrige lo que haga falta y guarda.",
      },
    ],
  },
  {
    id: "saludo-buzon",
    titulo: "Grabar el saludo de mi buzón",
    descripcion: "Subir un audio o grabarlo desde el teléfono con *98.",
    palabras: ["buzon", "saludo", "mensaje", "voz", "grabar", "contestador", "98"],
    permiso: PERMISOS.llamadasPropias,
    pasos: [
      {
        ruta: "/buzon",
        marca: "buzon:saludo",
        titulo: "Tu saludo",
        texto: "Desde tu teléfono marca *98 y graba después del tono. O súbelo aquí como archivo de audio.",
      },
      { ruta: "/buzon", marca: "buzon:subir-saludo", titulo: "Subir audio", texto: "Pulsa para elegir el archivo (mp3 o wav)." },
    ],
  },
  {
    id: "buzon-remoto",
    titulo: "Escuchar mi buzón desde otro teléfono",
    descripcion: "Ponerle un PIN y marcar *96 desde cualquier extensión o un número entrante.",
    palabras: ["buzon", "pin", "remoto", "otro telefono", "celular", "afuera", "escuchar", "mensajes", "96"],
    permiso: PERMISOS.llamadasPropias,
    pasos: [
      {
        ruta: "/buzon",
        marca: "buzon:pin",
        titulo: "Ponle un PIN",
        texto: "Escribe un PIN de 4 a 8 números (no 1111, 1234 ni tu extensión) y guárdalo.",
      },
      {
        ruta: "/buzon",
        titulo: "Marca *96",
        texto:
          "Desde cualquier extensión marca *96, luego tu extensión y numeral, y tu PIN y numeral. Para hacerlo desde el celular, un administrador puede poner un número entrante con destino «Escuchar mensajes del buzón».",
      },
    ],
  },
  {
    id: "festivos",
    titulo: "Cerrar en festivos o en una fecha especial",
    descripcion: "Que los números y el IVR atiendan como «cerrado» los festivos.",
    palabras: ["festivo", "feriado", "cerrar", "horario", "fecha", "diciembre", "vacaciones", "calendario"],
    permiso: PERMISOS.ajustes,
    pasos: [
      {
        ruta: "/settings",
        marca: "festivos:cerrar",
        titulo: "Festivos de Colombia",
        texto: "Activa este interruptor para cerrar en los festivos nacionales. Se guarda al cambiarlo.",
      },
      {
        ruta: "/settings",
        marca: "ajustes:festivos",
        titulo: "Fechas propias",
        texto: "Abajo agregas cierres propios (inventario, 24 de diciembre hasta el mediodía) con su franja abierta, si la hay.",
      },
    ],
  },
  {
    id: "supervisar-agente",
    titulo: "Escuchar o susurrar a un agente en vivo",
    descripcion: "Monitorear una llamada en curso sin que el cliente lo note.",
    palabras: ["supervisar", "escuchar", "susurrar", "monitorear", "en vivo", "espiar", "intervenir", "agente"],
    permiso: PERMISOS.supervisionIntervenir,
    pasos: [
      {
        ruta: "/supervision",
        marca: "supervision:escuchar",
        titulo: "Escuchar",
        texto: "En la fila del agente pulsa «Escuchar» (nadie te oye) o «Susurrar» (solo el agente te oye). Necesitas tu softphone conectado.",
      },
    ],
  },
  {
    id: "importar-contactos",
    titulo: "Importar contactos al CRM",
    descripcion: "Subir una lista de clientes al CRM de la empresa.",
    palabras: ["importar", "contactos", "crm", "clientes", "csv", "excel", "lista"],
    permiso: PERMISOS.crmGestionar,
    pasos: [
      { ruta: "/crm", marca: "crm:importar", titulo: "Importar", texto: "Pulsa la pestaña «Importar».", alPulsar: true },
      { ruta: "/crm", marca: "crm:elegir-archivo", titulo: "Elige el archivo", texto: "Sube el Excel o CSV con los nombres de columnas en la primera fila." },
      { ruta: "/crm", marca: "crm:importar-ya", titulo: "Importa", texto: "Revisa qué columna es el teléfono y pulsa importar.", alPulsar: true },
    ],
  },
  {
    id: "llamar-softphone",
    titulo: "Hacer una llamada desde el navegador",
    descripcion: "Usar el softphone del panel, sin teléfono físico.",
    palabras: ["llamar", "llamada", "softphone", "marcar", "navegador", "telefono", "hacer"],
    permiso: PERMISOS.softphone,
    pasos: [
      { ruta: "/softphone", marca: "softphone:numero", titulo: "Escribe el número", texto: "Una extensión (1002) o un número de afuera (3001234567)." },
      { ruta: "/softphone", marca: "softphone:llamar", titulo: "Llamar", texto: "Pulsa «Llamar». Si está gris, espera a que diga «Conectado».", alPulsar: true },
    ],
  },
];

export const guiaPorId = (id: string): Guia | undefined => GUIAS.find((g) => g.id === id);

const normalizar = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]/g, " ");

/** Búsqueda local (sin IA): guías permitidas, ordenadas por coincidencias. */
export function buscarGuias(texto: string, puede: (p: string) => boolean, max = 3): Guia[] {
  const q = ` ${normalizar(texto).replace(/\s+/g, " ")} `;
  const terminos = q.split(" ").filter((t) => t.length > 2);
  if (!terminos.length) return [];
  // Una palabra cuenta entera o por su raíz («predictivo» encuentra «predictiva»).
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
  // Solo las que compiten con la mejor: una coincidencia suelta no es una sugerencia.
  const mejor = puntuadas[0]?.puntos ?? 0;
  return puntuadas
    .filter((x) => x.puntos >= mejor * 0.6)
    .slice(0, max)
    .map((x) => x.g);
}

/** Arranca una guía desde cualquier parte del panel. */
export function iniciarGuia(id: string) {
  window.dispatchEvent(new CustomEvent("nspbx:guia", { detail: id }));
}
