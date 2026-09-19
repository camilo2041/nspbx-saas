import {
  addCallAnsweredListener,
  addCallEndedListener,
  addCallSessionAddedListener,
  addDTMFListener,
  addOutgoingCallStartedListener,
  addSetMutedActionListener,
  answerCall,
  endCall,
  failIncomingCallConnected,
  fulfillIncomingCallConnected,
  prepareAudioSessionForCall,
  registerVoIPPush,
  reportCallEnded,
  reportIncomingCall,
  reportOutgoingCallConnected,
  setAudioSessionPortOverride,
  setMuted as setMutedNativo,
  startOutgoingCall,
  useVoIPPushToken,
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
import { AppState, PermissionsAndroid, Platform } from "react-native";
import {
  Invitation,
  Inviter,
  Registerer,
  RegistererState,
  Session,
  SessionState,
  UserAgent,
  type UserAgentOptions,
} from "sip.js";

import { peticion, resolverServidorSip, servidorConfigurado } from "@/src/api/client";
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
  speaker: boolean;
  callSeconds: number;
  setDestination: (v: string) => void;
  connect: () => Promise<void>;
  call: () => Promise<void>;
  answer: () => Promise<void>;
  reject: () => Promise<void>;
  hangup: () => Promise<void>;
  toggleMute: () => void;
  toggleSpeaker: () => void;
  sendDtmf: (digit: string) => void;
  activarDnd: (activar: boolean) => Promise<void>;
}

const Ctx = createContext<SoftphoneCtx | null>(null);

export function useSoftphone(): SoftphoneCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSoftphone debe usarse dentro de <SoftphoneProvider>");
  return ctx;
}

/**
 * Android exige pedir el micrófono EN TIEMPO DE EJECUCIÓN; declararlo en el
 * manifiesto no alcanza. Sin este permiso `getUserMedia` falla y la llamada
 * conecta pero queda muda. En iOS lo pide el sistema al usar el micrófono
 * (texto de NSMicrophoneUsageDescription en app.json).
 */
async function asegurarMicrofono(): Promise<boolean> {
  if (Platform.OS !== "android") return true;
  const r = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO, {
    title: "Micrófono",
    message: "NSPBX necesita el micrófono para hablar en las llamadas.",
    buttonPositive: "Permitir",
    buttonNegative: "Ahora no",
  });
  return r === PermissionsAndroid.RESULTS.GRANTED;
}

/** Android 13+: sin este permiso no se puede mostrar el aviso de llamada. */
async function pedirNotificaciones(): Promise<void> {
  if (Platform.OS === "android" && Number(Platform.Version) >= 33) {
    await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
  }
}

const OPCIONES_AUDIO = { sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } } };
const RETRASO_MAX_RECONEXION_MS = 60_000;

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const { usuario, puede } = useAuth();

  const [entorno, setEntorno] = useState<MiEntorno | null>(null);
  const [connState, setConnState] = useState<ConnState>("disconnected");
  const [connError, setConnError] = useState("");
  const [destination, setDestination] = useState("");
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [remoteParty, setRemoteParty] = useState("");
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);
  const [callSeconds, setCallSeconds] = useState(0);

  // Los manejadores de eventos nativos y de SIP viven más que un render:
  // leen el estado más reciente a través de refs, no de variables capturadas
  // (que quedaban viejas y hacían perder respuestas a llamadas).
  const entornoRef = useRef<MiEntorno | null>(null);
  entornoRef.current = entorno;
  const connStateRef = useRef<ConnState>("disconnected");
  connStateRef.current = connState;

  const userAgentRef = useRef<UserAgent | null>(null);
  const registererRef = useRef<Registerer | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const apagadoRef = useRef(true);
  const generacionRef = useRef(0);
  const intentosRef = useRef(0);

  // Puente entre CallKit/Telecom (ids de sesión del sistema) y sip.js (la
  // sesión SIP real). Se maneja UNA llamada a la vez a propósito: es el
  // teléfono de una extensión personal, y CallKit/Telecom generan su propio
  // id, ajeno al del INVITE, así que no hay identificador compartido con qué
  // correlacionar más de una.
  const idNativoRef = useRef<string | null>(null);
  const respuestaPendienteRef = useRef<{ id: string; requestId: string } | null>(null);
  const salientePendienteRef = useRef<{ id: string; destino: string } | null>(null);
  // Invitación que ya se está aceptando: el botón de la app y el evento del
  // sistema podían disparar accept() a la vez (segundo 200 OK o excepción).
  const aceptandoRef = useRef<Invitation | null>(null);
  // Temporizadores de respaldo de UNA llamada. Se cancelan al terminarla: uno
  // que dispara después ("contestar en 1,5 s", "marcar en 3 s") actuaba sobre
  // la llamada siguiente.
  const temporizadoresRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const temporizarLlamada = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(() => {
      temporizadoresRef.current.delete(t);
      fn();
    }, ms);
    temporizadoresRef.current.add(t);
  }, []);

  const voip = useVoIPPushToken();

  useEffect(() => {
    // En Android esto lanza si el proyecto no tiene google-services.json
    // (ver SETUP.md); sin el try/catch cerraba la app al abrirla.
    try {
      registerVoIPPush();
    } catch (e) {
      console.warn("Push de voz no disponible:", e instanceof Error ? e.message : "error");
    }
  }, []);

  useEffect(() => {
    if (!voip || !usuario) return;
    const platform = voip.type === "APNS_VOIP" ? "ios" : "android";
    peticion("/api/auth/dispositivo", {
      method: "POST",
      body: { platform, token_type: voip.type, token: voip.token },
    }).catch(() => {});
  }, [voip, usuario]);

  useEffect(() => {
    if (!usuario || !puede("softphone:usar")) return;
    peticion<MiEntorno>("/api/auth/mi-entorno")
      .then(setEntorno)
      .catch(() => setEntorno(null));
    pedirNotificaciones().catch(() => {});
    asegurarMicrofono().catch(() => {});
  }, [usuario, puede]);

  const stopTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };
  const startTimer = () => {
    stopTimer();
    setCallSeconds(0);
    timerRef.current = setInterval(() => setCallSeconds((s) => s + 1), 1000);
  };

  const limpiarLlamada = useCallback(() => {
    stopTimer();
    temporizadoresRef.current.forEach((t) => clearTimeout(t));
    temporizadoresRef.current.clear();
    aceptandoRef.current = null;
    sessionRef.current = null;
    idNativoRef.current = null;
    respuestaPendienteRef.current = null;
    salientePendienteRef.current = null;
    setPhase("idle");
    setRemoteParty("");
    setMuted(false);
    setSpeaker(false);
  }, []);

  const bindSession = useCallback(
    (session: Session, party: string, incoming: boolean) => {
      sessionRef.current = session;
      setRemoteParty(party);
      setPhase(incoming ? "incoming" : "outgoing");

      session.stateChange.addListener((state) => {
        if (sessionRef.current !== session) return;
        if (state === SessionState.Established) {
          setPhase("in-call");
          startTimer();
        } else if (state === SessionState.Terminated) {
          // Si colgó el otro lado, CallKit/Telecom no se enteran solos de un
          // BYE que llega por SIP: hay que avisarles.
          const id = idNativoRef.current;
          if (id) reportCallEnded(id, "remoteEnded").catch(() => {});
          limpiarLlamada();
        }
      });
    },
    [limpiarLlamada]
  );

  const aceptarInvitacion = useCallback(
    async (inv: Invitation, requestId?: string) => {
      // Ya se aceptó (o se está aceptando) por otro camino: no repetir.
      if (inv.state !== SessionState.Initial || aceptandoRef.current === inv) {
        if (requestId && inv.state !== SessionState.Terminated) fulfillIncomingCallConnected(requestId).catch(() => {});
        return;
      }
      aceptandoRef.current = inv;

      // Falla al contestar: se rechaza la llamada, se avisa al sistema y se
      // limpia la pantalla; antes quedaba "Llamada entrante" para siempre.
      const abortar = (mensaje: string) => {
        setConnError(mensaje);
        const id = idNativoRef.current;
        if (requestId && id) failIncomingCallConnected(id, requestId).catch(() => {});
        inv.reject().catch(() => {});
        if (id) endCall(id).catch(() => {});
        limpiarLlamada();
      };

      if (!(await asegurarMicrofono())) {
        abortar("Sin permiso de micrófono: actívalo en Ajustes del teléfono para contestar.");
        return;
      }
      try {
        prepareAudioSessionForCall(false);
        await inv.accept(OPCIONES_AUDIO);
        if (requestId) fulfillIncomingCallConnected(requestId).catch(() => {});
      } catch (e) {
        console.warn("No se pudo contestar:", e instanceof Error ? e.message : "error");
        abortar("No se pudo contestar la llamada. Inténtalo de nuevo.");
      }
    },
    [limpiarLlamada]
  );

  // Llega un INVITE por SIP.
  const manejarInvite = useCallback(
    (invitation: Invitation) => {
      // Ya hay una llamada en curso: se responde ocupado en vez de pisarla.
      if (sessionRef.current && sessionRef.current.state !== SessionState.Terminated) {
        invitation.reject({ statusCode: 486 }).catch(() => {});
        return;
      }
      const numero = invitation.remoteIdentity.uri.user ?? "desconocido";
      const nombre = invitation.remoteIdentity.displayName || numero;
      bindSession(invitation, nombre === numero ? numero : `${nombre} (${numero})`, true);

      // El usuario ya había contestado desde la pantalla nativa que despertó
      // el push, antes de que el INVITE terminara de llegar.
      const pendiente = respuestaPendienteRef.current;
      if (pendiente) {
        respuestaPendienteRef.current = null;
        aceptarInvitacion(invitation, pendiente.requestId);
        return;
      }
      // Si el sistema ya tiene la llamada (llegó por push), no se reporta
      // otra vez; si no, se reporta ahora para que suene con la UI nativa.
      if (!idNativoRef.current) {
        reportIncomingCall({
          eventId: `${Date.now()}`,
          serverCallId: invitation.request.callId,
          hasVideo: false,
          caller: { id: numero, displayName: nombre, phoneNumber: numero },
        }).catch(() => {
          // Sin UI nativa la llamada sigue viva por SIP: quedan los botones
          // Contestar/Rechazar dentro de la app.
        });
      }
    },
    [bindSession, aceptarInvitacion]
  );
  const manejarInviteRef = useRef(manejarInvite);
  manejarInviteRef.current = manejarInvite;

  const programarReconexion = useCallback(() => {
    if (reconnectTimerRef.current || apagadoRef.current) return;
    // Espera creciente (4 s, 8 s, 16 s… hasta 1 min): con la red caída o una
    // contraseña mala, reintentar cada 4 s sin freno gasta batería y ensucia
    // el registro de la central.
    const espera = Math.min(4000 * 2 ** intentosRef.current, RETRASO_MAX_RECONEXION_MS);
    intentosRef.current += 1;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      if (!apagadoRef.current) connectRef.current();
    }, espera);
  }, []);

  const connect = useCallback(async () => {
    const env = entornoRef.current;
    const ext = env?.extension;
    if (!env || !ext || !env.fs_domain) return;
    apagadoRef.current = false;
    setConnState("connecting");
    setConnError("");
    const miGeneracion = ++generacionRef.current;
    const esVigente = () => generacionRef.current === miGeneracion;

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
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
      const uri = UserAgent.makeURI(`sip:${ext.number}@${env.fs_domain}`);
      if (!uri) throw new Error("Extensión o dominio SIP inválido");
      const servidor = await servidorConfigurado();
      const servidorSip = resolverServidorSip(env.sip_ws_url, servidor?.apiBase ?? null);
      if (!servidorSip) throw new Error("No hay dirección del servidor SIP configurada");

      const options: UserAgentOptions = {
        uri,
        transportOptions: { server: servidorSip },
        authorizationUsername: ext.number,
        authorizationPassword: ext.password,
        displayName: ext.caller_id_name || ext.number,
        logLevel: "error",
        sessionDescriptionHandlerFactoryOptions: {
          iceGatheringTimeout: 1500,
          peerConnectionConfiguration: {
            iceServers: env.ice_servers?.length
              ? (env.ice_servers as RTCIceServer[])
              : [{ urls: ["stun:stun.l.google.com:19302"] }],
          },
        },
        delegate: {
          onInvite: (invitation: Invitation) => manejarInviteRef.current(invitation),
          onDisconnect: () => {
            if (apagadoRef.current || !esVigente()) return;
            setConnState("error");
            setConnError("Se perdió la conexión con la central. Reconectando…");
            programarReconexion();
          },
        },
      };

      const ua = new UserAgent(options);
      await ua.start();
      if (!esVigente()) {
        // Mientras arrancaba, otro intento (o un cierre de sesión) lo dejó
        // viejo: se apaga en vez de quedar vivo sin dueño.
        ua.stop().catch(() => {});
        return;
      }
      userAgentRef.current = ua;

      const registerer = new Registerer(ua);
      registererRef.current = registerer;
      registerer.stateChange.addListener((state) => {
        if (!esVigente()) return;
        if (state === RegistererState.Registered) {
          intentosRef.current = 0;
          setConnState("registered");
          setConnError("");
        } else if (state === RegistererState.Unregistered) {
          if (apagadoRef.current) {
            setConnState("disconnected");
          } else {
            setConnState("error");
            setConnError("La central rechazó el registro de tu extensión");
            programarReconexion();
          }
        }
      });
      await registerer.register();
    } catch (e) {
      if (!esVigente()) return;
      setConnState("error");
      setConnError(e instanceof Error ? e.message : "No se pudo conectar con la central");
      programarReconexion();
    }
  }, [programarReconexion]);

  const connectRef = useRef<() => void>(() => {});
  connectRef.current = connect;

  // Apaga todo: al cerrar sesión no debe quedar nada vivo (registro SIP,
  // reintentos, llamada, temporizador) ni datos del usuario anterior.
  const apagar = useCallback(() => {
    apagadoRef.current = true;
    generacionRef.current += 1;
    intentosRef.current = 0;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
    const ua = userAgentRef.current;
    userAgentRef.current = null;
    registererRef.current = null;
    ua?.stop().catch(() => {});
    limpiarLlamada();
    setDestination("");
    setConnState("disconnected");
    setConnError("");
    setEntorno(null);
    autoIntentadoRef.current = false;
  }, [limpiarLlamada]);

  const autoIntentadoRef = useRef(false);
  useEffect(() => {
    if (autoIntentadoRef.current || !entorno) return;
    autoIntentadoRef.current = true;
    if (entorno.extension?.enabled) connect();
  }, [entorno, connect]);

  useEffect(() => {
    if (!usuario) apagar();
  }, [usuario, apagar]);

  // Al volver a la app, el WebSocket casi seguro murió mientras estaba en
  // segundo plano: se reconecta en vez de esperar al próximo reintento.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (estado) => {
      if (estado === "active" && entornoRef.current && !apagadoRef.current && connStateRef.current !== "registered") {
        intentosRef.current = 0;
        connectRef.current();
      }
    });
    return () => sub.remove();
  }, []);

  // ---- Eventos de CallKit/Telecom ------------------------------------
  // Cada suscripción se crea UNA vez y lee el estado por refs; antes se
  // recreaban con cada cambio de conexión y los eventos que caían en el
  // intervalo se perdían.
  useEffect(() => {
    const subs = [
      addCallSessionAddedListener(({ session }) => {
        if (session.origin !== "incoming") return;
        idNativoRef.current = session.id;
        // Llamada que despertó la app por push: aún no llegó el INVITE.
        if (!sessionRef.current) {
          const quien = session.remoteParticipants[0];
          setRemoteParty(quien?.displayName || quien?.phoneNumber || "Llamada entrante");
          setPhase("incoming");
        }
        const s = connStateRef.current;
        if (s !== "registered" && s !== "connecting") connectRef.current();
      }),

      addCallAnsweredListener(({ id, requestId }) => {
        if (!idNativoRef.current) idNativoRef.current = id;
        if (id !== idNativoRef.current) return;
        const s = sessionRef.current;
        if (s instanceof Invitation) {
          if (s.state === SessionState.Initial) aceptarInvitacion(s, requestId);
          else fulfillIncomingCallConnected(requestId).catch(() => {});
        } else {
          // Contestó antes de que llegara el INVITE: se atiende al llegar.
          respuestaPendienteRef.current = { id, requestId };
        }
      }),

      addCallEndedListener(({ id }) => {
        if (id !== idNativoRef.current) return;
        const s = sessionRef.current;
        if (s && s.state !== SessionState.Terminated) {
          if (s instanceof Invitation && s.state === SessionState.Initial) s.reject().catch(() => {});
          else if (s.state === SessionState.Established) s.bye().catch(() => {});
          else if (s instanceof Inviter) s.cancel().catch(() => {});
        }
        limpiarLlamada();
      }),

      addSetMutedActionListener(({ id, isMuted }) => {
        if (id !== idNativoRef.current) return;
        aplicarMute(isMuted);
        setMuted(isMuted);
      }),

      addDTMFListener(({ id, digits }) => {
        if (id !== idNativoRef.current) return;
        const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
        sdh?.sendDtmf?.(digits);
      }),

      addOutgoingCallStartedListener(({ id }) => iniciarSaliente(id)),
    ];
    return () => subs.forEach((s) => s.remove());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aceptarInvitacion, limpiarLlamada]);

  const aplicarMute = (next: boolean) => {
    const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
    sdh?.peerConnection?.getSenders().forEach((sender) => {
      if (sender.track) sender.track.enabled = !next;
    });
  };

  // Envía el INVITE de una llamada saliente. Idempotente: lo dispara el
  // evento del sistema o, si éste no llega, el temporizador de respaldo.
  const iniciarSaliente = (id: string) => {
    const pendiente = salientePendienteRef.current;
    const env = entornoRef.current;
    const ua = userAgentRef.current;
    if (!pendiente || pendiente.id !== id || !env?.fs_domain) return;
    salientePendienteRef.current = null;
    idNativoRef.current = id;
    try {
      if (!ua) throw new Error("Sin conexión con la central");
      const target = UserAgent.makeURI(`sip:${pendiente.destino}@${env.fs_domain}`);
      if (!target) throw new Error("Destino inválido");
      const inviter = new Inviter(ua, target, OPCIONES_AUDIO);
      bindSession(inviter, pendiente.destino, false);
      inviter.stateChange.addListener((state) => {
        if (state === SessionState.Established) reportOutgoingCallConnected(id).catch(() => {});
      });
      inviter
        .invite({
          requestDelegate: {
            // La central respondió con un error (ruta inexistente, ocupado, sin permiso…).
            onReject: (respuesta) => {
              const { statusCode, reasonPhrase } = respuesta.message;
              setConnError(`La central no completó la llamada (${statusCode} ${reasonPhrase}).`);
            },
          },
        })
        .catch((e) => {
          // Fallo local antes de llegar a la central (micrófono, WebRTC…).
          console.warn("Fallo al iniciar la llamada:", e instanceof Error ? e.message : "error");
          setConnError(`No se pudo iniciar la llamada: ${e instanceof Error ? e.message : String(e)}`);
          endCall(id).catch(() => {});
          limpiarLlamada();
        });
    } catch (e) {
      setConnError(e instanceof Error ? e.message : "No se pudo llamar");
      endCall(id).catch(() => {});
      limpiarLlamada();
    }
  };

  const call = useCallback(async () => {
    if (!destination || phase !== "idle") return;
    setConnError("");
    if (connStateRef.current !== "registered") {
      setConnError("Sin conexión con la central: espera a que diga Conectado.");
      return;
    }
    if (!(await asegurarMicrofono())) {
      setConnError("Sin permiso de micrófono: actívalo en Ajustes del teléfono para llamar.");
      return;
    }
    try {
      prepareAudioSessionForCall(false);
      const id = await startOutgoingCall(
        { id: destination, displayName: destination, phoneNumber: destination },
        { hasVideo: false }
      );
      salientePendienteRef.current = { id, destino: destination };
      setRemoteParty(destination);
      setPhase("outgoing");
      // Respaldo: si el sistema no avisa que aceptó la llamada, se marca igual.
      temporizarLlamada(() => iniciarSaliente(id), 3000);
    } catch (e) {
      console.warn("startOutgoingCall falló:", e instanceof Error ? e.message : "error");
      setConnError(`El teléfono no permitió iniciar la llamada: ${e instanceof Error ? e.message : String(e)}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destination, phase, temporizarLlamada]);

  // Contestar desde los botones de la app. Con UI nativa activa se pasa por
  // el sistema (que emite el evento de respuesta); si éste no llega, se
  // contesta directamente para que el botón NUNCA quede sin efecto.
  const answer = useCallback(async () => {
    const inv = sessionRef.current;
    if (!(inv instanceof Invitation) || inv.state !== SessionState.Initial) return;
    const id = idNativoRef.current;
    if (id) {
      answerCall(id).catch(() => {});
      temporizarLlamada(() => {
        if (sessionRef.current === inv && inv.state === SessionState.Initial) aceptarInvitacion(inv);
      }, 1500);
    } else {
      await aceptarInvitacion(inv);
    }
  }, [aceptarInvitacion, temporizarLlamada]);

  const hangup = useCallback(async () => {
    const session = sessionRef.current;
    const id = idNativoRef.current;
    try {
      if (session && session.state !== SessionState.Terminated) {
        if (session.state === SessionState.Established) await session.bye();
        else if (session instanceof Inviter) await session.cancel();
        else if (session instanceof Invitation) await session.reject();
      }
    } catch {
      // ya estaba terminada
    }
    if (id) endCall(id).catch(() => {});
    limpiarLlamada();
  }, [limpiarLlamada]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    aplicarMute(next);
    setMuted(next);
    if (idNativoRef.current) setMutedNativo(idNativoRef.current, next).catch(() => {});
  }, [muted]);

  const toggleSpeaker = useCallback(() => {
    const next = !speaker;
    try {
      setAudioSessionPortOverride(next);
      setSpeaker(next);
    } catch {
      // sin sesión de audio activa todavía
    }
  }, [speaker]);

  const sendDtmf = useCallback(
    (digit: string) => {
      if (phase === "in-call") {
        const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
        sdh?.sendDtmf?.(digit);
      } else if (phase === "idle") {
        setDestination((d) => (d + digit).slice(0, 30));
      }
    },
    [phase]
  );

  const activarDnd = useCallback(async (activar: boolean) => {
    await peticion("/api/auth/dnd", { method: "POST", body: { enabled: activar } });
    setEntorno((e) => (e?.extension ? { ...e, extension: { ...e.extension, dnd: activar } } : e));
  }, []);

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
        speaker,
        callSeconds,
        setDestination,
        connect,
        call,
        answer,
        reject: hangup,
        hangup,
        toggleMute,
        toggleSpeaker,
        sendDtmf,
        activarDnd,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}
