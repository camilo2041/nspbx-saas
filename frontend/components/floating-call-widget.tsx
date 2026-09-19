"use client";

import { usePathname } from "next/navigation";

import { useSoftphone } from "@/lib/softphone-context";

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/**
 * Igual que el banner de llamada entrante, pero para cuando ya se está en
 * una llamada (o marcando): un widget chiquito, siempre visible, para
 * colgar o ver cuánto lleva sin tener que volver a /softphone. Ahí mismo
 * ya está la tarjeta completa, así que se oculta en esa página para no
 * duplicar la misma información dos veces en la misma pantalla.
 */
export function FloatingCallWidget() {
  const pathname = usePathname();
  const { phase, remoteParty, callSeconds, muted, hangup, toggleMute } = useSoftphone();

  if (pathname.startsWith("/softphone")) return null;
  if (phase !== "outgoing" && phase !== "in-call") return null;

  const enLlamada = phase === "in-call";

  return (
    <div className="fixed bottom-24 right-5 z-[100]">
      <div
        className={`animate-pop flex items-center gap-3 rounded-2xl border-2 bg-surface py-2.5 pl-4 pr-2.5 shadow-[var(--shadow-3)] ${
          enLlamada ? "border-ok" : "border-info"
        }`}
      >
        <span className={`relative flex h-2.5 w-2.5 shrink-0 ${enLlamada ? "text-ok" : "text-info"}`}>
          <span className="ping-ring absolute inset-0" />
          <span className="relative h-2.5 w-2.5 rounded-full bg-current" />
        </span>

        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-fg">{remoteParty}</div>
          <div className={`text-[11px] tabular-nums ${enLlamada ? "text-ok-text" : "text-info-text"}`}>
            {enLlamada ? fmt(callSeconds) : "Llamando…"}
          </div>
        </div>

        {enLlamada && (
          <button
            type="button"
            onClick={toggleMute}
            title={muted ? "Reactivar micrófono" : "Silenciar"}
            aria-label={muted ? "Reactivar micrófono" : "Silenciar"}
            className={`press flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition-colors ${
              muted
                ? "border-warn/30 bg-warn-soft text-warn-text"
                : "border-line bg-surface-2 text-muted hover:bg-surface-3 hover:text-fg"
            }`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
              {muted ? (
                <>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M1 1l22 22" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 9v3a3 3 0 004.7 2.5M15 9.34V5a3 3 0 00-5.94-.6" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17 16.95A7 7 0 015 12M19 12a7 7 0 01-.11 1.23M12 19v3M8 22h8" />
                </>
              ) : (
                <>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 10v2a7 7 0 01-14 0v-2M12 19v3M8 22h8" />
                </>
              )}
            </svg>
          </button>
        )}

        <button
          type="button"
          onClick={hangup}
          title="Colgar"
          aria-label="Colgar"
          className="press flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-danger text-white transition-transform hover:brightness-110 active:scale-95"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4 rotate-[135deg]">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}
