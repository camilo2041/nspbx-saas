"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";
import { Guia, guiaPorId, NOMBRE_PANTALLA, PasoGuia } from "@/lib/guias";

const KEY = "nspbx-guia";
const ANCHO = 300;
const MARGEN = 12;

interface Estado {
  id: string;
  paso: number;
}

const enRuta = (pathname: string, ruta: string) => pathname === ruta || pathname.startsWith(`${ruta}/`);

const selector = (marca: string) => `[data-guia="${typeof CSS !== "undefined" ? CSS.escape(marca) : marca}"]`;

/** El primero visible con esa marca (hay marcas repetidas, una por fila). */
function buscar(marca: string): HTMLElement | null {
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector(marca)))) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}

/**
 * Guía en pantalla: señala con un recuadro el botón o campo de cada paso y
 * explica qué hacer en una tarjeta pequeña. No oscurece ni bloquea el panel:
 * todo sigue funcionando y la persona hace los cambios ella misma. Sobrevive a
 * cambiar de pantalla (sessionStorage) y se arranca con iniciarGuia(id).
 */
export function GuiaEnPantalla() {
  const { usuario } = useAuth();
  const pathname = usePathname();
  if (!usuario || pathname === "/login" || pathname === "/webcall") return null;
  return <Recorrido pathname={pathname} />;
}

function Recorrido({ pathname }: { pathname: string }) {
  const router = useRouter();
  const [estado, setEstado] = useState<Estado | null>(() => {
    try {
      const g = sessionStorage.getItem(KEY);
      return g ? (JSON.parse(g) as Estado) : null;
    } catch {
      return null;
    }
  });
  // Medidas atadas a la marca que se midió: al cambiar de paso, lo viejo no cuenta.
  const [medida, setMedida] = useState<{ marca: string; rect: DOMRect | null; perdido: boolean } | null>(null);
  const [oculta, setOculta] = useState(false);
  const tarjeta = useRef<HTMLDivElement>(null);
  const [altoTarjeta, setAltoTarjeta] = useState(170);

  const guia: Guia | undefined = estado ? guiaPorId(estado.id) : undefined;
  const terminada = !!guia && !!estado && estado.paso >= guia.pasos.length;
  const paso: PasoGuia | undefined = guia && estado && !terminada ? guia.pasos[estado.paso] : undefined;
  // En otra pantalla, el paso real espera: primero se señala la entrada del menú.
  const fuera = !!paso && !enRuta(pathname, paso.ruta);
  const marca = paso ? (fuera ? `menu:${paso.ruta}` : paso.marca) : undefined;
  const rect = medida && medida.marca === marca ? medida.rect : null;
  const perdido = !!medida && medida.marca === marca && medida.perdido;

  const guardar = useCallback((e: Estado | null) => {
    setEstado(e);
    setOculta(false);
    try {
      if (e) sessionStorage.setItem(KEY, JSON.stringify(e));
      else sessionStorage.removeItem(KEY);
    } catch {
      /* sin persistencia */
    }
  }, []);

  const ir = useCallback(
    (delta: number) => setEstado((e) => {
      if (!e) return e;
      const nuevo = { ...e, paso: Math.max(0, e.paso + delta) };
      try {
        sessionStorage.setItem(KEY, JSON.stringify(nuevo));
      } catch {
        /* sin persistencia */
      }
      return nuevo;
    }),
    []
  );

  // Arranque desde el asistente o cualquier pantalla.
  useEffect(() => {
    const onGuia = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (typeof id === "string" && guiaPorId(id)) guardar({ id, paso: 0 });
    };
    window.addEventListener("nspbx:guia", onGuia);
    return () => window.removeEventListener("nspbx:guia", onGuia);
  }, [guardar]);

  // Seguir al elemento: aparece tarde (modales, datos que cargan) y se mueve con el scroll.
  useEffect(() => {
    if (!marca) return;
    let desplazado = false;
    const inicio = Date.now();
    const medir = () => {
      const el = buscar(marca);
      if (!el) {
        setMedida({ marca, rect: null, perdido: Date.now() - inicio > 1500 });
        return;
      }
      const r = el.getBoundingClientRect();
      if (!desplazado) {
        desplazado = true;
        if (r.top < 60 || r.bottom > window.innerHeight - 60) el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      setMedida((prev) => {
        const p = prev?.marca === marca ? prev.rect : null;
        if (p && p.top === r.top && p.left === r.left && p.width === r.width && p.height === r.height) return prev;
        return { marca, rect: r, perdido: false };
      });
    };
    const primero = requestAnimationFrame(medir);
    const t = setInterval(medir, 250);
    window.addEventListener("scroll", medir, true);
    window.addEventListener("resize", medir);
    return () => {
      cancelAnimationFrame(primero);
      clearInterval(t);
      window.removeEventListener("scroll", medir, true);
      window.removeEventListener("resize", medir);
    };
  }, [marca]);

  // Pulsar lo señalado avanza solo (sin bloquear el clic: el botón hace lo suyo).
  useEffect(() => {
    if (!paso?.marca || fuera || !paso.alPulsar) return;
    const sel = selector(paso.marca);
    const onClick = (e: MouseEvent) => {
      if ((e.target as Element | null)?.closest?.(sel)) setTimeout(() => ir(1), 60);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [paso, fuera, ir]);

  // Al terminar, la tarjeta de «Listo» se va sola.
  useEffect(() => {
    if (!terminada) return;
    const t = setTimeout(() => guardar(null), 5000);
    return () => clearTimeout(t);
  }, [terminada, guardar]);

  useLayoutEffect(() => {
    if (tarjeta.current) setAltoTarjeta(tarjeta.current.offsetHeight);
  }, [estado, marca, perdido, oculta]);

  if (!guia || !estado) return null;

  const total = guia.pasos.length;
  const nombrePantalla = paso ? NOMBRE_PANTALLA[paso.ruta] ?? paso.ruta : "";

  // Tarjeta junto al elemento, tapando lo menos posible: a un lado si cabe (así
  // no cubre los campos de abajo), si no debajo o arriba; sin elemento, abajo a la izquierda.
  let pos: React.CSSProperties = { left: 20, bottom: 20 };
  if (rect && !oculta && typeof window !== "undefined") {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const ancho = Math.min(ANCHO, vw - 2 * MARGEN);
    const top = Math.min(Math.max(MARGEN, rect.top), vh - altoTarjeta - MARGEN);
    const left = Math.min(Math.max(MARGEN, rect.left), vw - ancho - MARGEN);
    if (rect.right + 2 * MARGEN + ancho < vw) pos = { left: rect.right + MARGEN + 4, top };
    else if (rect.left - 2 * MARGEN - ancho > 0) pos = { left: rect.left - MARGEN - 4 - ancho, top };
    else if (rect.bottom + MARGEN + altoTarjeta < vh) pos = { left, top: rect.bottom + MARGEN };
    else if (rect.top - MARGEN - altoTarjeta > 0) pos = { left, top: rect.top - MARGEN - altoTarjeta };
    else pos = { left: MARGEN, bottom: MARGEN };
  }

  const boton =
    "press rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-40";

  return (
    <>
      {rect && !oculta && (
        <div
          aria-hidden
          className="pointer-events-none fixed z-[95] rounded-xl border-2 border-brand transition-all duration-200"
          style={{
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            boxShadow: "0 0 0 4px color-mix(in srgb, var(--brand) 25%, transparent)",
          }}
        >
          <span className="absolute -right-1.5 -top-1.5 h-3 w-3 animate-ping rounded-full bg-brand" />
        </div>
      )}

      {oculta ? (
        <button
          type="button"
          onClick={() => setOculta(false)}
          className="press fixed bottom-5 left-5 z-[95] rounded-full border border-line bg-surface px-3.5 py-2 text-[12px] font-medium text-brand-text shadow-[var(--shadow-2)]"
        >
          Guía: paso {Math.min(estado.paso + 1, total)} de {total} ▸
        </button>
      ) : (
        <div
          ref={tarjeta}
          role="dialog"
          aria-label={`Guía: ${guia.titulo}`}
          className="animate-pop fixed z-[95] rounded-2xl border border-line bg-surface p-3.5 text-[13px] shadow-[var(--shadow-3)]"
          style={{ ...pos, width: Math.min(ANCHO, typeof window !== "undefined" ? window.innerWidth - 2 * MARGEN : ANCHO) }}
        >
          <div className="mb-1 flex items-center gap-2">
            <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted">{guia.titulo}</span>
            <button
              type="button"
              onClick={() => setOculta(true)}
              title="Ocultar (la guía sigue)"
              aria-label="Ocultar guía"
              className="press ml-auto rounded p-0.5 text-faint hover:text-fg"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                <path strokeLinecap="round" d="M6 12h12" />
              </svg>
            </button>
            <button type="button" onClick={() => guardar(null)} aria-label="Salir de la guía" className="press rounded p-0.5 text-faint hover:text-fg">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          {terminada ? (
            <>
              <p className="font-semibold text-fg">¡Listo! ✓</p>
              <p className="mt-1 text-fg-soft">Terminaste la guía. Si algo no salió, pregúntale al asistente.</p>
            </>
          ) : fuera ? (
            <>
              <p className="font-semibold text-fg">Entra a «{nombrePantalla}»</p>
              <p className="mt-1 text-fg-soft">
                {rect ? "Está señalado en el menú." : "Búscalo en el menú (puede estar en el modo avanzado) o déjame llevarte."}
              </p>
            </>
          ) : (
            <>
              <p className="font-semibold text-fg">{paso?.titulo}</p>
              <p className="mt-1 leading-relaxed text-fg-soft">{paso?.texto}</p>
              {paso?.marca && perdido && (
                <p className="mt-2 rounded-lg bg-surface-2 px-2.5 py-1.5 text-[12px] text-muted">
                  No veo ese botón ahora. Puede estar dentro de una ventana que se cerró, más abajo en la página, o tu rol no lo tiene.
                </p>
              )}
            </>
          )}

          <div className="mt-3 flex items-center gap-1.5">
            <span className="text-[11px] tabular-nums text-faint">
              {Math.min(estado.paso + 1, total)} / {total}
            </span>
            <div className="ml-auto flex gap-1.5">
              {estado.paso > 0 && !terminada && (
                <button type="button" onClick={() => ir(-1)} className={`${boton} text-fg-soft hover:bg-surface-2`}>
                  Atrás
                </button>
              )}
              {fuera && paso ? (
                <button type="button" onClick={() => router.push(paso.ruta)} className={`${boton} bg-brand text-on-brand`}>
                  Llévame →
                </button>
              ) : terminada ? (
                <button type="button" onClick={() => guardar(null)} className={`${boton} bg-brand text-on-brand`}>
                  Cerrar
                </button>
              ) : (
                <button type="button" onClick={() => ir(1)} className={`${boton} bg-brand text-on-brand`}>
                  {estado.paso === total - 1 ? "Terminar" : paso?.alPulsar && rect ? "Ya lo hice" : "Siguiente"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
