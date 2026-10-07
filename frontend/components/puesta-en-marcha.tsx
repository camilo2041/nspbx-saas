"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Card, ProgressBar } from "@/components/ui";
import { api } from "@/lib/api";

interface Paso {
  clave: string;
  titulo: string;
  hecho: boolean;
  detalle: string;
  enlace: string;
  accion: string;
  opcional: boolean;
}

interface Estado {
  pasos: Paso[];
  hechos: number;
  total: number;
  listo: boolean;
}

const CLAVE_OCULTA = "nspbx-puesta-en-marcha-oculta";

function leerOculta(): boolean {
  try {
    return localStorage.getItem(CLAVE_OCULTA) === "1";
  } catch {
    return false;
  }
}

/**
 * «Primeros pasos» del Inicio: qué falta para que la central funcione, en
 * orden y con lo que el sistema ve en vivo (backend/app/services/
 * puesta_en_marcha.py). Cuando lo obligatorio está hecho se puede ocultar.
 */
export function PuestaEnMarcha({ delay = 0 }: { delay?: number }) {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [oculta, setOculta] = useState(true);
  const [abierta, setAbierta] = useState(true);

  const cargar = useCallback(async () => {
    try {
      setEstado(await api.get<Estado>("/api/system/puesta-en-marcha"));
    } catch {
      setEstado(null);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- lee localStorage después de montar (no existe en el servidor)
    setOculta(leerOculta());
    cargar();
    const t = setInterval(cargar, 15000);
    return () => clearInterval(t);
  }, [cargar]);

  if (!estado || (estado.listo && oculta)) return null;

  const siguiente = estado.pasos.find((p) => !p.hecho && !p.opcional) ?? estado.pasos.find((p) => !p.hecho);
  const pct = Math.round((estado.hechos / Math.max(estado.total, 1)) * 100);

  const ocultar = () => {
    try {
      localStorage.setItem(CLAVE_OCULTA, "1");
    } catch {
      // sin almacenamiento: se oculta solo en esta visita
    }
    setOculta(true);
  };

  return (
    <Card delay={delay} className="mb-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-fg">
            {estado.listo ? "Tu central está lista" : "Pon en marcha tu central"}
          </h2>
          <p className="mt-0.5 text-sm text-fg-soft">
            {estado.listo
              ? "Lo esencial está hecho. Te quedan pasos opcionales para sacarle más provecho."
              : `Llevas ${estado.hechos} de ${estado.total} pasos. ${siguiente ? `Sigue: ${siguiente.titulo.toLowerCase()}.` : ""}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {!estado.listo && (
            <Link href="/configurar" className="rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white">
              Configuración guiada
            </Link>
          )}
          <button type="button" className="text-xs font-medium text-brand underline" onClick={() => setAbierta(!abierta)}>
            {abierta ? "Contraer" : "Ver pasos"}
          </button>
          {estado.listo && (
            <button type="button" className="text-xs text-muted underline" onClick={ocultar}>
              Ocultar
            </button>
          )}
        </div>
      </div>
      <ProgressBar value={pct} tone={estado.listo ? "ok" : "brand"} className="mt-3" />

      {abierta && (
        <ol className="mt-4 space-y-2">
          {estado.pasos.map((p, i) => {
            const esSiguiente = p.clave === siguiente?.clave;
            return (
              <li
                key={p.clave}
                className={`flex items-start gap-3 rounded-xl border p-3 ${
                  esSiguiente ? "border-brand bg-brand-soft" : "border-line"
                }`}
              >
                <span
                  aria-hidden
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    p.hecho ? "bg-ok text-white" : esSiguiente ? "bg-brand text-white" : "bg-surface-2 text-muted"
                  }`}
                >
                  {p.hecho ? "✓" : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-medium ${p.hecho ? "text-fg-soft" : "text-fg"}`}>
                    {p.titulo}
                    {p.opcional && <span className="ml-2 text-xs font-normal text-muted">opcional</span>}
                    <span className="sr-only">{p.hecho ? " (hecho)" : " (pendiente)"}</span>
                  </p>
                  <p className="mt-0.5 text-xs text-fg-soft">{p.detalle}</p>
                </div>
                {!p.hecho && p.enlace && (
                  <Link
                    href={p.enlace}
                    className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold ${
                      esSiguiente ? "bg-brand text-white" : "border border-line text-fg-soft hover:bg-surface-2"
                    }`}
                  >
                    {p.accion}
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
