#!/usr/bin/env node
/**
 * Auditoría de dependencias de npm para el CI.
 *
 *   node scripts/auditar-npm.mjs frontend
 *   node scripts/auditar-npm.mjs mobile
 *
 * Corre `npm audit --omit=dev` en la carpeta y falla si aparece cualquier
 * vulnerabilidad (moderada o más) que no esté aceptada en
 * <carpeta>/audit-aceptadas.json. Cada excepción lleva el motivo y una
 * fecha de revisión: vencida, vuelve a fallar. Así una excepción no se
 * queda para siempre y una vulnerabilidad nueva no pasa en silencio.
 *
 * Formato de audit-aceptadas.json:
 *   { "GHSA-xxxx-xxxx-xxxx": { "paquete": "...", "motivo": "...", "revisar_antes": "AAAA-MM-DD" } }
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const carpeta = process.argv[2];
if (!carpeta) {
  console.error("Uso: node scripts/auditar-npm.mjs <carpeta>");
  process.exit(2);
}

const NIVELES = ["info", "low", "moderate", "high", "critical"];
const MINIMO = NIVELES.indexOf("moderate");

let salida;
try {
  salida = execFileSync("npm", ["audit", "--omit=dev", "--json"], { cwd: carpeta, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
} catch (e) {
  // npm audit sale con código != 0 cuando encuentra algo; el JSON igual viene.
  salida = e.stdout;
  if (!salida) {
    console.error(`npm audit no respondió en ${carpeta}: ${e.message}`);
    process.exit(2);
  }
}

const reporte = JSON.parse(salida);
if (reporte.error) {
  console.error(`npm audit falló en ${carpeta}: ${JSON.stringify(reporte.error)}`);
  process.exit(2);
}

const archivo = join(carpeta, "audit-aceptadas.json");
const aceptadas = existsSync(archivo) ? JSON.parse(readFileSync(archivo, "utf8")) : {};
const hoy = new Date().toISOString().slice(0, 10);

// Cada aviso aparece en el paquete vulnerable (via con objeto) y en todos los
// que dependen de él (via con texto): basta con mirar los primeros.
const avisos = new Map();
for (const [paquete, v] of Object.entries(reporte.vulnerabilities ?? {})) {
  for (const via of v.via) {
    if (typeof via !== "object") continue;
    const id = (via.url || "").split("/").pop() || String(via.source);
    if (!avisos.has(id)) avisos.set(id, { id, paquete, severidad: via.severity, titulo: via.title, url: via.url, rango: via.range });
  }
}

const fallas = [];
const usadas = new Set();
for (const a of avisos.values()) {
  if (NIVELES.indexOf(a.severidad) < MINIMO) continue;
  const ok = aceptadas[a.id];
  if (ok) {
    usadas.add(a.id);
    if (!ok.motivo || !ok.revisar_antes) fallas.push(`${a.id} (${a.paquete}): la excepción no tiene motivo o fecha de revisión`);
    else if (ok.revisar_antes < hoy) fallas.push(`${a.id} (${a.paquete}): la excepción venció el ${ok.revisar_antes}; revisar si ya hay arreglo`);
    else console.log(`aceptada  ${a.severidad.padEnd(8)} ${a.id} ${a.paquete} — ${ok.motivo} (hasta ${ok.revisar_antes})`);
    continue;
  }
  fallas.push(`${a.severidad.toUpperCase()} ${a.id} en ${a.paquete} ${a.rango}: ${a.titulo} ${a.url}`);
}
for (const id of Object.keys(aceptadas)) {
  if (!usadas.has(id)) console.log(`nota: ${id} ya no aparece; se puede quitar de ${archivo}`);
}

if (fallas.length) {
  console.error(`Dependencias vulnerables en ${carpeta}:\n  ` + fallas.join("\n  "));
  console.error("Actualiza la dependencia o, si no hay arreglo y el riesgo no aplica, acéptala con motivo y fecha en " + archivo);
  process.exit(1);
}
console.log(`${carpeta}: sin vulnerabilidades sin revisar.`);
