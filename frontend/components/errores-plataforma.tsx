"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { api } from "@/lib/api";

interface ErrorAgrupado {
  id: number;
  origen: "panel" | "app";
  mensaje: string;
  pila: string | null;
  ruta: string | null;
  version: string | null;
  empresa: string | null;
  veces: number;
  usuarios: number;
  primera_vez: string;
  ultima_vez: string;
}

const cuando = (iso: string) => new Date(`${iso}Z`).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });

/**
 * Errores del panel y de la app (services/errores_cliente.py), agrupados:
 * cuántas veces, a cuántos usuarios, dónde y desde cuándo. «Arreglado» lo
 * saca de la lista; si vuelve a pasar, reaparece.
 */
export function ErroresPlataforma() {
  const [errores, setErrores] = useState<ErrorAgrupado[] | null>(null);
  const [abierto, setAbierto] = useState<number | null>(null);

  const cargar = useCallback(() => {
    api.get<ErrorAgrupado[]>("/api/plataforma/errores").then(setErrores, () => setErrores(null));
  }, []);
  useEffect(() => {
    cargar();
  }, [cargar]);

  if (!errores) return null;
  return (
    <Card className="mb-4">
      <CardHeader
        title="Errores del panel y la app"
        subtitle={
          errores.length
            ? `${errores.length} sin resolver. Lo que falla en el navegador o el teléfono de alguien, sin que tenga que avisar.`
            : "Ninguno sin resolver. Aquí aparece lo que falle en el navegador o el teléfono de alguien."
        }
      />
      {errores.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {errores.map((e) => (
            <li key={e.id} className="px-5 py-3">
              <div className="flex flex-wrap items-start gap-2">
                <Badge color={e.origen === "app" ? "violet" : "blue"}>{e.origen === "app" ? "App" : "Panel"}</Badge>
                <button type="button" onClick={() => setAbierto(abierto === e.id ? null : e.id)} className="min-w-0 flex-1 text-left">
                  <span className="block break-words font-mono text-[13px] text-fg">{e.mensaje}</span>
                  <span className="text-xs text-muted">
                    {e.veces} {e.veces === 1 ? "vez" : "veces"} · {e.usuarios} {e.usuarios === 1 ? "usuario" : "usuarios"}
                    {e.empresa ? ` · ${e.empresa}` : ""}
                    {e.ruta ? ` · ${e.ruta}` : ""} · última {cuando(e.ultima_vez)}
                  </span>
                </button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    await api.put(`/api/plataforma/errores/${e.id}/resuelto`, {}).catch(() => undefined);
                    setErrores((xs) => (xs ?? []).filter((x) => x.id !== e.id));
                  }}
                >
                  Arreglado
                </Button>
              </div>
              {abierto === e.id && (
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-2 font-mono text-[11px] text-fg-soft">
                  {`Desde ${cuando(e.primera_vez)}${e.version ? ` · versión ${e.version}` : ""}\n${e.pila ?? "(sin pila)"}`}
                </pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
