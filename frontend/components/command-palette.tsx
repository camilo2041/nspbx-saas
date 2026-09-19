"use client";

import { useRouter } from "next/navigation";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

export interface Comando {
  href: string;
  label: string;
  grupo: string;
  icon: ReactNode;
}

const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/**
 * Paleta de comandos (Ctrl/Cmd+K): saltar a cualquier pantalla escribiendo
 * unas letras, con flechas y Enter. Solo recibe las pantallas que el rol ya
 * puede abrir (las filtra el marco), así que no ofrece nada sin acceso.
 */
export function CommandPalette({ comandos }: { comandos: Comando[] }) {
  const router = useRouter();
  const [abierto, setAbierto] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const lista = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setAbierto((a) => !a);
        setQ("");
        setSel(0);
      } else if (e.key === "Escape") setAbierto(false);
    };
    const abrir = () => {
      setAbierto(true);
      setQ("");
      setSel(0);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("nspbx:paleta", abrir);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("nspbx:paleta", abrir);
    };
  }, []);

  const filtrados = useMemo(() => {
    const t = norm(q.trim());
    if (!t) return comandos;
    return comandos.filter((c) => norm(`${c.label} ${c.grupo}`).includes(t));
  }, [q, comandos]);

  useEffect(() => {
    lista.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!abierto) return null;

  const ir = (c: Comando) => {
    setAbierto(false);
    router.push(c.href);
  };

  return (
    <div className="fixed inset-0 z-[95] flex items-start justify-center px-4 pt-[14vh]" role="dialog" aria-label="Buscar pantalla">
      <div className="animate-fade-soft absolute inset-0 bg-slate-950/50 backdrop-blur-sm" onClick={() => setAbierto(false)} />
      <div className="animate-pop glass relative w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-surface/95 shadow-[var(--shadow-3)]">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 text-faint">
            <circle cx="11" cy="11" r="7" />
            <path strokeLinecap="round" d="M20 20l-3.5-3.5" />
          </svg>
          <input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setSel(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(s + 1, filtrados.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(s - 1, 0));
              } else if (e.key === "Enter" && filtrados[sel]) {
                e.preventDefault();
                ir(filtrados[sel]);
              }
            }}
            placeholder="Ir a… (llamadas, extensiones, ajustes)"
            className="h-12 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-faint"
          />
          <kbd className="rounded-md border border-line px-1.5 py-0.5 text-[10px] text-faint">Esc</kbd>
        </div>
        <div ref={lista} className="no-scrollbar max-h-72 overflow-y-auto p-2">
          {filtrados.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted">Sin resultados</div>}
          {filtrados.map((c, i) => (
            <button
              key={c.href}
              data-i={i}
              type="button"
              onMouseMove={() => setSel(i)}
              onClick={() => ir(c)}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[13px] transition-colors ${
                i === sel ? "bg-brand-soft text-brand-text" : "text-fg-soft"
              }`}
            >
              <span className={i === sel ? "text-brand" : "text-faint"}>{c.icon}</span>
              <span className="flex-1 font-medium">{c.label}</span>
              <span className="text-[11px] text-faint">{c.grupo}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-faint">
          <span>↑↓ navegar</span>
          <span>↵ abrir</span>
          <span className="ml-auto">Ctrl+J asistente</span>
        </div>
      </div>
    </div>
  );
}
