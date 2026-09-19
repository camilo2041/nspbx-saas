"use client";

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

import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { MiEntorno, PERMISOS } from "@/lib/types";

export type ConnState = "disconnected" | "connecting" | "registered" | "error";
export type CallPhase = "idle" | "outgoing" | "incoming" | "in-call" | "ended";

interface SdhLike {
  peerConnection?: RTCPeerConnection;
  sendDtmf?: (tone: string) => boolean;
}

interface SoftphoneCtx {
  entorno: MiEntorno | null;
  loadError: string;
  dndCambiando: boolean;
  dndError: string;
  connState: ConnState;
  connError: string;
  destination: string;
  phase: CallPhase;
  remoteParty: string;
  muted: boolean;
  callSeconds: number;
  setDestination: (v: string) => void;
  setConnError: (v: string) => void;
  setDndError: (v: string) => void;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  activarDnd: (activar: boolean) => Promise<void>;
  call: () => Promise<void>;
  answer: () => Promise<void>;
  reject: () => Promise<void>;
  hangup: () => Promise<void>;
  toggleMute: () => void;
  sendDtmf: (digit: string) => void;
}

const Ctx = createContext<SoftphoneCtx | null>(null);

/**
 * Dirección del WebSocket SIP al que se conecta el softphone.
 *
 * El valor de Ajustes manda, pero si quedó vacío o apuntando a
 * localhost —que es como viene de fábrica— y el panel se está sirviendo
 * por HTTPS, se deduce del propio dominio: el proxy rutea /sip hacia
 * FreeSWITCH (ver deploy/traefik-dynamic.yml.example).
 *
 * Existe porque el valor de fábrica es "wss://localhost:7443", que solo
 * sirve si el navegador corre en el mismo equipo que FreeSWITCH. Al
 * publicar el panel en un dominio, el softphone seguía intentando
 * contra localhost y fallaba con "WebSocket closed (code: 1006)", un
 * error que no sugiere en absoluto que el problema sea un ajuste sin
 * actualizar.
 */
export function resolverServidorSip(configurado: string | null | undefined): string {
  const v = (configurado ?? "").trim();
  const esLocal = v === "" || /^wss?:\/\/(localhost|127\.0\.0\.1)/i.test(v);
  if (esLocal && typeof window !== "undefined" && window.location.protocol === "https:") {
    return `wss://${window.location.host}/sip`;
  }
  return v;
}

export function useSoftphone() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSoftphone debe usarse dentro de <SoftphoneProvider>");
  return ctx;
}

/**
 * Timbre sintetizado con Web Audio API en vez de un archivo de sonido: no
 * hace falta ningún asset ni licencia, y el navegador ya nos obliga a
 * "desbloquear" el audio con un gesto del usuario de todas formas — con un
 * <audio src> pasaría lo mismo. Se desbloquea solo, en el primer click en
 * cualquier parte de la app (ver `unlock` más abajo), mucho antes de que
 * pueda entrar una llamada real.
 */
class Ringer {
  private ctx: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  unlock() {
    if (this.ctx) return;
    try {
      const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new Ctor();
    } catch {
      // Web Audio no disponible: el timbre simplemente no sonará, el
      // banner visual sigue funcionando igual.
    }
  }

  // Un solo timbrazo: dos tonos (440/480Hz, las mismas frecuencias del
  // tono de llamada telefónico clásico norteamericano — mucho más "cálido"
  // que un pitido agudo) con un leve trémolo de volumen durante el sonido.
  // Ese trémolo es justo lo que distingue a un timbre de teléfono de una
  // alerta electrónica plana: sin él, dos senos sostenidos suenan a
  // notificación de app, no a llamada entrante.
  private tono(inicio: number, duracion: number) {
    const ctx = this.ctx;
    if (!ctx) return;
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    const pasos = 48;
    const curva = new Float32Array(pasos);
    for (let i = 0; i < pasos; i++) {
      const t = i / (pasos - 1);
      const envolvente = Math.sin(Math.PI * t); // entra y sale suave, sin clicks
      const tremolo = 0.72 + 0.28 * Math.sin(t * duracion * 2 * Math.PI * 15); // ~15Hz, el "brrr"
      curva[i] = Math.max(0, envolvente * tremolo * 0.32);
    }
    gain.gain.setValueCurveAtTime(curva, inicio, duracion);
    [440, 480].forEach((freq) => {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.value = freq;
      osc.connect(gain);
      osc.start(inicio);
      osc.stop(inicio + duracion);
    });
  }

  // Patrón de doble timbrazo ("ring-ring… ring-ring…"), como un teléfono
  // de verdad — no un solo bip.
  private burst() {
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    this.tono(now, 0.4);
    this.tono(now + 0.5, 0.4);
  }

  start() {
    if (!this.ctx) this.unlock();
    if (!this.ctx || this.timer) return;
    if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    this.burst();
    this.timer = setInterval(() => this.burst(), 2500);
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const { usuario, puede, cargando: cargandoAuth } = useAuth();

  const [entorno, setEntorno] = useState<MiEntorno | null>(null);
  const [loadError, setLoadError] = useState("");
  const [dndCambiando, setDndCambiando] = useState(false);
  const [dndError, setDndError] = useState("");

  const [connState, setConnState] = useState<ConnState>("disconnected");
  const [connError, setConnError] = useState("");

  const [destination, setDestination] = useState("");
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [remoteParty, setRemoteParty] = useState("");
  const [muted, setMuted] = useState(false);
  const [callSeconds, setCallSeconds] = useState(0);

  const userAgentRef = useRef<UserAgent | null>(null);
  const registererRef = useRef<Registerer | null>(null);
  const intentionalUnregisterRef = useRef(false);
  const sessionRef = useRef<Session | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ringerRef = useRef<Ringer | null>(null);
  const tituloOriginalRef = useRef<string>("");
  const parpadeoRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Se incrementa en cada connect(). Un evento que llega de un intento
  // VIEJO (registrador que ya quedó atrás) se descarta comparando contra
  // este número, así no puede pisar el estado de un intento más nuevo
  // aunque el viejo tarde en terminar de apagarse.
  const generacionRef = useRef(0);

  if (!ringerRef.current) ringerRef.current = new Ringer();

  // Desbloquea el audio sintetizado con el primer gesto del usuario en
  // cualquier parte de la app — para cuando entre una llamada real, ya
  // pasó rato desde el login/primer click y el navegador lo deja sonar
  // sin más interacción.
  useEffect(() => {
    const desbloquear = () => {
      ringerRef.current?.unlock();
      window.removeEventListener("pointerdown", desbloquear);
      window.removeEventListener("keydown", desbloquear);
    };
    window.addEventListener("pointerdown", desbloquear);
    window.addEventListener("keydown", desbloquear);
    return () => {
      window.removeEventListener("pointerdown", desbloquear);
      window.removeEventListener("keydown", desbloquear);
    };
  }, []);

  // Timbre + parpadeo del título de la pestaña mientras hay una llamada
  // entrante — así se nota aunque la persona esté en otra pantalla de la
  // app o en otra pestaña del navegador.
  useEffect(() => {
    if (phase === "incoming") {
      ringerRef.current?.start();
      if (!tituloOriginalRef.current) tituloOriginalRef.current = document.title;
      let visible = true;
      parpadeoRef.current = setInterval(() => {
        document.title = visible ? "📞 Llamada entrante…" : tituloOriginalRef.current;
        visible = !visible;
      }, 900);
    } else {
      ringerRef.current?.stop();
      if (parpadeoRef.current) {
        clearInterval(parpadeoRef.current);
        parpadeoRef.current = null;
      }
      if (tituloOriginalRef.current) {
        document.title = tituloOriginalRef.current;
      }
    }
    return () => {
      if (parpadeoRef.current) {
        clearInterval(parpadeoRef.current);
        parpadeoRef.current = null;
      }
    };
  }, [phase]);

  const attachRemoteAudio = (session: Session) => {
    const sdh = session.sessionDescriptionHandler as unknown as SdhLike | undefined;
    const pc = sdh?.peerConnection;
    if (!pc || !audioRef.current) return;
    const remoteStream = new MediaStream();
    pc.getReceivers().forEach((receiver) => {
      if (receiver.track) remoteStream.addTrack(receiver.track);
    });
    audioRef.current.srcObject = remoteStream;
    audioRef.current.play().catch(() => {});
  };

  const startTimer = () => {
    setCallSeconds(0);
    timerRef.current = setInterval(() => setCallSeconds((s) => s + 1), 1000);
  };

  const stopTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };

  const bindSession = useCallback((session: Session, party: string, incoming: boolean) => {
    sessionRef.current = session;
    setRemoteParty(party);
    setPhase(incoming ? "incoming" : "outgoing");

    // El audio remoto (incluido el tono de "está sonando" que muchos
    // proveedores mandan como early media, antes de que contesten) debe
    // conectarse apenas exista el peerConnection, no solo al contestar
    // (SessionState.Established) — si no, no se oye nada mientras timbra.
    const attachWhenReady = () => {
      if (sessionRef.current !== session) return; // la llamada ya cambió/terminó
      const sdh = session.sessionDescriptionHandler as unknown as SdhLike | undefined;
      const pc = sdh?.peerConnection;
      if (pc) {
        pc.addEventListener("track", () => attachRemoteAudio(session));
        attachRemoteAudio(session);
      } else if (session.state !== SessionState.Terminated) {
        setTimeout(attachWhenReady, 150);
      }
    };
    attachWhenReady();

    session.stateChange.addListener((state) => {
      switch (state) {
        case SessionState.Established:
          setPhase("in-call");
          attachRemoteAudio(session);
          startTimer();
          break;
        case SessionState.Terminated:
          stopTimer();
          setPhase("idle");
          setRemoteParty("");
          setMuted(false);
          sessionRef.current = null;
          if (audioRef.current) audioRef.current.srcObject = null;
          break;
        default:
          break;
      }
    });
  }, []);

  const connect = useCallback(async () => {
    const ext = entorno?.extension;
    const settings = entorno;
    if (!ext || !settings?.fs_domain) return;
    setConnState("connecting");
    setConnError("");
    intentionalUnregisterRef.current = false;
    const miGeneracion = ++generacionRef.current;
    const esVigente = () => generacionRef.current === miGeneracion;

    // Si quedó un intento anterior vivo (un reintento automático que se
    // dispara mientras el previo todavía no terminó de fallar), apagarlo
    // ANTES de crear uno nuevo. Sin esto, dos UserAgent quedan corriendo
    // a la vez y sus eventos se pisan entre sí.
    if (userAgentRef.current) {
      const viejo = userAgentRef.current;
      userAgentRef.current = null;
      registererRef.current = null;
      try {
        await viejo.stop();
      } catch {
        // el intento viejo ya estaba roto; no importa cómo termine
      }
    }

    try {
      const uri = UserAgent.makeURI(`sip:${ext.number}@${settings.fs_domain}`);
      if (!uri) throw new Error("Extensión o dominio SIP inválido");

      const options: UserAgentOptions = {
        uri,
        transportOptions: { server: resolverServidorSip(settings.sip_ws_url) },
        authorizationUsername: ext.number,
        authorizationPassword: ext.password,
        displayName: ext.caller_id_name || ext.number,
        logLevel: "error",
        sessionDescriptionHandlerFactoryOptions: {
          iceGatheringTimeout: 1500,
          peerConnectionConfiguration: {
            // Los manda el backend (ver app/services/turn.py): STUN
            // solo, o STUN + TURN si hay relay configurado. La lista
            // fija queda de respaldo por si el backend es viejo y no
            // trae el campo — sin ella el softphone se quedaría sin
            // ningún servidor ICE y fallaría en cualquier red con NAT.
            iceServers: settings.ice_servers?.length
              ? settings.ice_servers
              : [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }],
          },
        },
        delegate: {
          onInvite(invitation: Invitation) {
            bindSession(invitation, invitation.remoteIdentity.uri.user ?? "desconocido", true);
          },
          onDisconnect() {
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
            setConnError(
              "El registro fue rechazado por FreeSWITCH (usuario/password incorrectos o extensión no encontrada)"
            );
            programarReconexion();
          }
        }
      });
      await registerer.register();
    } catch (e) {
      if (!esVigente()) return;
      // eslint-disable-next-line no-console
      console.error("[softphone] connect() failed", e);
      setConnState("error");
      setConnError(e instanceof Error ? e.message : "Error al conectar");
      if (!intentionalUnregisterRef.current) programarReconexion();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entorno, bindSession]);

  const connectRef = useRef<() => void>(() => {});
  connectRef.current = connect;

  const programarReconexion = () => {
    if (reconnectTimerRef.current) return;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      if (!intentionalUnregisterRef.current) connectRef.current();
    }, 4000);
  };

  const hangup = useCallback(async () => {
    const session = sessionRef.current;
    if (!session) return;
    try {
      if (session.state === SessionState.Established) {
        await session.bye();
      } else if (session instanceof Inviter) {
        await session.cancel();
      } else if (session instanceof Invitation) {
        await session.reject();
      }
    } catch {
      // ignore
    }
  }, []);

  const disconnect = useCallback(async () => {
    intentionalUnregisterRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    try {
      await hangup();
      if (registererRef.current) await registererRef.current.unregister();
      if (userAgentRef.current) await userAgentRef.current.stop();
    } catch {
      // ignore
    } finally {
      registererRef.current = null;
      userAgentRef.current = null;
      setConnState("disconnected");
    }
  }, [hangup]);

  // Carga el entorno (extensión asignada) apenas hay sesión — antes vivía
  // en la página /softphone, así que solo se conocía si la persona pasaba
  // por ahí. Ahora la conexión SIP debe existir en TODA la app, no solo
  // en esa pantalla.
  useEffect(() => {
    if (cargandoAuth || !usuario || !puede(PERMISOS.softphone)) return;
    (async () => {
      try {
        setEntorno(await api.get<MiEntorno>("/api/auth/mi-entorno"));
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : "Error al cargar");
      }
    })();
  }, [cargandoAuth, usuario, puede]);

  // Se desconecta si la sesión termina (logout), y se limpia al desmontar
  // el provider (solo pasa al cerrar/recargar la pestaña, dado que vive en
  // el layout raíz).
  useEffect(() => {
    if (!usuario) {
      disconnect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usuario]);

  useEffect(() => {
    return () => {
      disconnect();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    };
  }, []);

  // No hay nada que elegir: la extensión es la del usuario que inició
  // sesión. Se registra sola apenas se conoce.
  const autoIntentadoRef = useRef(false);
  useEffect(() => {
    if (autoIntentadoRef.current || !entorno) return;
    autoIntentadoRef.current = true;
    if (entorno.extension?.enabled) connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entorno]);

  // El WebSocket de SIP se cae cuando el navegador suspende la pestaña
  // (cambio de app en móvil, pestaña en segundo plano, equipo en reposo) y
  // FreeSWITCH deja de ver la extensión registrada. Al volver el foco, si la
  // extensión quedó sin registrar, se reconecta sola: el agente sigue
  // disponible sin importar en qué pantalla esté ni cuánto tiempo estuvo
  // fuera.
  useEffect(() => {
    if (!usuario || !entorno?.extension?.enabled) return;
    const reasegurar = () => {
      if (document.visibilityState !== "visible") return;
      const reg = registererRef.current;
      if (!reg || reg.state !== RegistererState.Registered) {
        connectRef.current();
      }
    };
    document.addEventListener("visibilitychange", reasegurar);
    window.addEventListener("focus", reasegurar);
    return () => {
      document.removeEventListener("visibilitychange", reasegurar);
      window.removeEventListener("focus", reasegurar);
    };
  }, [usuario, entorno]);

  const activarDnd = useCallback(
    async (activar: boolean) => {
      if (!entorno?.extension) return;
      setDndCambiando(true);
      setDndError("");
      try {
        await api.post("/api/auth/dnd", { enabled: activar });
        setEntorno((e) => (e?.extension ? { ...e, extension: { ...e.extension, dnd: activar } } : e));
      } catch (e) {
        setDndError(e instanceof Error ? e.message : "No se pudo cambiar el estado");
      } finally {
        setDndCambiando(false);
      }
    },
    [entorno]
  );

  const call = useCallback(async () => {
    if (!userAgentRef.current || !entorno?.fs_domain || !destination) return;
    try {
      const target = UserAgent.makeURI(`sip:${destination}@${entorno.fs_domain}`);
      if (!target) throw new Error("Destino inválido");
      const inviter = new Inviter(userAgentRef.current, target, {
        sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } },
      });
      bindSession(inviter, destination, false);
      await inviter.invite();
    } catch (e) {
      setConnError(e instanceof Error ? e.message : "Error al llamar");
      setPhase("idle");
    }
  }, [entorno, destination, bindSession]);

  const answer = useCallback(async () => {
    const session = sessionRef.current;
    if (!session || !(session instanceof Invitation)) return;
    await session.accept({ sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } } });
  }, []);

  const reject = useCallback(async () => {
    const session = sessionRef.current;
    if (!session || !(session instanceof Invitation)) return;
    await session.reject();
  }, []);

  const toggleMute = useCallback(() => {
    const sdh = sessionRef.current?.sessionDescriptionHandler as unknown as SdhLike | undefined;
    const pc = sdh?.peerConnection;
    if (!pc) return;
    setMuted((prev) => {
      const next = !prev;
      pc.getSenders().forEach((sender) => {
        if (sender.track) sender.track.enabled = !next;
      });
      return next;
    });
  }, []);

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

  return (
    <Ctx.Provider
      value={{
        entorno,
        loadError,
        dndCambiando,
        dndError,
        connState,
        connError,
        destination,
        phase,
        remoteParty,
        muted,
        callSeconds,
        setDestination,
        setConnError,
        setDndError,
        connect,
        disconnect,
        activarDnd,
        call,
        answer,
        reject,
        hangup,
        toggleMute,
        sendDtmf,
      }}
    >
      {children}
      <audio ref={audioRef} autoPlay className="hidden" />
    </Ctx.Provider>
  );
}
