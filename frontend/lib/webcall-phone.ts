"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Inviter,
  Registerer,
  RegistererState,
  Session,
  SessionState,
  UserAgent,
  type UserAgentOptions,
} from "sip.js";

import { API_URL } from "@/lib/api";
import { Ringer } from "@/lib/ringer";

/**
 * Base de la API. Si la página /webcall va embebida por webcall.js con un
 * `?api=` (panel y backend en orígenes distintos, típico en desarrollo
 * local), se respeta; si no, la resolución normal de lib/api.
 */
function apiBase(): string {
  if (typeof window !== "undefined") {
    const q = new URLSearchParams(window.location.search).get("api");
    if (q) return q.replace(/\/+$/, "");
  }
  return API_URL;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Error ${res.status}`;
    throw new Error(detail);
  }
  return data as T;
}

/**
 * Cliente SIP mínimo para el widget de llamada web (página /webcall).
 *
 * No reutiliza SoftphoneProvider a propósito: ese está acoplado a la
 * sesión del panel (useAuth, /api/auth/mi-entorno, permisos, DND). Acá el
 * visitante es anónimo: pide una credencial temporal a
 * POST /api/webcall/session y con ella se registra y hace un INVITE
 * automático al destino fijo `webqueue`, que el contexto de dialplan
 * `webcall` mapea a la cola configurada.
 */

export type WebcallPhase =
  | "idle"
  | "connecting" // pidiendo credencial + registrando
  | "queued" // en la cola, esperando agente (suena la música de espera)
  | "in-call"
  | "ended"
  | "error";

interface SdhLike {
  peerConnection?: RTCPeerConnection;
}

interface WebcallSession {
  username: string;
  password: string;
  domain: string;
  sip_ws_url: string;
  ice_servers: { urls: string[]; username?: string; credential?: string }[];
  target: string;
  expires_in: number;
}

function resolverServidorSip(configurado: string | null | undefined): string {
  const v = (configurado ?? "").trim();
  const esLocal = v === "" || /^wss?:\/\/(localhost|127\.0\.0\.1)/i.test(v);
  if (esLocal && typeof window !== "undefined" && window.location.protocol === "https:") {
    return `wss://${window.location.host}/sip`;
  }
  return v;
}

export function useWebcallPhone() {
  const [phase, setPhase] = useState<WebcallPhase>("idle");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);

  const uaRef = useRef<UserAgent | null>(null);
  const registererRef = useRef<Registerer | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const usernameRef = useRef<string>("");
  const capTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Se crea una sola vez, solo en el navegador.
  const [ringer] = useState<Ringer | null>(() => (typeof window !== "undefined" ? new Ringer() : null));

  const attachRemoteAudio = useCallback((session: Session) => {
    const pc = (session.sessionDescriptionHandler as unknown as SdhLike | undefined)?.peerConnection;
    if (!pc || !audioRef.current) return;
    const stream = new MediaStream();
    pc.getReceivers().forEach((r) => r.track && stream.addTrack(r.track));
    audioRef.current.srcObject = stream;
    audioRef.current.play().catch(() => {});
  }, []);

  const cleanup = useCallback(async () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    if (capTimerRef.current) clearTimeout(capTimerRef.current);
    capTimerRef.current = null;
    ringer?.stop();
    ringer?.ringbackOff();
    try {
      if (registererRef.current) await registererRef.current.unregister();
    } catch {
      /* noop */
    }
    try {
      if (uaRef.current) await uaRef.current.stop();
    } catch {
      /* noop */
    }
    uaRef.current = null;
    registererRef.current = null;
    sessionRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
    const u = usernameRef.current;
    usernameRef.current = "";
    if (u) {
      // Libera el cupo global enseguida; el backend tiene un barrido de
      // respaldo por si esto no llega.
      apiPost(`/api/webcall/session/${u}/end`, {}).catch(() => {});
    }
  }, [ringer]);

  const hangup = useCallback(async () => {
    const s = sessionRef.current;
    try {
      if (s && s.state === SessionState.Established) await s.bye();
      else if (s instanceof Inviter) await s.cancel();
    } catch {
      /* noop */
    }
    setPhase((p) => (p === "in-call" || p === "queued" || p === "connecting" ? "ended" : p));
    await cleanup();
  }, [cleanup]);

  const bindSession = useCallback(
    (session: Session) => {
      sessionRef.current = session;
      ringer?.ringbackOn();
      setPhase("queued");

      const attach = () => {
        if (sessionRef.current !== session) return;
        const pc = (session.sessionDescriptionHandler as unknown as SdhLike | undefined)?.peerConnection;
        if (pc) {
          pc.addEventListener("track", () => attachRemoteAudio(session));
          attachRemoteAudio(session);
        } else if (session.state !== SessionState.Terminated) {
          setTimeout(attach, 150);
        }
      };
      attach();

      session.stateChange.addListener((state) => {
        if (state === SessionState.Established) {
          ringer?.ringbackOff();
          setPhase("in-call");
          attachRemoteAudio(session);
          setSeconds(0);
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
        } else if (state === SessionState.Terminated) {
          setPhase((p) => (p === "error" ? p : "ended"));
          cleanup();
        }
      });
    },
    [attachRemoteAudio, cleanup, ringer]
  );

  const start = useCallback(
    async (turnstileToken?: string) => {
      if (phase === "connecting" || phase === "queued" || phase === "in-call") return;
      setError("");
      setPhase("connecting");
      ringer?.unlock();

      let ses: WebcallSession;
      try {
        ses = await apiPost<WebcallSession>("/api/webcall/session", {
          turnstile_token: turnstileToken ?? null,
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo iniciar la llamada");
        setPhase("error");
        return;
      }

      usernameRef.current = ses.username;
      // Corta sola al llegar al tope duro de sesión del backend.
      capTimerRef.current = setTimeout(() => hangup(), Math.max(30, ses.expires_in) * 1000);

      try {
        const uri = UserAgent.makeURI(`sip:${ses.username}@${ses.domain}`);
        if (!uri) throw new Error("Datos SIP inválidos");
        const options: UserAgentOptions = {
          uri,
          // Ver el mismo ajuste en softphone-context.tsx: sin keepalive,
          // Cloudflare cierra el WebSocket ocioso a los ~126 s.
          transportOptions: {
            server: resolverServidorSip(ses.sip_ws_url),
            keepAliveInterval: 30,
          },
          authorizationUsername: ses.username,
          authorizationPassword: ses.password,
          displayName: "Llamada web",
          logLevel: "error",
          sessionDescriptionHandlerFactoryOptions: {
            iceGatheringTimeout: 1500,
            peerConnectionConfiguration: {
              iceServers: ses.ice_servers?.length
                ? ses.ice_servers
                : [{ urls: ["stun:stun.l.google.com:19302"] }],
            },
          },
        };
        const ua = new UserAgent(options);
        uaRef.current = ua;
        await ua.start();

        const registerer = new Registerer(ua);
        registererRef.current = registerer;
        registerer.stateChange.addListener((state) => {
          if (state === RegistererState.Registered && !sessionRef.current) {
            const target = UserAgent.makeURI(`sip:${ses.target}@${ses.domain}`);
            if (!target) return;
            const inviter = new Inviter(ua, target, {
              sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } },
            });
            bindSession(inviter);
            inviter.invite().catch((err) => {
              setError(err instanceof Error ? err.message : "No se pudo conectar la llamada");
              setPhase("error");
              cleanup();
            });
          }
        });
        await registerer.register();
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo conectar con la central");
        setPhase("error");
        await cleanup();
      }
    },
    [phase, bindSession, cleanup, hangup, ringer]
  );

  const toggleMute = useCallback(() => {
    const pc = (sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined)?.peerConnection;
    if (!pc) return;
    setMuted((prev) => {
      const next = !prev;
      pc.getSenders().forEach((s) => s.track && (s.track.enabled = !next));
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setPhase("idle");
    setError("");
    setMuted(false);
    setSeconds(0);
  }, []);

  // Colgar si el visitante cierra la pestaña a media llamada.
  useEffect(() => {
    const onUnload = () => {
      const u = usernameRef.current;
      if (u && navigator.sendBeacon) {
        navigator.sendBeacon(`${apiBase()}/api/webcall/session/${u}/end`, new Blob([], { type: "text/plain" }));
      }
    };
    window.addEventListener("pagehide", onUnload);
    return () => {
      window.removeEventListener("pagehide", onUnload);
      cleanup();
    };
  }, [cleanup]);

  return { phase, error, muted, seconds, audioRef, start, hangup, toggleMute, reset };
}
