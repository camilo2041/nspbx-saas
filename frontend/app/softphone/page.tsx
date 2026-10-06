"use client";

import { Badge, Button, Card, CardBody, CardHeader, ErrorBanner, Note, PageHeader, Toggle } from "@/components/ui";
import { ControlesLlamada } from "@/components/controles-llamada";
import { useSoftphone, resolverServidorSip } from "@/lib/softphone-context";

const DIALPAD: { digit: string; letters?: string }[] = [
  { digit: "1" },
  { digit: "2", letters: "ABC" },
  { digit: "3", letters: "DEF" },
  { digit: "4", letters: "GHI" },
  { digit: "5", letters: "JKL" },
  { digit: "6", letters: "MNO" },
  { digit: "7", letters: "PQRS" },
  { digit: "8", letters: "TUV" },
  { digit: "9", letters: "WXYZ" },
  { digit: "*" },
  { digit: "0", letters: "+" },
  { digit: "#" },
];

export default function SoftphonePage() {
  const {
    entorno,
    loadError,
    dndCambiando,
    dndError,
    setDndError,
    connState,
    connError,
    setConnError,
    destination,
    setDestination,
    phase,
    remoteParty,
    muted,
    callSeconds,
    connect,
    disconnect,
    activarDnd,
    call,
    answer,
    reject,
    hangup,
    toggleMute,
    sendDtmf,
  } = useSoftphone();

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  const connBadge =
    connState === "registered" ? (
      <Badge color="green" dot>
        Registrado
      </Badge>
    ) : connState === "connecting" ? (
      <Badge color="amber" dot pulse>
        Conectando…
      </Badge>
    ) : connState === "error" ? (
      <Badge color="red" dot>
        Error
      </Badge>
    ) : (
      <Badge color="slate" dot>
        Desconectado
      </Badge>
    );

  // Función de render (no componente): así el teclado no se desmonta en cada
  // pulsación mientras se escribe el número.
  const renderDialpad = (compact = false) => (
    <div className="grid grid-cols-3 gap-2">
      {DIALPAD.map((k) => (
        <button
          key={k.digit}
          type="button"
          onClick={() => sendDtmf(k.digit)}
          className={`press flex flex-col items-center justify-center rounded-xl border border-line bg-surface-2 font-medium text-fg transition-all duration-150 hover:-translate-y-0.5 hover:border-brand/40 hover:bg-surface hover:shadow-[var(--shadow-2)] ${
            compact ? "py-2 text-sm" : "py-3 text-lg"
          }`}
        >
          {k.digit}
          {!compact && (
            <span className="text-[9px] font-normal tracking-widest text-faint">{k.letters ?? " "}</span>
          )}
        </button>
      ))}
    </div>
  );

  return (
    <div>
      <PageHeader
        title="Softphone"
        subtitle="Registra una extensión y haz/recibe llamadas con audio desde el navegador"
      />

      {loadError && (
        <div className="mb-4">
          <ErrorBanner message={loadError} />
        </div>
      )}
      {connError && (
        <div className="mb-4">
          <ErrorBanner message={connError} onClose={() => setConnError("")} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Conexión" subtitle="Tu extensión asignada" actions={connBadge} />
          <CardBody className="space-y-4">
            {entorno?.extension ? (
              <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-4 py-3">
                <div>
                  <div className="font-mono text-lg font-semibold text-fg">{entorno.extension.number}</div>
                  {entorno.extension.caller_id_name && (
                    <div className="text-xs text-muted">{entorno.extension.caller_id_name}</div>
                  )}
                </div>
                {!entorno.extension.enabled && <Badge color="amber">Desactivada</Badge>}
              </div>
            ) : (
              <Note tone="warn">
                Tu usuario no tiene una extensión asignada, así que no puedes registrarte para llamar.
                Pídele a un administrador que te asigne una en Usuarios.
              </Note>
            )}

            {entorno?.extension && (
              <div
                className={`flex items-center justify-between rounded-xl border px-4 py-3 transition-colors ${
                  entorno.extension.dnd ? "border-warn/25 bg-warn-soft" : "border-line bg-surface-2"
                }`}
              >
                <div>
                  <div className={`text-sm font-medium ${entorno.extension.dnd ? "text-warn-text" : "text-fg"}`}>
                    No molestar
                  </div>
                  <div className="text-[11px] text-faint">
                    {entorno.extension.dnd
                      ? "Las llamadas a tu extensión no van a timbrar."
                      : "Mismo efecto que marcar *78 desde cualquier teléfono."}
                  </div>
                </div>
                <Toggle
                  checked={entorno.extension.dnd}
                  onChange={activarDnd}
                  disabled={dndCambiando}
                />
              </div>
            )}
            {dndError && <ErrorBanner message={dndError} onClose={() => setDndError("")} />}

            <Note tone="muted">
              {/* La URL EFECTIVA, no la de Ajustes: cuando el panel corre en un
                  dominio, el softphone deduce wss://<dominio>/sip e ignora el
                  "wss://localhost:7443" que viene de fábrica. Mostrar el valor
                  crudo hacía creer que seguía intentando contra localhost. */}
              WebSocket: <span className="font-mono">{resolverServidorSip(entorno?.sip_ws_url) || "…"}</span> · Dominio:{" "}
              <span className="font-mono">{entorno?.fs_domain || "…"}</span>
            </Note>
            {connState === "registered" ? (
              <Button variant="danger" onClick={disconnect}>
                Desconectar
              </Button>
            ) : (
              <Button
                onClick={connect}
                loading={connState === "connecting"}
                disabled={!entorno?.extension?.enabled}
              >
                {connState === "connecting" ? "Conectando…" : "Conectar"}
              </Button>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Llamada" subtitle="Marca un número o extensión interna" />
          <CardBody className="space-y-4">
            {phase === "incoming" && (
              <div className="animate-pop rounded-xl border border-warn/25 bg-warn-soft p-4">
                <p className="mb-3 flex items-center gap-2 font-medium text-warn-text">
                  <span className="relative flex h-2.5 w-2.5 text-warn">
                    <span className="ping-ring absolute inset-0" />
                    <span className="relative h-2.5 w-2.5 rounded-full bg-current" />
                  </span>
                  Llamada entrante de {remoteParty}
                </p>
                <div className="flex gap-2">
                  <Button variant="success" onClick={answer}>
                    Contestar
                  </Button>
                  <Button variant="danger" onClick={reject}>
                    Rechazar
                  </Button>
                </div>
              </div>
            )}

            {phase === "outgoing" && (
              <div className="animate-pop rounded-xl border border-info/25 bg-info-soft p-4">
                <p className="mb-3 flex items-center gap-2 font-medium text-info-text">
                  <span className="relative flex h-2.5 w-2.5 text-info">
                    <span className="ping-ring absolute inset-0" />
                    <span className="relative h-2.5 w-2.5 rounded-full bg-current" />
                  </span>
                  Llamando a {remoteParty}… (puede tardar unos segundos en sonar)
                </p>
                <Button variant="danger" onClick={hangup}>
                  Colgar
                </Button>
              </div>
            )}

            {phase === "in-call" && (
              <div className="animate-pop rounded-xl border border-ok/25 bg-ok-soft p-4">
                <p className="mb-3 font-medium text-ok-text">
                  En llamada con {remoteParty} ·{" "}
                  <span className="tabular-nums">{fmt(callSeconds)}</span>
                </p>
                <div className="flex gap-2">
                  <Button variant="danger" onClick={hangup}>
                    Colgar
                  </Button>
                  <Button variant="secondary" onClick={toggleMute}>
                    {muted ? "Reactivar mic" : "Silenciar"}
                  </Button>
                </div>
                <ControlesLlamada />
              </div>
            )}

            {(phase === "idle" || phase === "ended") && (
              <>
                <div className="relative">
                  <input
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="Ej. 1002 o 5551234567"
                    className="w-full rounded-xl border border-line bg-surface-2 px-10 py-3 text-center font-mono text-xl tracking-wider text-fg outline-none transition-all placeholder:text-sm placeholder:tracking-normal placeholder:text-faint focus:border-brand focus:bg-surface focus:ring-4 focus:ring-brand/15"
                  />
                  {destination && (
                    <button
                      type="button"
                      onClick={() => setDestination(destination.slice(0, -1))}
                      aria-label="Borrar último dígito"
                      className="press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-faint hover:bg-surface-3 hover:text-fg"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M21 5H9l-6 7 6 7h12a1 1 0 001-1V6a1 1 0 00-1-1zM17 9l-5 6M12 9l5 6"
                        />
                      </svg>
                    </button>
                  )}
                </div>
                {renderDialpad()}
                <Button
                  variant="success"
                  onClick={call}
                  disabled={connState !== "registered" || !destination}
                  className="w-full justify-center py-2.5"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
                    />
                  </svg>
                  Llamar
                </Button>
              </>
            )}

            {phase === "in-call" && (
              <div className="border-t border-line pt-4">
                <div className="mb-2 text-xs text-muted">Enviar tonos (DTMF)</div>
                {renderDialpad(true)}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
