"use client";

import { useState } from "react";

import { AgentesCampana } from "@/components/agentes-campana";
import { CargarClientes } from "@/components/cargar-clientes";
import { DiagnosticoCampana } from "@/components/diagnostico-campana";
import { Button, Modal, Note } from "@/components/ui";
import { api } from "@/lib/api";
import { CampaignWithStats } from "@/lib/types";

/**
 * Lo que sigue a «Crear campaña», paso a paso: cargar los clientes desde un
 * Excel, elegir los agentes (si la campaña es con agentes) y revisar e
 * iniciar. Cada paso se puede saltar y hacer luego desde el detalle.
 */
export function AsistenteCampana({
  campana,
  onCerrar,
}: {
  campana: CampaignWithStats | null;
  /** `iniciada`: si se pulsó «Iniciar» al final. */
  onCerrar: (iniciada: boolean) => void;
}) {
  const conAgentes = !!campana?.metodo && campana.metodo !== "voizbot";
  const pasos = ["Clientes", ...(conAgentes ? ["Agentes"] : []), "Revisar e iniciar"];
  const [paso, setPaso] = useState(0);
  const [cargados, setCargados] = useState(0);
  const [iniciando, setIniciando] = useState(false);
  const [error, setError] = useState("");

  if (!campana) return null;
  const titulo = pasos[paso];
  const variables = Array.from(new Set(Array.from((campana.message_template ?? "").matchAll(/\{(\w+)\}/g), (m) => m[1])));

  const iniciar = async () => {
    setIniciando(true);
    setError("");
    try {
      await api.post(`/api/campaigns/${campana.id}/start`);
      onCerrar(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo iniciar");
    } finally {
      setIniciando(false);
    }
  };

  const ultimo = paso === pasos.length - 1;

  return (
    <Modal
      open
      onClose={() => onCerrar(false)}
      size="xl"
      title={`${campana.name}: ${titulo.toLowerCase()}`}
      subtitle={`Paso ${paso + 1} de ${pasos.length}. Puedes saltar cualquier paso y hacerlo después desde la campaña.`}
      footer={
        <>
          {paso > 0 && (
            <Button variant="secondary" onClick={() => setPaso(paso - 1)}>
              Atrás
            </Button>
          )}
          {!ultimo ? (
            <Button guia="asistente:siguiente" onClick={() => setPaso(paso + 1)}>
              {paso === 0 && !cargados ? "Saltar por ahora" : "Siguiente"}
            </Button>
          ) : (
            <>
              <Button variant="secondary" onClick={() => onCerrar(false)}>
                Dejarla lista sin iniciar
              </Button>
              {campana.metodo !== "manual" && (
                <Button guia="asistente:iniciar" variant="success" onClick={iniciar} loading={iniciando}>
                  Iniciar campaña
                </Button>
              )}
            </>
          )}
        </>
      }
    >
      <ol className="mb-4 flex flex-wrap gap-2 text-xs">
        {pasos.map((t, i) => (
          <li
            key={t}
            className={`rounded-full px-3 py-1 ${
              i === paso ? "bg-brand text-white" : i < paso ? "bg-ok-soft text-ok-text" : "bg-surface-2 text-muted"
            }`}
          >
            {i < paso ? "✓ " : `${i + 1}. `}
            {t}
          </li>
        ))}
      </ol>

      {titulo === "Clientes" && (
        <CargarClientes
          campaignId={campana.id}
          variablesMensaje={variables}
          onCargado={(r) => setCargados((n) => n + (r.campana?.added ?? 0))}
        />
      )}

      {titulo === "Agentes" && (
        <div>
          <p className="mb-3 text-sm text-fg-soft">
            Marca quiénes trabajan esta campaña (se guarda al marcar). Después, cada uno abre la Consola de agente y pulsa
            «Empezar a trabajar».
          </p>
          <AgentesCampana campaignId={campana.id} />
        </div>
      )}

      {titulo === "Revisar e iniciar" && (
        <div className="space-y-3">
          {error && <Note tone="warn">{error}</Note>}
          <DiagnosticoCampana campaignId={campana.id} version={`${paso}-${cargados}`} />
          <p className="text-xs text-muted">
            Lo que esté en rojo impide llamar. «Iniciar» se puede pulsar ya: en cuanto todo esté listo (por ejemplo, cuando
            los agentes entren), empieza a marcar sola.
          </p>
        </div>
      )}
    </Modal>
  );
}
