"use client";

import { useEffect, useRef, useState } from "react";

import { Button, Card, CardBody, CardHeader, ErrorBanner, Input, Note, Select, Table, Td, Tr, fieldClass } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CampoContacto, Campaign, PERMISOS, ReporteImportacion, VistaPreviaImportacion } from "@/lib/types";

const FIJOS = [
  { value: "nombre", label: "Nombre" },
  { value: "documento", label: "Documento" },
  { value: "telefono", label: "Teléfono principal" },
  { value: "telefono2", label: "Teléfono 2" },
  { value: "telefono3", label: "Teléfono 3" },
  { value: "email", label: "Correo" },
  { value: "direccion", label: "Dirección" },
  { value: "ciudad", label: "Ciudad" },
];

/** Nombre de variable para una columna: «Fecha cita» → fecha_cita. */
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
 * Importar contactos desde un CSV: vista previa con un mapeo sugerido,
 * el usuario ajusta qué columna va a qué campo y, si quiere, los carga en
 * una campaña como una lista nueva. El reporte dice qué filas no entraron.
 */
export function ImportarCsv({ campos, onImportado }: { campos: CampoContacto[]; onImportado: () => void }) {
  const { puede, tieneModulo } = useAuth();
  const cargaCampanas = puede(PERMISOS.campanas) && tieneModulo("voicebot");
  const archivoRef = useRef<HTMLInputElement>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [vista, setVista] = useState<VistaPreviaImportacion | null>(null);
  const [mapeo, setMapeo] = useState<Record<string, string>>({});
  const [campanas, setCampanas] = useState<Campaign[]>([]);
  const [campana, setCampana] = useState("");
  const [nombreLista, setNombreLista] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState("");
  const [reporte, setReporte] = useState<ReporteImportacion | null>(null);

  useEffect(() => {
    if (!cargaCampanas) return;
    api
      .get<Campaign[]>("/api/campaigns")
      .then(setCampanas)
      .catch(() => setCampanas([]));
  }, [cargaCampanas]);

  const elegir = async (f: File) => {
    setArchivo(f);
    setReporte(null);
    setError("");
    setTrabajando(true);
    try {
      const datos = new FormData();
      datos.append("archivo", f);
      const v = await api.form<VistaPreviaImportacion>("/api/crm/importar/vista-previa", datos);
      setVista(v);
      setMapeo(v.sugerido);
      setNombreLista(f.name.replace(/\.[^.]+$/, ""));
    } catch (e) {
      setVista(null);
      setError(e instanceof Error ? e.message : "No se pudo leer el archivo");
    } finally {
      setTrabajando(false);
    }
  };

  const importar = async () => {
    if (!archivo) return;
    setTrabajando(true);
    setError("");
    try {
      const datos = new FormData();
      datos.append("archivo", archivo);
      datos.append("mapeo", JSON.stringify(mapeo));
      if (campana) {
        datos.append("campaign_id", campana);
        if (nombreLista.trim()) datos.append("nombre_lista", nombreLista.trim());
      }
      setReporte(await api.form<ReporteImportacion>("/api/crm/importar", datos));
      onImportado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo importar");
    } finally {
      setTrabajando(false);
    }
  };

  const reiniciar = () => {
    setArchivo(null);
    setVista(null);
    setMapeo({});
    setReporte(null);
    setCampana("");
  };

  const destinos = (col: string) => [
    { value: "", label: "— No importar —" },
    ...FIJOS,
    ...campos.map((c) => ({ value: `campo:${c.clave}`, label: `Campo: ${c.nombre}` })),
    ...(campana ? [{ value: `var:${variableDe(col)}`, label: `Variable de campaña {${variableDe(col)}}` }] : []),
  ];
  const usados = new Set(Object.values(mapeo).filter(Boolean));
  const tieneTelefono = usados.has("telefono");

  return (
    <Card>
      <CardHeader
        title="Importar contactos"
        subtitle="Excel (.xlsx) o CSV, con los nombres de las columnas en la primera fila; hasta 50.000 filas."
        actions={
          vista ? (
            <Button size="sm" variant="secondary" onClick={reiniciar}>
              Otro archivo
            </Button>
          ) : undefined
        }
      />
      <CardBody>
        {error && (
          <div className="mb-4">
            <ErrorBanner message={error} onClose={() => setError("")} />
          </div>
        )}

        {!vista && (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-line-strong px-6 py-10 text-center">
            <p className="text-sm text-fg-soft">Elige el archivo. Primero verás una vista previa: no se guarda nada hasta confirmar.</p>
            <Button guia="crm:elegir-archivo" onClick={() => archivoRef.current?.click()} loading={trabajando}>
              Elegir archivo (Excel o CSV)
            </Button>
            <input
              ref={archivoRef}
              type="file"
              accept=".xlsx,.csv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) elegir(f);
                e.target.value = "";
              }}
            />
          </div>
        )}

        {vista && !reporte && (
          <>
            <p className="mb-3 text-xs text-muted">
              {archivo?.name} · {vista.total_filas} fila(s). Indica qué es cada columna; el teléfono es obligatorio. Un
              contacto que ya existe (mismo documento o mismo teléfono) se actualiza con los valores no vacíos.
            </p>
            <Table head={["Columna del archivo", "Ejemplos", "Va a"]}>
              {vista.columnas.map((col, i) => (
                <Tr key={col + i}>
                  <Td strong>{col || <span className="text-faint">(sin nombre)</span>}</Td>
                  <Td muted>
                    <span className="block max-w-xs truncate font-mono text-xs">
                      {vista.filas.map((f) => f[i]).filter(Boolean).slice(0, 3).join(" · ") || "—"}
                    </span>
                  </Td>
                  <Td>
                    <select
                      className={`${fieldClass} w-64 px-2 py-1.5 text-xs`}
                      value={mapeo[col] ?? ""}
                      onChange={(e) => setMapeo({ ...mapeo, [col]: e.target.value })}
                    >
                      {destinos(col).map((d) => (
                        <option key={d.value} value={d.value} disabled={!!d.value && usados.has(d.value) && mapeo[col] !== d.value}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                  </Td>
                </Tr>
              ))}
            </Table>

            {cargaCampanas && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <Select
                  label="Cargar también en una campaña (opcional)"
                  value={campana}
                  onChange={setCampana}
                  placeholder="Solo al CRM"
                  options={campanas.map((c) => ({ value: String(c.id), label: c.name }))}
                  hint="Entran como una lista nueva que puedes pausar o priorizar. Las columnas marcadas como variable llegan al mensaje del voizbot."
                />
                {campana && <Input label="Nombre de la lista" value={nombreLista} onChange={setNombreLista} />}
              </div>
            )}

            <div className="mt-4 flex items-center gap-2">
              <Button guia="crm:importar-ya" onClick={importar} loading={trabajando} disabled={!tieneTelefono}>
                Importar {vista.total_filas} fila(s)
              </Button>
              {!tieneTelefono && <span className="text-xs text-warn-text">Falta indicar la columna del teléfono.</span>}
            </div>
          </>
        )}

        {reporte && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { l: "Filas", v: reporte.filas, c: "text-fg" },
                { l: "Contactos nuevos", v: reporte.creados, c: "text-ok-text" },
                { l: "Actualizados", v: reporte.actualizados, c: "text-info-text" },
                { l: "Con error", v: reporte.con_error, c: reporte.con_error ? "text-danger-text" : "text-faint" },
              ].map((k) => (
                <div key={k.l} className="rounded-xl border border-line bg-surface-2 p-3">
                  <div className={`text-xl font-bold tabular-nums ${k.c}`}>{k.v}</div>
                  <div className="mt-0.5 text-xs text-muted">{k.l}</div>
                </div>
              ))}
            </div>
            {reporte.campana && (
              <Note tone="brand">
                Campaña: {reporte.campana.added} número(s) agregado(s)
                {reporte.campana.updated > 0 && `, ${reporte.campana.updated} actualizado(s)`}
                {(reporte.campana.bloqueados?.length ?? 0) > 0 &&
                  `, ${reporte.campana.bloqueados!.length} no cargado(s) por la política de salientes`}
                .
              </Note>
            )}
            {reporte.errores.length > 0 && (
              <div className="max-h-64 overflow-y-auto rounded-xl border border-line">
                {reporte.errores.map((e) => (
                  <div key={e.fila} className="border-b border-line/60 px-3.5 py-2 text-xs last:border-0">
                    <span className="font-mono text-faint">Fila {e.fila}</span> <span className="text-danger-text">{e.motivo}</span>
                  </div>
                ))}
                {reporte.con_error > reporte.errores.length && (
                  <div className="px-3.5 py-2 text-xs text-faint">
                    … y {reporte.con_error - reporte.errores.length} más con el mismo tipo de problema.
                  </div>
                )}
              </div>
            )}
            <Button variant="secondary" onClick={reiniciar}>
              Importar otro archivo
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
