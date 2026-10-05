"use client";

import { FormEvent, useState } from "react";

import { Button, ErrorBanner, fieldClass } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { entrar, verificarMfa, cargando } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  // Token del segundo paso: la contraseña fue correcta y falta el código.
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [codigo, setCodigo] = useState("");

  const enviar = async (e: FormEvent) => {
    e.preventDefault();
    setEnviando(true);
    setError("");
    try {
      if (mfaToken) {
        await verificarMfa(mfaToken, codigo);
        return;
      }
      const pendiente = await entrar(username, password);
      if (pendiente) {
        setMfaToken(pendiente);
        setEnviando(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
      setEnviando(false);
    }
  };

  // Mientras se revalida el token guardado no se pinta el formulario: si
  // la sesión sigue viva, la persona vería un login que desaparece solo.
  if (cargando) return null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center bg-marca rounded-2xl text-xl font-bold text-white shadow-[var(--shadow-2)]">
            N
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold tracking-tight text-fg">NSPBX</h1>
            <p className="text-sm text-muted">Central telefónica</p>
          </div>
        </div>

        <form
          onSubmit={enviar}
          className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-6 shadow-[var(--shadow-2)]"
        >
          {error && <ErrorBanner message={error} onClose={() => setError("")} />}

          {mfaToken ? (
            <div>
              <label htmlFor="codigo" className="mb-1.5 block text-xs font-medium text-fg-soft">
                Código de verificación
              </label>
              <input
                id="codigo"
                value={codigo}
                onChange={(e) => setCodigo(e.target.value)}
                autoComplete="one-time-code"
                inputMode="text"
                autoFocus
                required
                className={fieldClass}
              />
              <p className="mt-1.5 text-[11px] leading-snug text-faint">
                Los 6 dígitos de tu app de autenticación, o uno de tus códigos de recuperación.
              </p>
            </div>
          ) : (
          <>
          <div>
            <label htmlFor="usuario" className="mb-1.5 block text-xs font-medium text-fg-soft">
              Usuario
            </label>
            <input
              id="usuario"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              className={fieldClass}
            />
          </div>

          <div>
            <label htmlFor="clave" className="mb-1.5 block text-xs font-medium text-fg-soft">
              Contraseña
            </label>
            <input
              id="clave"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className={fieldClass}
            />
          </div>
          </>
          )}

          <Button type="submit" loading={enviando} className="mt-1 w-full justify-center">
            {mfaToken ? "Verificar" : "Entrar"}
          </Button>
        </form>

        <p className="mt-5 text-center text-xs text-faint">
          ¿Olvidaste tu contraseña? Pídele a un administrador que te la restablezca.
        </p>
      </div>
    </div>
  );
}
