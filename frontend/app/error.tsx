"use client";

import { useEffect } from "react";

import { Button, Card } from "@/components/ui";
import { reportarError } from "@/lib/errores";
import { esVersionVieja, recargarPorVersion } from "@/lib/version-vieja";

// Si una pantalla falla, se muestra esto dentro del panel (con el menú) en
// vez de la página genérica de Next («This page couldn't load»). Si es una
// pestaña abierta desde antes de actualizar el servidor, recarga sola
// (lib/version-vieja.ts).
export default function ErrorDePantalla({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  const versionVieja = esVersionVieja(error);

  useEffect(() => {
    console.error(error);
    reportarError(error, "Pantalla");
    if (versionVieja) recargarPorVersion();
  }, [error, versionVieja]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-4">
      <Card className="w-full max-w-md p-6 text-center">
        <div className="mb-1 text-base font-semibold text-fg">
          {versionVieja ? "El panel se actualizó" : "Esta pantalla tuvo un problema"}
        </div>
        <p className="mb-4 text-sm text-fg-soft">
          {versionVieja
            ? "Hay una versión nueva. Recarga para seguir."
            : "No se perdió nada de lo guardado. Prueba de nuevo; si se repite, avisa al administrador con la hora en que pasó."}
        </p>
        <div className="flex justify-center gap-2">
          {!versionVieja && <Button onClick={() => retry()}>Reintentar</Button>}
          <Button variant={versionVieja ? "primary" : "secondary"} onClick={() => window.location.reload()}>
            Recargar la página
          </Button>
        </div>
        <details className="mt-4 text-left">
          <summary className="cursor-pointer text-xs text-muted">Detalle técnico (para soporte)</summary>
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-2 font-mono text-[11px] text-fg-soft">
            {`${error.name}: ${error.message}${error.digest ? `\nCódigo: ${error.digest}` : ""}\n${typeof window !== "undefined" ? window.location.pathname : ""}`}
          </pre>
        </details>
      </Card>
    </div>
  );
}
