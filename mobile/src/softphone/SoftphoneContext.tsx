import {
  addCallAnsweredListener,
  addCallEndedListener,
  addCallSessionAddedListener,
  addDTMFListener,
  addOutgoingCallStartedListener,
  addSetMutedActionListener,
  answerCall,
  endCall,
  fulfillIncomingCallConnected,
  failIncomingCallConnected,
  prepareAudioSessionForCall,
  registerVoIPPush,
  reportCallEnded,
  reportIncomingCall,
  reportOutgoingCallConnected,
  setMuted as setMutedNativo,
  startOutgoingCall,
  useVoIPPushToken,
  type CallSession,
} from "expo-callkit-telecom";
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Inviter,
  Invitation,
  Registerer,
  RegistererState,
  Session,
  SessionState,
  UserAgent,
  type UserAgentOptions,
} from "sip.js";

import { peticion } from "@/src/api/client";
import type { MiEntorno } from "@/src/api/types";
import { useAuth } from "@/src/auth/AuthContext";
import { instalarPolyfillWebRTC } from "@/src/softphone/webrtcPolyfill";

instalarPolyfillWebRTC();

export type ConnState = "disconnected" | "connecting" | "registered" | "error";
export type CallPhase = "idle" | "outgoing" | "incoming" | "in-call" | "ended";

interface SdhLike {
  peerConnection?: RTCPeerConnection;
  sendDtmf?: (tone: string) => boolean;
}

interface SoftphoneCtx {
  entorno: MiEntorno | null;
  connState: ConnState;
  connError: string;
  phase: CallPhase;
  destination: string;
  remoteParty: string;
  muted: boolean;
  callSeconds: number;
  setDestination: (v: string) => void;
  connect: () => Promise<void>;
  call: () => Promise<void>;
  hangup: () => Promise<void>;
  toggleMute: () => void;
  sendDtmf: (digit: string) => void;
  activarDnd: (activar: boolean) => Promise<void>;
}

const Ctx = createContext<SoftphoneCtx | null>(null);

export function useSoftphone(): SoftphoneCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSoftphone debe usarse dentro de <SoftphoneProvider>");
  return ctx;
}

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const { usuario, puede } = useAuth();

  const [entorno, setEntorno] = useState<MiEntorno | null>(null);
  const [connState, setConnState] = useState<ConnState>("disconnected");
  const [connError, setConnError] = useState("");
  const [destination, setDestination] = useState("");
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [remoteParty, setRemoteParty] = useState("");
  const [muted, setMuted] = useState(false);
  const [callSeconds, setCallSeconds] = useState(0);

  const userAgentRef = useRef<UserAgent | null>(null);
  const registererRef = useRef<Registerer | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const intentionalUnregisterRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generacionRef = useRef(0);

  // Puente entre el mundo de expo-callkit-telecom (ids de sesión del SO,
  // CallKit/Telecom) y el de sip.js (la sesión SIP de verdad). Una sola
  // llamada pendiente a la vez a propósito: esto es el teléfono de UNA
  // extensión personal, no una central — simplifica bastante la
  // correlación entre "el push que despertó la UI nativa" y "el INVITE
  // que le sigue por SIP" sin necesitar un identificador compartido
  // entre FreeSWITCH y el SO (que no existe: CallKit/Telecom generan su
  // propio id, ajeno al que usa el SIP INVITE).
  const idNativoRef = useRef<string | null>(null);
  const requestIdRef = useRef<string | null>(null);
  const destinoSalienteRef = useRef<{ id: string; destino: string } | null>(null);

  const voip = useVoIPPushToken();

  // Registro de push VoIP: una vez al montar. El token en sí se manda al
  // backend más abajo, apenas aparece (o cambia).
  useEffect(() => {
    // En Android esto falla si el proyecto no tiene google-services.json
    // (Firebase sin configurar, ver SETUP.md). Sin el try/catch, esa
    // excepción nativa cerraba la app al abrirla; así la app funciona
    // igual, solo sin push en segundo plano.
    try {
      registerVoIPPush();
    } catch (e) {
      console.warn("Push de voz no disponible:", e);
    }
  }, []);

  useEffect(() => {
    if (!voip || !usuario) return;
    const platform = voip.type === "APNS_VOIP" ? "ios" : "android";
    peticion("/api/auth/dispositivo", {
      method: "POST",
      body: { platform, token_type: voip.type, token: voip.token },
    }).catch(() => {
      // Best-effort: si falla, se reintenta solo la próxima vez que el
      // token cambie o la app se reabra con esta misma dependencia.
    });
  }, [voip, usuario]);

  // Entorno (extensión propia + credenciales SIP) — igual que
  // frontend/lib/softphone-context.tsx, ver /api/auth/mi-entorno.
  useEffect(() => {
    if (!usuario || !puede("softphone:usar")) return;
    peticion<MiEntorno>("/api/auth/mi-entorno")
      .then(setEntorno)
      .catch(() => setEntorno(null));
  }, [usuario, puede]);

  const startTimer = () => {
    setCallSeconds(0);
    timerRef.current = setInterval(() => setCallSeconds((s) => s + 1), 1000);
  };
  const stopTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };

  const limpiarLlamada = useCallback(() => {
    stopTimer();
    sessionRef.current = null;
    idNativoRef.current = null;
    requestIdRef.current = null;
    setPhase("idle");
    setRemoteParty("");
    setMuted(false);
  }, []);

  const bindSession = useCallback((session: Session, party: string, incoming: boolean) => {
    sessionRef.current = session;
    setRemoteParty(party);
    setPhase(incoming ? "incoming" : "outgoing");

    session.stateChange.addListener((state) => {
      if (sessionRef.current !== session) return;
      switch (state) {
        case SessionState.Established:
          setPhase("in-call");
          startTimer();
          break;
        case SessionState.Terminated: {
          // Si el otro lado colgó (no nosotros desde la UI: eso ya limpia
          // por su cuenta en hangup()), hay que avisarle al sistema —
          // CallKit/Telecom no se enteran solos de un BYE que llega por SIP.
          const id = idNativoRef.current;
          if (id) reportCallEnded(id, "remoteEnded").catch(() => {});
          limpiarLlamada();
          break;
        }
        default:
          break;
      }
    });
  }, [limpiarLlamada]);

  const connect = useCallback(async () => {
    const ext = entorno?.extension;
    if (!ext || !entorno?.fs_domain || !entorno?.sip_ws_url) return;
    setConnState("connecting");
    setConnError("");
    intentionalUnregisterRef.current = false;
    const miGeneracion = ++generacionRef.current;
    const esVigente = () => generacionRef.current === miGeneracion;

    if (userAgentRef.current) {
      const viejo = userAgentRef.current;
      userAgentRef.current = null;
      registererRef.current = null;
      try {
        await viejo.stop();
      } catch {
        // el intento viejo ya estaba roto
      }
    }

    try {
      const uri = UserAgent.makeURI(`sip:${ext.number}@${entorno.fs_domain}`);
      if (!uri) throw new Error("Extensión o dominio SIP inválido");

      const options: UserAgentOptions = {
        uri,
        transportOptions: { server: entorno.sip_ws_url },
        authorizationUsername: ext.number,
        authorizationPassword: ext.password,
        displayName: ext.caller_id_name || ext.number,
        logLevel: "error",
        sessionDescriptionHandlerFactoryOptions: {
          iceGatheringTimeout: 1500,
          peerConnectionConfiguration: {
            iceServers: entorno.ice_servers?.length
              ? (entorno.ice_servers as RTCIceServer[])
              : [{ urls: ["stun:stun.l.google.com:19302"] }],
          },
        },
        delegate: {
          onInvite: (invitation: Invitation) => {
            manejarInvite(invitation);
          },
          onDisconnect: () => {
            if (intentionalUnregisterRef.current || !esVigente()) return;
            setConnState("error");
            setConnError("Se perdió la conexión con la central. Reconectando…");
            programarReconexion();
          },
        },
      };

      const ua = new UserAgent(options);
      userAgentRef.current = ua;
      await ua.start();

      const registerer = new Registerer(ua);
      registererRef.current = registerer;
      registerer.stateChange.addListener((state) => {
        if (!esVigente()) return;
        if (state === RegistererState.Registered) {
          setConnState("registered");
        } else if (state === RegistererState.Unregistered) {
          if (intentionalUnregisterRef.current) {
            setConnState("disconnected");
          } else {
            setConnState("error");
            setConnError("Registro rechazado por la central");
            programarReconexion();
          }
        }
      });
      await registerer.register();
    } catch (e) {
      if (!esVigente()) return;
      setConnState("error");
      setConnError(e instanceof Error ? e.message : "Error al conectar");
      if (!intentionalUnregisterRef.current) programarReconexion();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entorno]);

  const connectRef = useRef<() => void>(() => {});
  connectRef.current = connect;

  const programarReconexion = () => {
    if (reconnectTimerRef.current) return;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      if (!intentionalUnregisterRef.current) connectRef.current();
    }, 4000);
  };

  // Llega un INVITE por SIP. Si ya había una llamada entrante reportada al
  // sistema (por push o porque este mismo handler la reportó hace un
  // instante), se empata con esa; si no, se reporta ahora mismo — cubre
  // el caso de estar en primer plano y YA conectado (sin haber pasado por
  // push) para que igual se vea la UI nativa de CallKit/Telecom.
  const manejarInvite = useCallback((invitation: Invitation) => {
    const numero = invitation.remoteIdentity.uri.user ?? "desconocido";
    bindSession(invitation, numero, true);

    if (idNativoRef.current) return; // ya viene de un push, ver addCallSessionAddedListener

    reportIncomingCall({
      eventId: `${Date.now()}`,
      serverCallId: invitation.request.callId,
      hasVideo: false,
      caller: { id: numero, displayName: invitation.remoteIdentity.displayName || numero, phoneNumber: numero },
    }).catch(() => {
      // Si el SO rechaza el reporte (otra llamada activa, etc.), la
      // llamada sigue viva por SIP igual; solo no se ve el CallKit nativo.
    });
  }, [bindSession]);

  // Sesión nativa agregada (CallKit/Telecom) — cubre tanto el reporte de
  // arriba (nos llega nuestro propio id) como el caso de un push recibido
  // con la app en segundo plano/cerrada, donde el SO ya mostró la UI de
  // llamada ANTES de que corriera esta línea: acá solo se toma nota del
  // id para poder empatarlo con el INVITE que llega (o ya llegó) por SIP.
  useEffect(() => {
    const sub = addCallSessionAddedListener(({ session }: { session: CallSession }) => {
      if (session.origin !== "incoming") return;
      idNativoRef.current = session.id;
      // Si la app estaba dormida, esto es también la señal de reconectar
      // el softphone para que el INVITE de verdad pueda llegar.
      if (connState !== "registered" && connState !== "connecting") connect();
    });
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connState, connect]);

  useEffect(() => {
    const sub = addCallAnsweredListener(({ id, requestId }) => {
      if (id !== idNativoRef.current) return;
      requestIdRef.current = requestId;
      const session = sessionRef.current;
      if (!(session instanceof Invitation)) return;
      prepareAudioSessionForCall(false);
      session
        .accept({ sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } } })
        .then(() => fulfillIncomingCallConnected(requestId))
        .catch(() => failIncomingCallConnected(id, requestId));
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    const sub = addCallEndedListener(({ id }) => {
      if (id !== idNativoRef.current) return;
      const session = sessionRef.current;
      if (session && session.state !== SessionState.Terminated) {
        if (session instanceof Invitation) session.reject().catch(() => {});
        else if (session.state === SessionState.Established) session.bye().catch(() => {});
      }
      limpiarLlamada();
    });
    return () => sub.remove();
  }, [limpiarLlamada]);

  useEffect(() => {
    const sub = addSetMutedActionListener(({ id, isMuted }) => {
      if (id !== idNativoRef.current) return;
      aplicarMute(isMuted);
      setMuted(isMuted);
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    const sub = addDTMFListener(({ id, digits }) => {
      if (id !== idNativoRef.current) return;
      const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
      sdh?.sendDtmf?.(digits);
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    const sub = addOutgoingCallStartedListener(({ id }) => {
      const pendiente = destinoSalienteRef.current;
      if (!pendiente || pendiente.id !== id || !userAgentRef.current || !entorno?.fs_domain) return;
      destinoSalienteRef.current = null;
      idNativoRef.current = id;
      try {
        const target = UserAgent.makeURI(`sip:${pendiente.destino}@${entorno.fs_domain}`);
        if (!target) throw new Error("Destino inválido");
        const inviter = new Inviter(userAgentRef.current, target, {
          sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } },
        });
        bindSession(inviter, pendiente.destino, false);
        inviter.stateChange.addListener((state) => {
          if (state === SessionState.Established) reportOutgoingCallConnected(id).catch(() => {});
        });
        inviter.invite();
      } catch {
        endCall(id).catch(() => {});
        limpiarLlamada();
      }
    });
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entorno, bindSession]);

  const aplicarMute = (next: boolean) => {
    const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
    const pc = sdh?.peerConnection;
    pc?.getSenders().forEach((sender) => {
      if (sender.track) sender.track.enabled = !next;
    });
  };

  const toggleMute = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      aplicarMute(next);
      if (idNativoRef.current) setMutedNativo(idNativoRef.current, next).catch(() => {});
      return next;
    });
  }, []);

  const call = useCallback(async () => {
    if (!destination || !entorno?.fs_domain) return;
    try {
      const id = await startOutgoingCall(
        { id: destination, displayName: destination, phoneNumber: destination },
        { hasVideo: false }
      );
      destinoSalienteRef.current = { id, destino: destination };
    } catch (e) {
      setConnError(e instanceof Error ? e.message : "No se pudo iniciar la llamada");
    }
  }, [destination, entorno]);

  const hangup = useCallback(async () => {
    const session = sessionRef.current;
    const id = idNativoRef.current;
    try {
      if (session) {
        if (session.state === SessionState.Established) await session.bye();
        else if (session instanceof Inviter) await session.cancel();
        else if (session instanceof Invitation) await session.reject();
      }
    } catch {
      // ignore
    }
    if (id) endCall(id).catch(() => {});
    limpiarLlamada();
  }, [limpiarLlamada]);

  const sendDtmf = useCallback(
    (digit: string) => {
      if (phase === "in-call") {
        const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
        sdh?.sendDtmf?.(digit);
      } else {
        setDestination((d) => d + digit);
      }
    },
    [phase]
  );

  const activarDnd = useCallback(async (activar: boolean) => {
    await peticion("/api/auth/dnd", { method: "POST", body: { enabled: activar } });
    setEntorno((e) => (e?.extension ? { ...e, extension: { ...e.extension, dnd: activar } } : e));
  }, []);

  // Se conecta solo apenas hay entorno — igual que el panel web, la
  // extensión es la del usuario que inició sesión, nada que elegir.
  const autoIntentadoRef = useRef(false);
  useEffect(() => {
    if (autoIntentadoRef.current || !entorno) return;
    autoIntentadoRef.current = true;
    if (entorno.extension?.enabled) connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entorno]);

  useEffect(() => {
    if (!usuario) {
      intentionalUnregisterRef.current = true;
      userAgentRef.current?.stop().catch(() => {});
      userAgentRef.current = null;
      registererRef.current = null;
      setConnState("disconnected");
      setEntorno(null);
    }
  }, [usuario]);

  return (
    <Ctx.Provider
      value={{
        entorno,
        connState,
        connError,
        phase,
        destination,
        remoteParty,
        muted,
        callSeconds,
        setDestination,
        connect,
        call,
        hangup,
        toggleMute,
        sendDtmf,
        activarDnd,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}
