"use client";

import { useEffect, useState } from "react";

import { Badge, Card, CardBody, CardHeader } from "@/components/ui";
import { api } from "@/lib/api";

interface Operacion {
  respaldo: { at: string | null; ok: boolean | null; error: string | null; archivo: string | null };
  externo: { hay: boolean; archivo: string | null; at: string | null; horas: number | null; al_dia: boolean };
  simulacro: { hay: boolean; ok: boolean | null; at: string | null; dias: number | null; detalle: string | null; al_dia: boolean };
  metricas: boolean;
}

const cuando = (iso: string | null, utc = false) =>
  iso ? new Date(utc ? `${iso}Z` : iso).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" }) : "nunca";

/**
 * Respaldos de la plataforma (services/operacion.py): el volcado diario del
 * backend, la copia externa cifrada (scripts/backup-offsite.sh) y el
 * simulacro de restauración (scripts/simulacro-restauracion.sh).
 */
export function OperacionPlataforma() {
  const [op, setOp] = useState<Operacion | null>(null);
  useEffect(() => {
    api.get<Operacion>("/api/plataforma/operacion").then(setOp, () => undefined);
  }, []);
  if (!op) return null;
  const { respaldo, externo, simulacro } = op;
  return (
    <Card className="mb-4">
      <CardHeader
        title="Respaldos"
        subtitle="Un respaldo que nunca se restauró no es un respaldo. Los dos últimos corren por cron en el servidor (docs/runbooks/recuperacion-total.md)."
      />
      <CardBody className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-60 text-fg-soft">Volcado diario de la base</span>
          {respaldo.ok === null ? <Badge color="gray">Sin datos</Badge> : respaldo.ok ? <Badge color="green" dot>Bien</Badge> : <Badge color="red" dot>Falló</Badge>}
          <span className="text-muted">
            {cuando(respaldo.at, true)}
            {respaldo.error ? ` · ${respaldo.error}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-60 text-fg-soft">Copia externa cifrada</span>
          {!externo.hay ? (
            <span className="text-warn-text">
              No hay ninguna: si se pierde el servidor, se pierden los respaldos. Programa scripts/backup-offsite.sh en el cron.
            </span>
          ) : (
            <>
              {externo.al_dia ? <Badge color="green" dot>Al día</Badge> : <Badge color="red" dot>Atrasada</Badge>}
              <span className="text-muted">
                {cuando(externo.at)} (hace {externo.horas} h) · {externo.archivo}
              </span>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-60 text-fg-soft">Simulacro de restauración</span>
          {!simulacro.hay ? (
            <span className="text-warn-text">Nunca se probó. Corre scripts/simulacro-restauracion.sh una vez al mes.</span>
          ) : (
            <>
              {simulacro.al_dia ? (
                <Badge color="green" dot>Bien</Badge>
              ) : simulacro.ok === false ? (
                <Badge color="red" dot>Falló</Badge>
              ) : (
                <Badge color="amber" dot>Hace más de un mes</Badge>
              )}
              <span className="text-muted">
                {cuando(simulacro.at)}
                {simulacro.dias != null ? ` (hace ${simulacro.dias} días)` : ""}
                {simulacro.detalle ? ` · ${simulacro.detalle}` : ""}
              </span>
            </>
          )}
        </div>
        <p className="text-xs text-muted">
          Métricas para Prometheus en <span className="font-mono">/metrics</span>:{" "}
          {op.metricas ? "activas (con METRICS_TOKEN)." : "apagadas; se activan con METRICS_TOKEN."}
        </p>
      </CardBody>
    </Card>
  );
}
