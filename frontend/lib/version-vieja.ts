// Tras actualizar el servidor, una pestaña abierta desde antes pide archivos
// del build anterior, que ya no existen: basta con recargar. Lo usan
// app/error.tsx y app/global-error.tsx.
const CLAVE_RECARGA = "nspbx-recarga-por-version";

export function esVersionVieja(error: Error): boolean {
  const texto = `${error.name} ${error.message}`;
  return /ChunkLoadError|Loading chunk|Loading CSS chunk|Failed to fetch dynamically imported module|Importing a module script failed/i.test(texto);
}

/** Recarga una vez por minuto como mucho (si el problema es otro, no queda en bucle). */
export function recargarPorVersion(): void {
  try {
    const ultima = Number(sessionStorage.getItem(CLAVE_RECARGA) || 0);
    if (Date.now() - ultima < 60_000) return;
    sessionStorage.setItem(CLAVE_RECARGA, String(Date.now()));
  } catch {
    return;
  }
  window.location.reload();
}
