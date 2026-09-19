"use client";

import { useRouter, usePathname } from "next/navigation";
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PERMISOS } from "@/lib/types";

interface Msg {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}

const KEY = "nspbx-asistente";
const MAX_HISTORIAL = 12;

// Pantallas que el asistente puede ofrecer como botón, con el permiso que
// pide cada una. El backend solo sugiere rutas de este catálogo; aquí se
// vuelve a comprobar para no mostrar un botón a una pantalla sin acceso.
const RUTAS: Record<string, { label: string; permiso: string | null }> = {
  "/": { label: "Dashboard", permiso: null },
  "/softphone": { label: "Softphone", permiso: PERMISOS.softphone },
  "/calls": { label: "Llamadas", permiso: PERMISOS.llamadasPropias },
  "/appointments": { label: "Citas", permiso: PERMISOS.citas },
  "/extensions": { label: "Extensiones", permiso: PERMISOS.telefonia },
  "/trunks": { label: "Troncales", permiso: PERMISOS.telefonia },
  "/inbound-routes": { label: "Rutas entrantes", permiso: PERMISOS.telefonia },
  "/queues": { label: "Colas", permiso: PERMISOS.colas },
  "/voicebots": { label: "Voizbots", permiso: PERMISOS.voizbotsVer },
  "/campaigns": { label: "Campañas", permiso: PERMISOS.campanas },
  "/ai-usage": { label: "Consumo IA", permiso: PERMISOS.consumoIa },
  "/users": { label: "Usuarios", permiso: PERMISOS.usuarios },
  "/settings": { label: "Ajustes", permiso: PERMISOS.ajustes },
};

const SUGERENCIAS_POR_PANTALLA: Record<string, string[]> = {
  "/": ["¿Cómo van las llamadas?", "¿Qué puedo hacer desde aquí?"],
  "/calls": ["¿Cuántas llamadas no se contestaron?", "¿Cómo escucho una grabación?"],
  "/extensions": ["¿Cómo creo una extensión?", "¿Cómo configuro mi teléfono?"],
  "/trunks": ["¿Qué es una troncal?", "¿Cómo conecto mi proveedor?"],
  "/settings": ["¿Cómo activo las llamadas internacionales?", "¿Dónde pongo la API key de IA?"],
  "/campaigns": ["¿Cómo lanzo una campaña?", "¿Cuántas campañas hay activas?"],
};
const SUGERENCIAS_BASE = ["¿Cómo hago una llamada?", "Resume el estado de mi central"];

/** Markdown mínimo y seguro: negrita, código, listas y saltos, sin HTML crudo. */
function Texto({ texto }: { texto: string }) {
  const en = (s: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => {
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong>;
      if (p.startsWith("`") && p.endsWith("`"))
        return <code key={i} className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[12px]">{p.slice(1, -1)}</code>;
      return p;
    });
  return (
    <div className="space-y-1.5">
      {texto.split("\n").map((l, i) => {
        if (!l.trim()) return null;
        const li = l.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)/);
        return li ? (
          <div key={i} className="flex gap-2 pl-1">
            <span className="text-brand">•</span>
            <span>{en(li[1])}</span>
          </div>
        ) : (
          <p key={i}>{en(l)}</p>
        );
      })}
    </div>
  );
}

/** Entrada: monta el chat por usuario (key) para que en un equipo compartido
 *  la conversación de un turno nunca aparezca en la sesión del siguiente. */
export function AssistantWidget() {
  const { usuario } = useAuth();
  const pathname = usePathname();
  if (!usuario || pathname === "/login" || pathname === "/webcall") return null;
  return <Chat key={usuario.id} uid={usuario.id} nombre={usuario.full_name} />;
}

function Chat({ uid, nombre }: { uid: number; nombre: string }) {
  const { puede } = useAuth();
  const clave = `${KEY}-${uid}`;
  const router = useRouter();
  const pathname = usePathname();
  const [abierto, setAbierto] = useState(false);
  const [ancho, setAncho] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    try {
      const g = typeof window !== "undefined" ? sessionStorage.getItem(clave) : null;
      return g ? (JSON.parse(g) as Msg[]) : [];
    } catch {
      return []; // storage bloqueado: arranca vacío
    }
  });
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);
  const [sinLeer, setSinLeer] = useState(false);
  const fin = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLTextAreaElement>(null);

  // La conversación sobrevive a la navegación entre pantallas (el widget
  // vive en el marco) y a recargar, pero no al cerrar la pestaña.
  useEffect(() => {
    try {
      sessionStorage.setItem(clave, JSON.stringify(msgs.slice(-MAX_HISTORIAL)));
    } catch {
      /* sin persistencia */
    }
  }, [msgs, clave]);

  useEffect(() => {
    fin.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, pensando, abierto]);

  useEffect(() => {
    if (abierto) {
      setTimeout(() => entrada.current?.focus(), 120);
    }
  }, [abierto]);

  // Ctrl/Cmd+J abre y cierra; Esc cierra.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setAbierto((a) => !a);
      } else if (e.key === "Escape") setAbierto(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const enviar = useCallback(
    async (contenido: string) => {
      const limpio = contenido.trim().slice(0, 2000);
      if (!limpio || pensando) return;
      const historial: Msg[] = [...msgs.filter((m) => !m.error), { role: "user", content: limpio }];
      setMsgs([...msgs, { role: "user", content: limpio }]);
      setTexto("");
      setPensando(true);
      try {
        const r = await api.post<{ reply: string }>("/api/assistant/chat", {
          messages: historial.slice(-MAX_HISTORIAL).map(({ role, content }) => ({ role, content })),
        });
        setMsgs((m) => [...m, { role: "assistant", content: r.reply }]);
        setSinLeer(!abierto);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "No se pudo conectar con el asistente";
        setMsgs((m) => [...m, { role: "assistant", content: msg, error: true }]);
      } finally {
        setPensando(false);
      }
    },
    [msgs, pensando, abierto]
  );

  const sugerencias = SUGERENCIAS_POR_PANTALLA[pathname] ?? SUGERENCIAS_BASE;

  /** Separa el texto de los marcadores [[ir:/ruta]] y los vuelve botones permitidos. */
  const partir = (contenido: string) => {
    const rutas: string[] = [];
    const limpio = contenido.replace(/\[\[ir:(\/[a-z-]*)\]\]/g, (_, r: string) => {
      const def = RUTAS[r];
      if (def && (def.permiso === null || puede(def.permiso)) && !rutas.includes(r)) rutas.push(r);
      return "";
    });
    return { limpio: limpio.trim(), rutas };
  };

  return (
    <>
      {abierto && (
        <div
          role="dialog"
          aria-label="Asistente"
          className={`animate-pop glass fixed z-[90] flex flex-col overflow-hidden rounded-3xl border border-line bg-surface/95 shadow-[var(--shadow-3)] transition-[width,height] duration-300
            inset-x-3 bottom-24 h-[min(70vh,560px)] sm:inset-x-auto sm:right-5 ${ancho ? "sm:h-[min(82vh,720px)] sm:w-[560px]" : "sm:h-[min(70vh,560px)] sm:w-[380px]"}`}
        >
          <header className="flex items-center gap-3 border-b border-line bg-gradient-to-r from-brand-soft to-info-soft/60 px-4 py-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 text-white shadow-[var(--shadow-brand)]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l1.9 4.6L18.5 9l-4.6 1.4L12 15l-1.9-4.6L5.5 9l4.6-1.4L12 3zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9L18 15z" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-fg">Asistente</div>
              <div className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-ok" /> Pregunta sobre tu central · Ctrl+J
              </div>
            </div>
            {msgs.length > 0 && (
              <button
                type="button"
                onClick={() => setMsgs([])}
                title="Nueva conversación"
                aria-label="Nueva conversación"
                className="press rounded-lg p-1.5 text-faint transition-colors hover:bg-surface-2 hover:text-fg"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v6h6M20 20v-6h-6M20 10A8 8 0 006.3 6.3L4 10m16 4l-2.3 3.7A8 8 0 014 14" />
                </svg>
              </button>
            )}
            <button
              type="button"
              onClick={() => setAncho((a) => !a)}
              title={ancho ? "Reducir" : "Ampliar"}
              aria-label={ancho ? "Reducir" : "Ampliar"}
              className="press hidden rounded-lg p-1.5 text-faint transition-colors hover:bg-surface-2 hover:text-fg sm:block"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path strokeLinecap="round" strokeLinejoin="round" d={ancho ? "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" : "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"} />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => setAbierto(false)}
              aria-label="Cerrar"
              className="press rounded-lg p-1.5 text-faint transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </header>

          <div className="no-scrollbar flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {msgs.length === 0 && (
              <div className="animate-fade-up space-y-3 py-2 text-center">
                <p className="text-sm font-medium text-fg">Hola, {nombre.split(" ")[0]} 👋</p>
                <p className="text-[13px] leading-relaxed text-muted">
                  Puedo explicarte el panel y contarte cómo van tus llamadas. Solo consulto; los cambios los haces tú.
                </p>
              </div>
            )}
            {msgs.map((m, i) => {
              const { limpio, rutas } = m.role === "assistant" ? partir(m.content) : { limpio: m.content, rutas: [] };
              return (
                <div key={i} className={`animate-fade-up flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[88%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
                      m.role === "user"
                        ? "rounded-br-md bg-gradient-to-br from-orange-500 to-amber-500 text-white"
                        : m.error
                        ? "rounded-bl-md bg-danger-soft text-danger-text"
                        : "rounded-bl-md bg-surface-2 text-fg-soft"
                    }`}
                  >
                    {m.role === "user" ? <span className="whitespace-pre-wrap">{limpio}</span> : <Texto texto={limpio} />}
                    {rutas.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {rutas.map((r) => (
                          <button
                            key={r}
                            type="button"
                            onClick={() => {
                              router.push(r);
                              setAbierto(false);
                            }}
                            className="press rounded-lg border border-line bg-surface px-2.5 py-1 text-[12px] font-medium text-brand-text transition-colors hover:border-brand"
                          >
                            Abrir {RUTAS[r].label} →
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {pensando && (
              <div className="flex justify-start">
                <div className="flex gap-1 rounded-2xl rounded-bl-md bg-surface-2 px-4 py-3" aria-label="Escribiendo">
                  {[0, 1, 2].map((d) => (
                    <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" style={{ animationDelay: `${d * 0.15}s` }} />
                  ))}
                </div>
              </div>
            )}
            <div ref={fin} />
          </div>

          {msgs.length === 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {sugerencias.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => enviar(s)}
                  className="press rounded-full border border-line bg-surface-2 px-3 py-1 text-[12px] text-fg-soft transition-colors hover:border-brand hover:text-brand-text"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              enviar(texto);
            }}
            className="flex items-end gap-2 border-t border-line p-3"
          >
            <textarea
              ref={entrada}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  enviar(texto);
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="Escribe tu pregunta…"
              className="max-h-28 min-h-[40px] flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3 py-2 text-[13px] text-fg outline-none transition-colors placeholder:text-faint focus:border-brand"
            />
            <button
              type="submit"
              disabled={!texto.trim() || pensando}
              aria-label="Enviar"
              className="press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand text-on-brand transition-opacity disabled:opacity-40"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          </form>
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          setSinLeer(false);
          setAbierto((a) => !a);
        }}
        aria-label={abierto ? "Cerrar asistente" : "Abrir asistente"}
        aria-expanded={abierto}
        className="press group fixed bottom-5 right-5 z-[90] flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-orange-500 to-amber-500 text-white shadow-[var(--shadow-brand)] transition-transform duration-200 hover:scale-105"
      >
        {sinLeer && !abierto && <span className="absolute right-1 top-1 h-3 w-3 rounded-full border-2 border-white bg-info" />}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-6 w-6 transition-transform duration-300 ${abierto ? "rotate-90 scale-0 absolute" : ""}`}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z" />
        </svg>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`h-6 w-6 transition-transform duration-300 ${abierto ? "" : "-rotate-90 scale-0 absolute"}`}>
          <path strokeLinecap="round" d="M6 9l6 6 6-6" />
        </svg>
      </button>
    </>
  );
}
