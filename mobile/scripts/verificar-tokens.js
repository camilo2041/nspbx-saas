#!/usr/bin/env node
/**
 * La app y el panel web tienen que verse como un solo producto: este chequeo
 * compara los colores de src/tokens.json con las variables de
 * frontend/app/globals.css (:root y .dark) y falla si alguno difiere.
 *
 *   node mobile/scripts/verificar-tokens.js
 */
const fs = require("fs");
const path = require("path");

const tokens = require("../src/tokens.json");
const css = fs.readFileSync(path.join(__dirname, "../../frontend/app/globals.css"), "utf8");

function bloque(selector) {
  const i = css.indexOf(`${selector} {`);
  if (i < 0) throw new Error(`No encontré ${selector} en globals.css`);
  const cuerpo = css.slice(i, css.indexOf("}", i));
  const vars = {};
  for (const m of cuerpo.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) vars[m[1]] = m[2].trim();
  return vars;
}

/** "#FFF", "rgb(1 2 3 / 0.5)" y "rgba(1,2,3,0.5)" a una forma comparable. */
function normal(color) {
  let c = color.toLowerCase().replace(/\s+/g, " ").trim();
  const rgb = c.match(/^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*(?:[/,]\s*([\d.]+))?\s*\)$/);
  if (rgb) return `rgba(${rgb[1]},${rgb[2]},${rgb[3]},${rgb[4] === undefined ? 1 : Number(rgb[4])})`;
  if (/^#[0-9a-f]{3}$/.test(c)) c = "#" + [...c.slice(1)].map((x) => x + x).join("");
  return c;
}

const fallas = [];
for (const [tema, selector] of [["claro", ":root"], ["oscuro", ".dark"]]) {
  const vars = bloque(selector);
  for (const [clave, variable] of Object.entries(tokens.css)) {
    const web = vars[variable];
    const app = tokens[tema][clave];
    if (web === undefined) fallas.push(`${tema}: ${variable} no está en globals.css (${selector})`);
    else if (app === undefined) fallas.push(`${tema}: falta "${clave}" en tokens.json`);
    else if (normal(web) !== normal(app)) fallas.push(`${tema}: ${clave} = ${app} en la app, ${variable} = ${web} en la web`);
  }
}

if (fallas.length) {
  console.error("La app y el panel web no tienen los mismos colores:\n  " + fallas.join("\n  "));
  process.exit(1);
}
console.log(`Colores de la app y del panel alineados (${Object.keys(tokens.css).length} por tema).`);
