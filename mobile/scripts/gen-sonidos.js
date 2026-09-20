// Genera los tonos de la app (WAV mono 16 bit): timbre de llamada entrante.
// node scripts/gen-sonidos.js
const fs = require("fs");
const path = require("path");
const RATE = 22050;

function wav(muestras) {
  const datos = Buffer.alloc(muestras.length * 2);
  muestras.forEach((m, i) => datos.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(m * 32767))), i * 2));
  const cab = Buffer.alloc(44);
  cab.write("RIFF", 0);
  cab.writeUInt32LE(36 + datos.length, 4);
  cab.write("WAVEfmt ", 8);
  cab.writeUInt32LE(16, 16);
  cab.writeUInt16LE(1, 20);
  cab.writeUInt16LE(1, 22);
  cab.writeUInt32LE(RATE, 24);
  cab.writeUInt32LE(RATE * 2, 28);
  cab.writeUInt16LE(2, 32);
  cab.writeUInt16LE(16, 34);
  cab.write("data", 36);
  cab.writeUInt32LE(datos.length, 40);
  return Buffer.concat([cab, datos]);
}

// Tono de dos frecuencias con subida y bajada suaves (sin "clics").
function tono(seg, f1, f2, vol = 0.5) {
  const n = Math.floor(seg * RATE);
  const salida = new Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    const env = Math.min(1, t / 0.015, (seg - t) / 0.03);
    salida[i] = vol * env * 0.5 * (Math.sin(2 * Math.PI * f1 * t) + Math.sin(2 * Math.PI * f2 * t));
  }
  return salida;
}
const silencio = (seg) => new Array(Math.floor(seg * RATE)).fill(0);

// Timbre: dos toques "ring-ring" y una pausa larga (3,4 s en total; se repite en bucle).
const timbre = [...tono(0.4, 440, 480), ...silencio(0.2), ...tono(0.4, 440, 480), ...silencio(2.4)];
fs.writeFileSync(path.join(__dirname, "..", "assets", "sounds", "ring.wav"), wav(timbre));
console.log("ring.wav", timbre.length / RATE, "s");
