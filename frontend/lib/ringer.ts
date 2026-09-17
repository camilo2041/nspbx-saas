/**
 * Timbre sintetizado con Web Audio API en vez de un archivo de sonido: no
 * hace falta ningún asset ni licencia, y el navegador ya nos obliga a
 * "desbloquear" el audio con un gesto del usuario de todas formas — con un
 * <audio src> pasaría lo mismo.
 *
 * Vive acá (y no dentro de softphone-context.tsx) porque lo usan dos
 * clientes SIP distintos: el softphone del panel y el widget de llamada
 * web (lib/webcall-phone.ts).
 */
export class Ringer {
  private ctx: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private ringbackTimer: ReturnType<typeof setInterval> | null = null;

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

  // Ringback de llamada saliente: mismos 440/480 Hz del timbre de entrada
  // pero con el patrón largo de "está llamando" (2s de tono, 4s de
  // silencio — el ca-ring de FreeSWITCH). Se corta apenas llega audio
  // real del otro lado (early media del proveedor o que contesten).
  ringbackOn() {
    if (!this.ctx) this.unlock();
    if (!this.ctx || this.ringbackTimer) return;
    if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    this.tono(this.ctx.currentTime, 2.0);
    this.ringbackTimer = setInterval(() => {
      if (this.ctx) this.tono(this.ctx.currentTime, 2.0);
    }, 6000);
  }

  ringbackOff() {
    if (this.ringbackTimer) {
      clearInterval(this.ringbackTimer);
      this.ringbackTimer = null;
    }
  }
}
