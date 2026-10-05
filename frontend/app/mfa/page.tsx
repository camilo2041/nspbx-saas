"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, ErrorBanner, Input, Note, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Sesion } from "@/lib/types";
import { SesionesAbiertas } from "@/components/sesiones-abiertas";

interface Estado {
  activo: boolean;
  obligatorio: boolean;
  codigos_recuperacion_restantes: number;
}

/** Verificación en dos pasos (backend core/mfa.py). Si el rol la exige y
 *  falta activarla, el resto del panel redirige acá hasta hacerlo. */
export default function MfaPage() {
  const { aplicar, mfaPendiente } = useAuth();
  const [estado, setEstado] = useState<Estado | null>(null);
  const [alta, setAlta] = useState<{ secreto: string; uri: string } | null>(null);
  const [codigo, setCodigo] = useState("");
  const [codigos, setCodigos] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setEstado(await api.get<Estado>("/api/auth/mfa"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga inicial
    cargar();
  }, [cargar]);

  const accion = async (fn: () => Promise<void>) => {
    setTrabajando(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setTrabajando(false);
    }
  };

  const generar = () => accion(async () => setAlta(await api.post<{ secreto: string; uri: string }>("/api/auth/mfa/iniciar", {})));

  const activar = () =>
    accion(async () => {
      const r = await api.post<{ codigos_recuperacion: string[]; sesion: Sesion }>("/api/auth/mfa/activar", { codigo, plataforma: "web" });
      // Las demás sesiones se cerraron (se abrieron sin el segundo paso):
      // esta continúa con la sesión nueva que trae la respuesta.
      aplicar(r.sesion);
      setCodigos(r.codigos_recuperacion);
      setAlta(null);
      setCodigo("");
      await cargar();
    });

  const desactivar = () =>
    accion(async () => {
      await api.post("/api/auth/mfa/desactivar", { password, codigo });
      setPassword("");
      setCodigo("");
      await cargar();
    });

  // El secreto en grupos de 4: así se copia a mano sin perderse.
  const agrupado = alta?.secreto.match(/.{1,4}/g)?.join(" ") ?? "";

  return (
    <div className="max-w-2xl">
      <PageHeader
        title="Verificación en dos pasos"
        subtitle="Además de la contraseña, un código de 6 dígitos que genera una app en tu teléfono"
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {mfaPendiente && !codigos && (
        <div className="mb-4">
          <Note tone="warn">
            Tu rol administra la central (troncales, rutas, topes): necesita la verificación en dos pasos. Actívala
            para seguir usando el panel.
          </Note>
        </div>
      )}

      {codigos && (
        <Card className="mb-4">
          <CardHeader
            title="Códigos de recuperación"
            subtitle="Guárdalos fuera del teléfono. Cada uno sirve una sola vez si pierdes el teléfono. No se vuelven a mostrar."
          />
          <CardBody>
            <div className="grid grid-cols-2 gap-2 font-mono text-sm">
              {codigos.map((c) => (
                <div key={c} className="rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-center">
                  {c}
                </div>
              ))}
            </div>
            <Button className="mt-4" variant="secondary" onClick={() => setCodigos(null)}>
              Ya los guardé
            </Button>
          </CardBody>
        </Card>
      )}

      {estado && (
        <Card>
          <CardHeader
            title="Estado"
            subtitle={estado.obligatorio ? "Obligatoria para tu rol" : "Opcional para tu rol"}
            actions={
              <Badge color={estado.activo ? "green" : "amber"} dot>
                {estado.activo ? "Activa" : "Inactiva"}
              </Badge>
            }
          />
          <CardBody className="space-y-4">
            {estado.activo ? (
              <>
                <p className="text-sm text-fg-soft">
                  Te quedan {estado.codigos_recuperacion_restantes} códigos de recuperación. Si pierdes el teléfono y los
                  códigos, otro administrador puede restablecerla desde Usuarios.
                </p>
                {!estado.obligatorio && (
                  <div className="space-y-3 border-t border-line pt-4">
                    <div className="text-sm font-medium text-fg">Desactivar</div>
                    <Input label="Contraseña" type="password" value={password} onChange={setPassword} />
                    <Input label="Código de la app" value={codigo} onChange={setCodigo} mono />
                    <Button variant="danger" loading={trabajando} onClick={desactivar} disabled={!password || !codigo}>
                      Desactivar
                    </Button>
                  </div>
                )}
              </>
            ) : !alta ? (
              <>
                <p className="text-sm text-fg-soft">
                  Instala una app de autenticación (Google Authenticator, Microsoft Authenticator, 1Password, Authy…) y
                  genera el código para cargarla.
                </p>
                <Button loading={trabajando} onClick={generar}>
                  Generar código para la app
                </Button>
              </>
            ) : (
              <>
                <ol className="list-decimal space-y-2 pl-5 text-sm text-fg-soft">
                  <li>
                    En la app, elige agregar una cuenta e <b>ingresar la clave a mano</b> (o abre el enlace desde el
                    teléfono).
                  </li>
                  <li>Cuenta: NSPBX. Clave:</li>
                </ol>
                <div className="select-all rounded-lg border border-line bg-surface-2 px-3 py-2 text-center font-mono text-base tracking-wider text-fg">
                  {agrupado}
                </div>
                <a href={alta.uri} className="block text-xs text-brand-text underline underline-offset-2">
                  Abrir en la app de autenticación (desde el teléfono)
                </a>
                <Input label="Código de 6 dígitos que muestra la app" value={codigo} onChange={setCodigo} mono />
                <Button loading={trabajando} onClick={activar} disabled={codigo.trim().length < 6}>
                  Activar
                </Button>
              </>
            )}
          </CardBody>
        </Card>
      )}

      {!mfaPendiente && (
        <div className="mt-4">
          <SesionesAbiertas />
        </div>
      )}
    </div>
  );
}
