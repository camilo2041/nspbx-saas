"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "nspbx-theme";

// Se inyecta en <head> antes de pintar: evita el parpadeo blanco al entrar
// con el tema oscuro activo (FOUC).
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var mode = localStorage.getItem("${STORAGE_KEY}") || "system";
    var dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.dataset.theme = mode;
  } catch (e) {}
})();
`;

function systemPrefersDark() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyMode(mode: ThemeMode) {
  const dark = mode === "dark" || (mode === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.dataset.theme = mode;
  return dark ? "dark" : "light";
}

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
  mounted: boolean;
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: "system",
  resolved: "light",
  setMode: () => {},
  mounted: false,
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = (localStorage.getItem(STORAGE_KEY) as ThemeMode | null) ?? "system";
    // eslint-disable-next-line react-hooks/set-state-in-effect -- lee localStorage después de montar (no existe en el servidor)
    setModeState(stored);
    setResolved(applyMode(stored));
    setMounted(true);
  }, []);

  // Si el usuario deja el tema en "sistema", seguimos los cambios del SO en vivo.
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(applyMode("system"));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    setResolved(applyMode(next));
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // modo incógnito / storage bloqueado: el tema simplemente no persiste
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, mounted }}>{children}</ThemeContext.Provider>
  );
}

const SunIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" className="h-4 w-4">
    <circle cx="12" cy="12" r="4" />
    <path
      strokeLinecap="round"
      d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
    />
  </svg>
);

const MoonIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" className="h-4 w-4">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 1020.354 15.354z"
    />
  </svg>
);

const SystemIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" className="h-4 w-4">
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path strokeLinecap="round" d="M8 20h8M12 16v4" />
  </svg>
);

const OPTIONS: { value: ThemeMode; icon: ReactNode; label: string }[] = [
  { value: "light", icon: SunIcon, label: "Modo claro" },
  { value: "dark", icon: MoonIcon, label: "Modo oscuro" },
  { value: "system", icon: SystemIcon, label: "Según el sistema" },
];

/** Selector de tema de 3 posiciones con indicador deslizante. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { mode, setMode, mounted } = useTheme();
  const index = Math.max(
    0,
    OPTIONS.findIndex((o) => o.value === mode)
  );

  return (
    <div
      className={`relative inline-flex items-center rounded-full border border-line bg-surface-2 p-0.5 ${className}`}
      role="radiogroup"
      aria-label="Tema"
    >
      <span
        aria-hidden
        className="absolute top-0.5 bottom-0.5 left-0.5 w-8 rounded-full bg-surface shadow-[var(--shadow-1)] ring-1 ring-line transition-transform duration-300"
        style={{
          transform: `translateX(${index * 2}rem)`,
          opacity: mounted ? 1 : 0,
        }}
      />
      {OPTIONS.map((opt) => {
        const active = mounted && mode === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={opt.label}
            aria-label={opt.label}
            onClick={() => setMode(opt.value)}
            className={`relative z-10 flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
              active ? "text-brand" : "text-faint hover:text-fg-soft"
            }`}
          >
            {opt.icon}
          </button>
        );
      })}
    </div>
  );
}
