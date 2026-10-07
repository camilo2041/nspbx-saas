"use client";

import { useRef, useState } from "react";

import { Button, ErrorBanner, Note, fieldClass } from "@/components/ui";
import { api } from "@/lib/api";
import { ReporteImportacion, VistaPreviaImportacion } from "@/lib/types";

const FIJOS = [
  { value: "telefono", label: "Teléfono (obligatorio)" },
  { value: "nombre", label: "Nombre del cliente" },
  { value: "documento", label: "Documento / cédula" },
  { value: "telefono2", label: "Otro teléfono" },
  { value: "email", label: "Correo" },
  { value: "ciudad", label: "Ciudad" },
];

/** «Fecha cita» → fecha_cita: el nombre con el que el dato llega al mensaje o al guion. */
function variableDe(columna: string) {
  const base = columna
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return /^[a-z]/.test(base) ? base.slice(0, 40) : `col_${base}`.slice(0, 40);
}

/**
 * Cargar los clientes de una campaña desde un Excel (.xlsx) o CSV: se sube,
 * se ve una vista previa con cada columna ya reconocida (teléfono, nombre…;
 * el resto pasa como dato para el mensaje o el guion) y se confirma. Usa la
 * misma importación del CRM (POST /api/crm/importar con campaign_id): los
 * clientes quedan también en Contactos y entran a la campaña como una lista.
 */
export function CargarClientes({
  campaignId,
  variablesMensaje = [],
  onCargado,
}: {
  campaignId: number;
  /** {variables} que usa el mensaje de apertura de la campaña. */
  variablesMensaje?: string[];
  onCargado?: (r: ReporteImportacion) => void;
}) {
  const archivoRef = useRef<HTMLInputElement>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [vista, setVista] = useState<VistaPreviaImportacion | null>(null);
  const [mapeo, setMapeo] = useState<Record<string, string>>({});
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState("");
  const [reporte, setReporte] = useState<ReporteImportacion | null>(null);

  const elegir = async (f: File) => {
    setArchivo(f);
    setReporte(null);
    setError("");
    setTrabajando(true);
    try {
      const datos = new FormData();
      datos.append("archivo", f);
      const v = await api.form<VistaPreviaImportacion>("/api/crm/importar/vista-previa", datos);
      // Lo que no se reconoce como teléfono, nombre, etc. pasa como dato
      // para el mensaje o el guion (antes se perdía si no se elegía a mano).
      const inicial: Record<string, string> = {};
      const usados = new Set(Object.values(v.sugerido));
      for (const col of v.columnas) {
        if (!col.trim()) continue;
        // Si el mensaje de la campaña usa esa columna ({cliente}, {monto}…),
        // va al mensaje aunque también parezca un dato del contacto.
        if (variablesMensaje.includes(variableDe(col)) && !usados.has(`var:${variableDe(col)}`)) {
          inicial[col] = `var:${variableDe(col)}`;
          usados.add(inicial[col]);
        } else if (v.sugerido[col]) inicial[col] = v.sugerido[col];
        else {
          const nombre = variableDe(col);
          const destino = `var:${nombre}`;
          if (!usados.has(destino)) {
            inicial[col] = destino;
            usados.add(destino);
          }
        }
      }
      setVista(v);
      setMapeo(inicial);
    } catch (e) {
      setVista(null);
      setError(e instanceof Error ? e.message : "No se pudo leer el archivo");
    } finally {
      setTrabajando(false);
    }
  };

  const cargar = async () => {
    if (!archivo) return;
    setTrabajando(true);
    setError("");
    try {
      const datos = new FormData();
      datos.append("archivo", archivo);
      datos.append("mapeo", JSON.stringify(mapeo));
      datos.append("campaign_id", String(campaignId));
      datos.append("nombre_lista", archivo.name.replace(/\.[^.]+$/, "").slice(0, 120));
      const r = await api.form<ReporteImportacion>("/api/crm/importar", datos);
      setReporte(r);
      onCargado?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar");
    } finally {
      setTrabajando(false);
    }
  };

  const destinos = (col: string) => [
    { value: "", label: "— No usar —" },
    ...FIJOS,
    ...variablesMensaje.map((v) => ({ value: `var:${v}`, label: `Para el mensaje: {${v}}` })),
    ...(variablesMensaje.includes(variableDe(col))
      ? []
      : [{ value: `var:${variableDe(col)}`, label: `Dato para el mensaje o el guion: {${variableDe(col)}}` }]),
  ];
  const usados = new Set(Object.values(mapeo).filter(Boolean));

  return (
    <div className="space-y-3">
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}

      {!vista && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-line-strong px-6 py-8 text-center">
          <p className="text-sm text-fg-soft">
            Sube tu base de clientes en <b>Excel (.xlsx)</b> o CSV, con los nombres de las columnas en la primera fila. Antes de
            cargar verás qué entendimos de cada columna.
          </p>
          <Button guia="clientes:elegir-archivo" onClick={() => archivoRef.current?.click()} loading={trabajando}>
            Elegir archivo
          </Button>
          <input
            ref={archivoRef}
            type="file"
            accept=".xlsx,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) elegir(f);
              e.target.value = "";
            }}
          />
          <p className="text-xs text-muted">Hasta 50.000 filas. Si tu Excel tiene varias hojas, se lee la primera.</p>
        </div>
      )}

      {vista && !reporte && (
        <>
          <p className="text-sm text-fg-soft">
            <b>{archivo?.name}</b>: {vista.total_filas} cliente(s). Revisa qué es cada columna:
          </p>
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2">Columna</th>
                  <th className="px-3 py-2">Ejemplos</th>
                  <th className="px-3 py-2">Es…</th>
                </tr>
              </thead>
              <tbody>
                {vista.columnas.map((col, i) => (
                  <tr key={col + i} className="border-t border-line">
                    <td className="px-3 py-2 font-medium text-fg">{col || <span className="text-faint">(sin nombre)</span>}</td>
                    <td className="px-3 py-2">
                      <span className="block max-w-[14rem] truncate font-mono text-xs text-fg-soft">
                        {vista.filas.map((f) => f[i]).filter(Boolean).slice(0, 2).join(" · ") || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        aria-label={`Qué es la columna ${col}`}
                        className={`${fieldClass} w-full min-w-[12rem] px-2 py-1.5 text-xs`}
                        value={mapeo[col] ?? ""}
                        onChange={(e) => setMapeo({ ...mapeo, [col]: e.target.value })}
                      >
                        {destinos(col).map((d) => (
                          <option key={d.value} value={d.value} disabled={!!d.value && usados.has(d.value) && mapeo[col] !== d.value}>
                            {d.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!usados.has("telefono") && <Note tone="warn">Indica cuál columna es el teléfono.</Note>}
          <div className="flex flex-wrap gap-2">
            <Button guia="clientes:cargar" onClick={cargar} loading={trabajando} disabled={!usados.has("telefono")}>
              Cargar {vista.total_filas} cliente(s)
            </Button>
            <Button variant="secondary" onClick={() => setVista(null)}>
              Otro archivo
            </Button>
          </div>
        </>
      )}

      {reporte && (
        <div className="space-y-2">
          <Note tone={reporte.con_error ? "warn" : "brand"}>
            {reporte.campana ? `${reporte.campana.added} cliente(s) cargado(s) en la campaña` : "Clientes guardados"}
            {reporte.campana && reporte.campana.updated > 0 && `, ${reporte.campana.updated} ya estaban`}
            {reporte.con_error > 0 && `. ${reporte.con_error} fila(s) no entraron (abajo el motivo)`}
            {(reporte.campana?.bloqueados?.length ?? 0) > 0 &&
              `. ${reporte.campana!.bloqueados!.length} número(s) no se pueden marcar por las reglas de salida`}
            .
          </Note>
          {reporte.errores.length > 0 && (
            <div className="max-h-40 overflow-y-auto rounded-xl border border-line">
              {reporte.errores.map((e) => (
                <div key={e.fila} className="border-b border-line/60 px-3 py-1.5 text-xs last:border-0">
                  <span className="font-mono text-faint">Fila {e.fila}</span> <span className="text-danger-text">{e.motivo}</span>
                </div>
              ))}
            </div>
          )}
          <Button variant="secondary" size="sm" onClick={() => { setVista(null); setReporte(null); }}>
            Cargar otro archivo
          </Button>
        </div>
      )}
    </div>
  );
}
