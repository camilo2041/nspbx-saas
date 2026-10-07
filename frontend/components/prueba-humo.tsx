"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Input, Modal } from "@/components/ui";
import { api } from "@/lib/api";

interface Paso {
  clave: string;
  titulo: string;
  estado: "ok" | "fallo" | "aviso" | "omitido";
  detalle: string;
  ms: number;
}

interface Resultado {
  empresa: string;
  ok: boolean;
  segundos: number;
  pasos: Paso[];
}

const ESTADOS: Record<Paso["estado"], { texto: string; color: "green" | "red" | "amber" | "gray" }> = {
  ok: { texto: "Bien", color: "green" },
  fallo: { texto: "Falló", color: "red" },
  aviso: { texto: "Revisar", color: "amber" },
  omitido: { texto: "Omitido", color: "gray" },
};

/**
 * «Probar la central» de una empresa: llamadas de prueba dentro de su
 * FreeSWITCH (services/humo.py). Conviene correrla después de cada despliegue.
 */
export function PruebaHumo({ empresa, onCerrar }: { empresa: { id: number; name: string } | null; onCerrar: () => void }) {
  const [buzon, setBuzon] = useState("");
  const [grupo, setGrupo] = useState("");
  const [corriendo, setCorriendo] = useState(false);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (empresa) {
      setResultado(null);
      setError("");
    }
  }, [empresa]);

  const probar = async () => {
    if (!empresa) return;
    setCorriendo(true);
    setError("");
    setResultado(null);
    try {
      setResultado(
        await api.post<Resultado>("/api/plataforma/humo", {
          tenant_id: empresa.id,
          buzon: buzon.trim() || null,
          grupo: grupo.trim() || null,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo correr la prueba");
    } finally {
      setCorriendo(false);
    }
  };

  return (
    <Modal
      open={!!empresa}
      onClose={onCerrar}
      title={`Probar la central · ${empresa?.name ?? ""}`}
      subtitle="Llamadas de prueba dentro de la central, sin salir al proveedor. Tarda hasta 2 minutos."
      footer={
        <>
          <Button variant="secondary" onClick={onCerrar}>
            Cerrar
          </Button>
          <Button onClick={probar} loading={corriendo}>
            {resultado ? "Probar de nuevo" : "Probar"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label="Extensión para probar el buzón (opcional)"
            value={buzon}
            onChange={setBuzon}
            placeholder="101"
            hint="Deja un mensaje de prueba y lo borra. No manda correo."
          />
          <Input
            label="Grupo para probar la fila (opcional)"
            value={grupo}
            onChange={setGrupo}
            placeholder="8000"
            hint="Entra a la fila unos segundos: sus agentes pueden oír timbrar."
          />
        </div>
        {corriendo && <p className="text-sm text-muted">Probando… no cierres esta ventana.</p>}
        {error && <p className="text-sm text-danger-text">{error}</p>}
        {resultado && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge color={resultado.ok ? "green" : "red"} dot>
                {resultado.ok ? "Todo bien" : "Hay fallos"}
              </Badge>
              <span className="text-xs text-muted">{resultado.segundos} s</span>
            </div>
            <ul className="divide-y divide-line rounded-xl border border-line">
              {resultado.pasos.map((p) => (
                <li key={p.clave} className="flex items-start gap-3 p-3">
                  <Badge color={ESTADOS[p.estado].color}>{ESTADOS[p.estado].texto}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-fg">{p.titulo}</p>
                    <p className="text-xs text-muted">{p.detalle}</p>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted">
              Las transferencias y «hablar los tres» necesitan dos teléfonos de verdad: pruébalas a mano.
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}
