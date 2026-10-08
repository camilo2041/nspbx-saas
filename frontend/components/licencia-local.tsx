"use client";

import { useEffect, useState } from "react";

import { Badge, Card, CardHeader, Note } from "@/components/ui";
import { api } from "@/lib/api";

// La licencia de una instalación local (docs/plan-fase-k.md;
// backend/app/services/licencia_local.py). En la nube no se muestra nada.

export interface EstadoLicencia {
  modo: "nube" | "local";
  activada?: boolean;
  valida?: boolean;
  error?: string;
  empresa?: string;
  plan?: string;
  estado?: "active" | "trial" | "suspended";
  vence?: string | null;
  valida_hasta?: string;
  ultimo_contacto?: string;
  ultimo_error?: string | null;
  horas_sin_contacto?: number;
  version?: string;
  version_disponible?: string | null;
}

const CADA_MS = 10 * 60_000;
// Antes de esto, un corte de internet normal no merece un aviso a todos.
const HORAS_AVISO = 6;

function fecha(f?: string | null): string {
  return f ? new Date(f).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}

function useLicenciaLocal(): EstadoLicencia | null {
  const [estado, setEstado] = useState<EstadoLicencia | null>(null);
  useEffect(() => {
    let vivo = true;
    const cargar = () =>
      api
        .get<EstadoLicencia>("/api/instalacion/licencia")
        .then((e) => vivo && setEstado(e))
        .catch(() => {});
    cargar();
    const t = setInterval(cargar, CADA_MS);
    return () => {
      vivo = false;
      clearInterval(t);
    };
  }, []);
  return estado;
}

/** El problema de la licencia que todos deben ver, o null. */
function problema(e: EstadoLicencia): { tono: "warn" | "danger"; texto: string } | null {
  if (e.modo !== "local") return null;
  if (!e.activada) return { tono: "danger", texto: "Esta central no está activada: no puede operar. Vuelve a correr el instalador con un código de activación." };
  if (!e.valida) return { tono: "danger", texto: `La licencia de esta central no es válida (${e.error}). Contacta a tu proveedor.` };
  if (e.estado === "suspended")
    return { tono: "danger", texto: "La licencia de esta central está suspendida: las llamadas siguen, pero las campañas y los cambios están detenidos. Contacta a tu proveedor." };
  if ((e.horas_sin_contacto ?? 0) >= HORAS_AVISO)
    return {
      tono: "warn",
      texto: `Sin conexión con la central desde hace ${Math.round(e.horas_sin_contacto ?? 0)} h. Si sigue así hasta el ${fecha(e.valida_hasta)}, se detienen las campañas y los cambios (los teléfonos siguen). Revisa la conexión a internet del servidor.`,
    };
  if (e.vence) {
    const dias = (new Date(e.vence).getTime() - Date.now()) / 86_400_000;
    if (dias < 15) return { tono: "warn", texto: `La licencia vence el ${fecha(e.vence)}. Contacta a tu proveedor para renovarla.` };
  }
  return null;
}

/** Franja arriba del contenido, para todos los usuarios. */
export function AvisoLicenciaLocal() {
  const estado = useLicenciaLocal();
  const p = estado && problema(estado);
  if (!p) return null;
  return (
    <div
      role="status"
      className={`border-b px-4 py-2 text-center text-xs font-medium ${
        p.tono === "danger" ? "border-danger/25 bg-danger-soft text-danger-text" : "border-warn/25 bg-warn-soft text-warn-text"
      }`}
    >
      {p.texto}
    </div>
  );
}

const ESTADOS = { active: "Activa", trial: "De prueba", suspended: "Suspendida" };

/** Tarjeta de Ajustes con el detalle. */
export function TarjetaLicenciaLocal() {
  const e = useLicenciaLocal();
  if (!e || e.modo !== "local") return null;
  const p = problema(e);
  return (
    <Card className="mb-4">
      <CardHeader
        title="Licencia de esta central"
        subtitle="Llega firmada desde tu proveedor cada hora. El plan, los topes y los módulos se cambian allá, no aquí."
      />
      <div className="space-y-3 px-4 pb-4 text-sm">
        {p && <Note tone="warn">{p.texto}</Note>}
        {e.valida && (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Empresa</dt>
              <dd className="font-medium text-fg">{e.empresa}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Plan</dt>
              <dd className="flex items-center gap-2 font-medium text-fg">
                {e.plan}
                <Badge color={e.estado === "suspended" ? "red" : "green"} dot>
                  {ESTADOS[e.estado ?? "active"]}
                </Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Vence</dt>
              <dd className="text-fg">{e.vence ? fecha(e.vence) : "Sin vencimiento"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Último contacto con la central</dt>
              <dd className="text-fg">
                {fecha(e.ultimo_contacto)}
                {e.ultimo_error && <span className="block text-xs text-warn-text">Último intento: {e.ultimo_error}</span>}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Versión</dt>
              <dd className="text-fg">
                {e.version}
                {e.version_disponible && e.version_disponible !== e.version && (
                  <span className="block text-xs text-brand-text">
                    Hay una nueva ({e.version_disponible}): en el servidor, <span className="font-mono">sudo nspbx actualizar</span>
                  </span>
                )}
              </dd>
            </div>
          </dl>
        )}
      </div>
    </Card>
  );
}
