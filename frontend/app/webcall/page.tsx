"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { API_URL } from "@/lib/api";
import { useWebcallPhone } from "@/lib/webcall-phone";

// Respeta un ?api= inyectado por webcall.js cuando el panel y el backend
// están en orígenes distintos (desarrollo local: :3005 y :8001).
function apiBase(): string {
  if (typeof window !== "undefined") {
    const q = new URLSearchParams(window.location.search).get("api");
    if (q) return q.replace(/\/+$/, "");
  }
  return API_URL;
}

interface WebcallConfig {
  enabled: boolean;
  open?: boolean;
  site_key?: string;
  greeting?: string;
  button_text?: string;
  offline_text?: string;
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// El widget vive en un iframe embebido en sitios de terceros; le avisa al
// contenedor los cambios de estado para que la burbuja reaccione (y el
// botón "cerrar" pida que lo oculten).
function postToParent(msg: Record<string, unknown>) {
  try {
    window.parent?.postMessage({ source: "nspbx-webcall", ...msg }, "*");
  } catch {
    /* noop */
  }
}

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string;
      reset: (id?: string) => void;
    };
  }
}

const PhoneIcon = ({ className = "h-6 w-6" }: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
    />
  </svg>
);

export default function WebcallPage() {
  const [config, setConfig] = useState<WebcallConfig | null>(null);
  const [loadError, setLoadError] = useState("");
  const [token, setToken] = useState("");
  const turnstileBox = useRef<HTMLDivElement | null>(null);
  const turnstileId = useRef<string | null>(null);

  const { phase, error, muted, seconds, audioRef, start, hangup, toggleMute, reset } = useWebcallPhone();

  useEffect(() => {
    fetch(`${apiBase()}/api/webcall/config`)
      .then((r) => r.json())
      .then(setConfig)
      .catch((e) => setLoadError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, []);

  useEffect(() => {
    postToParent({ phase });
  }, [phase]);

  // Turnstile: se carga el script y se renderiza el widget cuando hay
  // site key. El token se guarda para mandarlo en /api/webcall/session.
  useEffect(() => {
    const key = config?.site_key;
    if (!key || !turnstileBox.current) return;
    const render = () => {
      if (!window.turnstile || !turnstileBox.current || turnstileId.current) return;
      turnstileId.current = window.turnstile.render(turnstileBox.current, {
        sitekey: key,
        callback: (t: string) => setToken(t),
        "expired-callback": () => setToken(""),
        "error-callback": () => setToken(""),
      });
    };
    if (window.turnstile) {
      render();
      return;
    }
    const existing = document.getElementById("cf-turnstile-script");
    if (!existing) {
      const s = document.createElement("script");
      s.id = "cf-turnstile-script";
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
      s.async = true;
      s.onload = render;
      document.head.appendChild(s);
    } else {
      existing.addEventListener("load", render);
    }
  }, [config?.site_key]);

  const needsToken = !!config?.site_key;
  const canCall = phase === "idle" && (!needsToken || !!token);

  const onCall = useCallback(() => {
    start(token || undefined);
    if (turnstileId.current) window.turnstile?.reset(turnstileId.current);
    setToken("");
  }, [start, token]);

  const close = () => postToParent({ action: "close" });

  let body: ReactNode;

  if (loadError) {
    body = <p className="text-sm text-muted">{loadError}</p>;
  } else if (!config) {
    body = <p className="text-sm text-muted">Cargando…</p>;
  } else if (!config.enabled) {
    body = <p className="text-sm text-muted">El botón de llamada no está disponible.</p>;
  } else if (config.open === false && (phase === "idle" || phase === "error")) {
    body = (
      <p className="text-center text-sm text-muted">
        {config.offline_text || "Estamos fuera de horario de atención."}
      </p>
    );
  } else if (phase === "idle") {
    body = (
      <div className="flex flex-col items-center gap-4">
        <p className="text-center text-sm text-fg">{config.greeting || "Presione para hablar con un agente"}</p>
        {needsToken && <div ref={turnstileBox} className="min-h-[65px]" />}
        <button
          type="button"
          onClick={onCall}
          disabled={!canCall}
          className="flex items-center gap-2 rounded-full bg-brand px-6 py-3 text-sm font-semibold text-on-brand shadow-2 transition-transform hover:brightness-110 active:scale-95 disabled:opacity-50"
        >
          <PhoneIcon className="h-5 w-5" />
          {config.button_text || "Hablar con un agente"}
        </button>
      </div>
    );
  } else if (phase === "connecting") {
    body = <p className="text-sm text-muted">Conectando…</p>;
  } else if (phase === "queued") {
    body = (
      <div className="flex flex-col items-center gap-4">
        <span className="relative flex h-3 w-3">
          <span className="ping-ring absolute inset-0 rounded-full bg-info" />
          <span className="relative h-3 w-3 rounded-full bg-info" />
        </span>
        <p className="text-sm text-fg">Esperando a un agente…</p>
        <button
          type="button"
          onClick={hangup}
          className="rounded-full bg-danger px-5 py-2.5 text-sm font-semibold text-white active:scale-95"
        >
          Cancelar
        </button>
      </div>
    );
  } else if (phase === "in-call") {
    body = (
      <div className="flex flex-col items-center gap-4">
        <p className="text-sm font-semibold text-ok-text">En llamada</p>
        <p className="text-2xl font-semibold tabular-nums text-fg">{fmt(seconds)}</p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggleMute}
            className={`rounded-full border px-4 py-2 text-sm ${
              muted ? "border-warn/40 bg-warn-soft text-warn-text" : "border-line bg-surface-2 text-muted"
            }`}
          >
            {muted ? "Reactivar micrófono" : "Silenciar"}
          </button>
          <button
            type="button"
            onClick={hangup}
            className="rounded-full bg-danger px-5 py-2 text-sm font-semibold text-white active:scale-95"
          >
            Colgar
          </button>
        </div>
      </div>
    );
  } else if (phase === "error") {
    body = (
      <div className="flex flex-col items-center gap-3">
        <p className="text-center text-sm text-danger">{error || "No se pudo completar la llamada."}</p>
        <button type="button" onClick={reset} className="text-sm font-semibold text-brand">
          Reintentar
        </button>
      </div>
    );
  } else {
    // ended
    body = (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm text-fg">Llamada finalizada.</p>
        <button type="button" onClick={reset} className="text-sm font-semibold text-brand">
          Llamar de nuevo
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="relative w-full max-w-sm rounded-3xl border border-line bg-surface p-8 shadow-3">
        <button
          type="button"
          onClick={close}
          aria-label="Cerrar"
          className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        <div className="flex flex-col items-center gap-2 pb-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand">
            <PhoneIcon />
          </div>
        </div>
        <div className="flex min-h-[160px] items-center justify-center">{body}</div>
      </div>
      <audio ref={audioRef} autoPlay className="hidden" />
    </div>
  );
}
