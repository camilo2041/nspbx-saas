"use client";

import { useEffect } from "react";

import { esVersionVieja, recargarPorVersion } from "@/lib/version-vieja";

// Lo que falla FUERA de una pantalla (el menú, el softphone flotante, el aviso
// de llamada entrante: viven en el layout raíz, que app/error.tsx no cubre).
// Reemplaza a todo el documento, así que lleva su propio <html> y estilos
// mínimos en línea (los del panel pueden no haber cargado).
export default function ErrorGlobal({ error }: { error: Error & { digest?: string } }) {
  const versionVieja = esVersionVieja(error);

  useEffect(() => {
    console.error(error);
    if (versionVieja) recargarPorVersion();
  }, [error, versionVieja]);

  return (
    <html lang="es">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#050b1f", color: "#eef3ff" }}>
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <div style={{ maxWidth: 440, width: "100%", textAlign: "center" }}>
            <h1 style={{ fontSize: 18, margin: "0 0 8px" }}>{versionVieja ? "El panel se actualizó" : "El panel tuvo un problema"}</h1>
            <p style={{ fontSize: 14, color: "#8f9cc6", margin: "0 0 16px" }}>
              {versionVieja ? "Hay una versión nueva. Recarga para seguir." : "No se perdió nada de lo guardado. Recarga la página; si se repite, avisa al administrador."}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{ padding: "8px 16px", borderRadius: 8, border: 0, backgroundImage: "linear-gradient(100deg, #1f5eff, #7b3fe4 55%, #ff8a00)", color: "#fff", fontSize: 14, cursor: "pointer" }}
            >
              Recargar la página
            </button>
            <details style={{ marginTop: 16, textAlign: "left", fontSize: 12, color: "#8f9cc6" }}>
              <summary style={{ cursor: "pointer" }}>Detalle técnico (para soporte)</summary>
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", background: "#081233", padding: 8, borderRadius: 8 }}>
                {`${error.name}: ${error.message}${error.digest ? `\nCódigo: ${error.digest}` : ""}\n${typeof window !== "undefined" ? window.location.pathname : ""}`}
              </pre>
            </details>
          </div>
        </div>
      </body>
    </html>
  );
}
