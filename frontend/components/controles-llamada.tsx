"use client";

import { useEffect, useState } from "react";

import { Button, Note, fieldClass } from "@/components/ui";
import { api } from "@/lib/api";
import { DestinosTransferencia } from "@/lib/types";

const PREFIJO_BUZON = "*99";

/**
 * En espera y transferir la llamada en curso (backend:
 * services/transferencias.py). Sirve para el softphone y para la consola de
 * agente; en la consola el estado (en espera, consultando) viene del servidor
 * en `agente` y tras cada acción se pide recargar con `onCambio`.
 */
export function ControlesLlamada({
  agente,
  onCambio,
  onTransferida,
}: {
  agente?: { en_espera?: boolean; consulta_destino?: string | null } | null;
  onCambio?: () => void;
  /** La llamada ya no es tuya (se pasó a otro). */
  onTransferida?: () => void;
}) {
  const [enEsperaLocal, setEnEsperaLocal] = useState(false);
  const [consultaLocal, setConsultaLocal] = useState<string | null>(null);
  // Softphone: los tres en conferencia (en la consola lo sabe la sala del agente).
  const [tresLocal, setTresLocal] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const [destino, setDestino] = useState("");
  const [destinos, setDestinos] = useState<DestinosTransferencia | null>(null);
  const [trabajando, setTrabajando] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  const enEspera = agente ? !!agente.en_espera : enEsperaLocal;
  const consulta = agente ? agente.consulta_destino ?? null : consultaLocal;

  useEffect(() => {
    if (!abierto || destinos) return;
    api
      .get<DestinosTransferencia>("/api/llamada/destinos")
      .then(setDestinos)
      .catch(() => setDestinos({ extensiones: [], grupos: [] }));
  }, [abierto, destinos]);

  const pedir = async <T,>(nombre: string, ruta: string, cuerpo?: unknown): Promise<T | null> => {
    setTrabajando(nombre);
    setError("");
    setAviso("");
    try {
      const r = await api.post<T>(ruta, cuerpo);
      onCambio?.();
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo");
      onCambio?.();
      return null;
    } finally {
      setTrabajando("");
    }
  };

  const alternarEspera = async () => {
    const r = await pedir<{ en_espera: boolean }>("espera", "/api/llamada/espera", { activar: !enEspera });
    if (r) setEnEsperaLocal(r.en_espera);
  };

  const transferir = async (consultada: boolean, a = destino) => {
    const d = a.trim();
    if (!d) {
      setError("Elige a quién pasar la llamada");
      return;
    }
    const r = await pedir<{ estado: string; destino: string }>(consultada ? "consultar" : "pasar", "/api/llamada/transferir", {
      destino: d,
      consultada,
    });
    if (!r) return;
    setAbierto(false);
    setDestino("");
    if (r.estado === "consultando") {
      setConsultaLocal(d);
      setEnEsperaLocal(true);
    } else {
      setAviso(`Llamada pasada a ${nombre(d)}.`);
      onTransferida?.();
    }
  };

  const completar = async () => {
    const r = await pedir("completar", "/api/llamada/transferencia/completar");
    if (r) {
      setAviso(tresLocal ? "Saliste de la llamada: ellos siguen hablando." : `Llamada pasada a ${nombre(consulta ?? "")}.`);
      setConsultaLocal(null);
      setEnEsperaLocal(false);
      setTresLocal(false);
      onTransferida?.();
    }
  };

  const cancelar = async () => {
    const r = await pedir("cancelar", "/api/llamada/transferencia/cancelar");
    if (r) {
      setConsultaLocal(null);
      setEnEsperaLocal(false);
      setTresLocal(false);
    }
  };

  const hablarLosTres = async () => {
    const r = await pedir("tres", "/api/llamada/transferencia/conferencia");
    if (r && !agente) setTresLocal(true);
  };

  const nombre = (n: string): string => {
    if (n.startsWith(PREFIJO_BUZON)) return `el buzón de ${nombre(n.slice(PREFIJO_BUZON.length))}`;
    const ext = destinos?.extensiones.find((e) => e.numero === n);
    if (ext) return ext.nombre ? `${ext.nombre} (${n})` : `la ${n}`;
    const g = destinos?.grupos.find((x) => x.numero === n);
    return g ? `el grupo ${g.nombre}` : n;
  };

  if (consulta) {
    return (
      <div className="mt-3 space-y-2 rounded-xl border border-warn/30 bg-warn-soft p-3">
        <p className="text-sm text-warn-text">
          {tresLocal ? (
            <>
              Están hablando los tres: tú, el cliente y <b>{nombre(consulta)}</b>.
            </>
          ) : (
            <>
              Hablando con <b>{nombre(consulta)}</b>. El cliente está en espera con música.
            </>
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="success" onClick={completar} loading={trabajando === "completar"}>
            {tresLocal ? "Salir (que sigan ellos)" : "Pasarle la llamada"}
          </Button>
          <Button size="sm" variant="secondary" onClick={cancelar} loading={trabajando === "cancelar"}>
            {tresLocal ? `Sacar a ${nombre(consulta)}` : "Volver con el cliente"}
          </Button>
          {!tresLocal && (
            <Button size="sm" variant="ghost" onClick={hablarLosTres} loading={trabajando === "tres"}>
              Hablar los tres
            </Button>
          )}
        </div>
        {error && <p className="text-xs text-danger-text">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={alternarEspera} loading={trabajando === "espera"}>
          {enEspera ? "Retomar llamada" : "Poner en espera"}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setAbierto(!abierto)}>
          Transferir
        </Button>
      </div>
      {enEspera && <p className="text-xs text-muted">El cliente oye música mientras esperas.</p>}
      {abierto && (
        <div className="space-y-2 rounded-xl border border-line bg-surface-2 p-3">
          <label className="block text-xs font-medium text-fg-soft" htmlFor="transferir-a">
            ¿A quién se la pasas?
          </label>
          <input
            id="transferir-a"
            list="destinos-transferencia"
            value={destino}
            onChange={(e) => setDestino(e.target.value)}
            placeholder="Extensión, grupo o número"
            className={`${fieldClass} w-full px-3 py-2 font-mono text-sm`}
          />
          <datalist id="destinos-transferencia">
            {destinos?.extensiones.map((e) => (
              <option key={e.numero} value={e.numero}>
                {e.nombre || "Extensión"}
              </option>
            ))}
            {destinos?.grupos.map((g) => (
              <option key={g.numero} value={g.numero}>
                Grupo {g.nombre}
              </option>
            ))}
          </datalist>
          {!!destinos?.grupos.length && (
            <div className="flex flex-wrap gap-1.5">
              {destinos.grupos.map((g) => (
                <button
                  key={g.numero}
                  type="button"
                  onClick={() => setDestino(g.numero)}
                  className="rounded-full border border-line px-2.5 py-0.5 text-xs text-fg-soft hover:bg-surface-3"
                >
                  {g.nombre}
                </button>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => transferir(true)} loading={trabajando === "consultar"}>
              Hablar antes con esa persona
            </Button>
            <Button size="sm" variant="secondary" onClick={() => transferir(false)} loading={trabajando === "pasar"}>
              Pasarla ya
            </Button>
            {destinos?.extensiones.some((e) => e.numero === destino.trim() && e.buzon) && (
              <Button size="sm" variant="ghost" onClick={() => transferir(false, `${PREFIJO_BUZON}${destino.trim()}`)}>
                A su buzón de voz
              </Button>
            )}
          </div>
          <p className="text-xs text-muted">
            «Hablar antes»: el cliente espera con música mientras le explicas el caso; luego le pasas la llamada o vuelves con
            el cliente.
          </p>
        </div>
      )}
      {error && <Note tone="warn">{error}</Note>}
      {aviso && <Note tone="brand">{aviso}</Note>}
    </div>
  );
}
