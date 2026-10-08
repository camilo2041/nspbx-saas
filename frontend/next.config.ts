import type { NextConfig } from "next";

// Cabeceras de seguridad del panel (ver docs/seguridad-y-robustez.md §5.4).
//
// La política de contenido (CSP) va en dos partes a propósito:
//
// - Lo que se APLICA es lo que no puede romper nada: que el panel no se
//   pueda meter en un iframe ajeno (clickjacking), ni cargar plugins, ni
//   cambiar la URL base de los enlaces.
// - La política completa (de dónde se cargan scripts, a dónde se conecta)
//   va en modo "solo reporte": el navegador avisa en la consola qué
//   bloquearía, sin bloquearlo. El softphone conecta por WSS a FreeSWITCH
//   y al relay TURN, que dependen de cada instalación; aplicarla sin haber
//   mirado esos avisos en producción podía dejar el softphone mudo.
//   Los avisos llegan al backend (/api/csp-report) y la plataforma los ve
//   en Empresas. Cuando esa lista quede vacía, se aplica poniendo
//   CSP_APLICADA=1 en el .env y reconstruyendo el panel
//   (docker compose up -d --build frontend). Se lee al compilar.

const POLITICA_COMPLETA = [
  "default-src 'self'",
  // Next inyecta scripts en línea para hidratar la página.
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob: data:",
  // API (puede estar en otro host), WebSocket del softphone y de los logs.
  "connect-src 'self' https: wss:",
  "worker-src 'self' blob:",
  "frame-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  // A dónde mandan los avisos los navegadores. Solo report-uri: con
  // report-to presente, Chrome pasa a la Reporting API, que agrupa y demora
  // los envíos; report-uri llega al instante (probado con Chromium).
  "report-uri /api/csp-report",
].join("; ");

const CSP_APLICADA = process.env.CSP_APLICADA === "1";

const comunes = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // El micrófono lo usa el softphone; nada más del dispositivo.
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)" },
  // Solo tiene efecto por HTTPS (Traefik); por HTTP el navegador lo ignora.
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: CSP_APLICADA ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only", value: POLITICA_COMPLETA },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        // Todo menos el widget de llamada web.
        source: "/((?!webcall$).*)",
        headers: [
          ...comunes,
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
        ],
      },
      {
        // /webcall se muestra en un iframe dentro de los sitios de los
        // clientes (ver public/webcall.js): ahí sí se permite enmarcar.
        source: "/webcall",
        headers: [
          ...comunes,
          { key: "Content-Security-Policy", value: "frame-ancestors *; object-src 'none'; base-uri 'self'" },
        ],
      },
    ];
  },
};

export default nextConfig;
