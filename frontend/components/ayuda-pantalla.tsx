"use client";

import { useEffect, useRef, useState } from "react";

interface Ayuda {
  que: string;
  pasos?: string[];
  /** Pregunta que se le hace al asistente con «Preguntar al asistente». */
  pregunta: string;
}

// «¿Qué es esto?» de cada pantalla, para quien no sabe de telefonía: qué es,
// para qué sirve y los pasos típicos. El asistente responde lo que falte.
const AYUDA: Record<string, Ayuda> = {
  "/": {
    que: "El resumen de tu central. Arriba está la lista «Pon en marcha tu central» con lo que falta para dejarla funcionando.",
    pregunta: "¿Por dónde empiezo a configurar la central?",
  },
  "/configurar": {
    que: "Un asistente que deja la central armada en pocos pasos: proveedor, equipo y a dónde van las llamadas.",
    pregunta: "¿Qué hace el asistente de configuración?",
  },
  "/extensions": {
    que: "Una extensión es el número interno de una persona (101, 102…). Con ella se conecta su softphone, la app o un teléfono de escritorio, y la usa para llamar y recibir llamadas.",
    pasos: [
      "Lo más fácil: crea a la persona en Usuarios con «Agregar persona»; su extensión se crea sola.",
      "Aquí puedes ver la clave SIP para configurar un teléfono de escritorio.",
    ],
    pregunta: "¿Qué es una extensión y cómo conecto un teléfono a ella?",
  },
  "/buzon": {
    que: "Los mensajes de voz que te dejaron cuando no contestaste (o tenías «no molestar»). Si tu usuario tiene correo, también te llega cada mensaje por correo.",
    pasos: [
      "El buzón se activa por extensión (Extensiones → Buzón de voz).",
      "Para dejar un mensaje directo, marca *99 y la extensión (por ejemplo *99101).",
      "En Números entrantes o en un grupo puedes mandar las llamadas al buzón de alguien, por ejemplo fuera de horario.",
    ],
    pregunta: "¿Cómo funciona el buzón de voz?",
  },
  "/calidad": {
    que: "Para mejorar la atención: escuchas llamadas grabadas y las calificas con los criterios de tu empresa. La IA puede leer la llamada y sugerir la calificación; tú la revisas y guardas.",
    pasos: [
      "En «Criterios», define qué se evalúa (vienen unos de ejemplo).",
      "En «Evaluar llamadas», abre una llamada, escúchala y califica cada punto (o pulsa «Sugerir con IA»).",
      "En «Resultados» ves el promedio de cada persona. Cada persona ve sus evaluaciones en esta misma pantalla.",
    ],
    pregunta: "¿Cómo evalúo la calidad de las llamadas?",
  },
  "/trunks": {
    que: "El proveedor de telefonía (técnico: troncal SIP) es la línea que conecta tu central con la red telefónica: por ahí entran y salen las llamadas externas.",
    pasos: [
      "Pide a tu proveedor (Claro, Tigo, ETB, Movistar…) el servidor, el usuario y la clave de tu línea SIP.",
      "Conéctalo aquí y pulsa «Probar conexión»: debe decir «Conectado».",
      "Haz una «Llamada de prueba» a tu celular.",
    ],
    pregunta: "¿Qué es una troncal SIP y qué datos le pido a mi proveedor?",
  },
  "/inbound-routes": {
    que: "Aquí dices a dónde va una llamada cuando alguien marca tu número: a una persona, a su buzón de voz, a un grupo de atención o al voizbot. Puedes ponerle horario de atención.",
    pasos: ["Si tienes un solo número, usa «Cualquier número».", "Elige a dónde va y, si quieres, qué pasa fuera de horario."],
    pregunta: "¿Cómo hago que las llamadas a mi número suenen en mi equipo?",
  },
  "/queues": {
    que: "Un grupo de atención (técnico: cola) es un conjunto de personas que atienden las mismas llamadas, como Ventas o Soporte. La llamada suena en el grupo y la toma quien esté libre.",
    pasos: ["Crea el grupo y marca quiénes atienden.", "Luego, en Números entrantes, envía tu número a este grupo."],
    pregunta: "¿Para qué sirve un grupo de atención y cómo lo armo?",
  },
  "/outbound-routes": {
    que: "Las reglas de salida dicen a qué números se puede llamar y por qué proveedor sale cada uno. Sin reglas, todo sale por tus proveedores; con reglas, solo lo que cubran.",
    pasos: ["Para Colombia, «Crear reglas de Colombia» deja celulares, fijos y 01 8000 listos."],
    pregunta: "¿Necesito reglas de salida?",
  },
  "/logs": {
    que: "Lo que hace la central por dentro, en vivo. Sirve para que soporte técnico diagnostique problemas; no hace falta para el día a día.",
    pregunta: "¿Cómo leo el registro técnico de la central?",
  },
  "/users": {
    que: "Las personas de tu equipo: con qué usuario entran, qué rol tienen (qué pueden hacer) y su extensión para llamar.",
    pasos: ["Usa «Agregar persona»: el usuario y la extensión se crean juntos.", "Comparte el usuario y la contraseña por un medio seguro."],
    pregunta: "¿Qué rol le doy a cada persona de mi equipo?",
  },
  "/campaigns": {
    que: "Una campaña llama a una lista de clientes, con tus agentes o con un voizbot. El recuadro de cada campaña dice qué le falta para empezar a llamar.",
    pasos: ["Crea la campaña.", "Elige los agentes y carga los números.", "Pulsa «Iniciar»."],
    pregunta: "¿Cómo armo una campaña predictiva con mis agentes?",
  },
  "/agente": {
    que: "Tu puesto de trabajo como agente: aquí recibes y haces las llamadas de tus campañas y registras el resultado de cada una.",
    pasos: ["Pulsa «Empezar a trabajar».", "Cuando termine cada llamada, elige el resultado (disposición)."],
    pregunta: "¿Cómo trabajo en la consola de agente?",
  },
  "/contact-center": {
    que: "Las pausas (almuerzo, baño, capacitación…) y los resultados de llamada (venta, no contesta, volver a llamar…) que usan tus agentes.",
    pregunta: "¿Qué son las pausas y disposiciones?",
  },
  "/settings": {
    que: "Ajustes generales de tu empresa: horarios, grabación, voz del voizbot y la burbuja de llamada para tu sitio web.",
    pregunta: "¿Qué ajustes debo revisar al empezar?",
  },
  "/softphone": {
    que: "Un teléfono dentro del navegador. Con él llamas y recibes llamadas en tu extensión sin instalar nada.",
    pasos: ["Pulsa Conectar y permite el micrófono.", "Marca un número o una extensión."],
    pregunta: "¿Cómo uso el softphone del navegador?",
  },
};

function ayudaDe(pathname: string): Ayuda | null {
  const ruta = Object.keys(AYUDA)
    .filter((r) => pathname === r || (r !== "/" && pathname.startsWith(r)))
    .sort((a, b) => b.length - a.length)[0];
  return ruta ? AYUDA[ruta] : null;
}

/** Botón «¿Qué es esto?» de la cabecera, con la ayuda de la pantalla actual. */
export function AyudaPantalla({ pathname, titulo }: { pathname: string; titulo: string }) {
  const [abierta, setAbierta] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const ayuda = ayudaDe(pathname);

  useEffect(() => {
    if (!abierta) return;
    const fuera = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierta(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setAbierta(false);
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", esc);
    };
  }, [abierta]);

  if (!ayuda) return null;

  return (
    <div ref={caja} className="relative">
      <button
        type="button"
        onClick={() => setAbierta(!abierta)}
        aria-expanded={abierta}
        className="press flex items-center gap-1.5 rounded-xl border border-line bg-surface-2 px-2.5 py-1.5 text-[13px] text-fg-soft transition-colors hover:border-line-strong hover:text-fg"
      >
        <span aria-hidden className="flex h-4 w-4 items-center justify-center rounded-full bg-brand text-[10px] font-bold text-white">
          ?
        </span>
        <span className="hidden sm:inline">¿Qué es esto?</span>
      </button>
      {abierta && (
        <div
          role="dialog"
          aria-label={`Ayuda: ${titulo}`}
          className="animate-fade-soft absolute right-0 top-11 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-3)]"
        >
          <p className="text-sm font-semibold text-fg">{titulo}</p>
          <p className="mt-1 text-sm leading-relaxed text-fg-soft">{ayuda.que}</p>
          {ayuda.pasos && (
            <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-fg-soft">
              {ayuda.pasos.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ol>
          )}
          <button
            type="button"
            className="mt-3 text-sm font-medium text-brand underline"
            onClick={() => {
              setAbierta(false);
              window.dispatchEvent(new CustomEvent("nspbx:preguntar", { detail: ayuda.pregunta }));
            }}
          >
            Preguntarle al asistente: «{ayuda.pregunta}»
          </button>
        </div>
      )}
    </div>
  );
}
