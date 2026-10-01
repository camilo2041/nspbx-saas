"use client";

import { useEffect, useState } from "react";

import { Button, Card, CardHeader, ErrorBanner, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

// Consumo del mes (ver backend/app/services/consumo.py). Con `plataforma`,
// una fila por empresa: la base para facturar.

interface Consumo {
  mes: string;
  tenant_id: number;
  empresa?: string;
  llamadas: number;
  llamadas_contestadas: number;
  minutos_hablados: number;
  llamadas_por_troncal: number;
  minutos_por_troncal: number;
  conversaciones_ia: number;
  minutos_ia: number;
  costo_ia_usd: number;
  grabaciones_mb: number;
}

function mesActual(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function bajar(path: string, nombre: string) {
  const blob = await api.getBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}

const COLUMNAS: [keyof Consumo, string][] = [
  ["minutos_por_troncal", "Min. por troncal"],
  ["llamadas", "Llamadas"],
  ["llamadas_contestadas", "Contestadas"],
  ["minutos_hablados", "Min. hablados"],
  ["conversaciones_ia", "Conversaciones IA"],
  ["minutos_ia", "Min. IA"],
  ["costo_ia_usd", "Costo IA (USD)"],
  ["grabaciones_mb", "Grabaciones (MB)"],
];

export function ConsumoMensual({ plataforma = false }: { plataforma?: boolean }) {
  const [mes, setMes] = useState(mesActual());
  const [filas, setFilas] = useState<Consumo[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const ruta = plataforma ? "/api/plataforma/consumo" : "/api/consumo";
    api
      .get<Consumo | Consumo[]>(`${ruta}?mes=${mes}`)
      .then((r) => setFilas(Array.isArray(r) ? r : [r]))
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar el consumo"));
  }, [mes, plataforma]);

  async function exportar() {
    try {
      if (plataforma) await bajar(`/api/plataforma/consumo/csv?mes=${mes}`, `consumo-${mes}.csv`);
      else await bajar("/api/consumo/csv?meses=12", "consumo.csv");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo exportar");
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title="Consumo del mes"
        subtitle={
          plataforma
            ? "Por empresa. Los minutos que se facturan son los que salen por una troncal."
            : "Los minutos que se facturan son los que salen por una troncal; las llamadas internas no cuentan."
        }
      />
      <div className="space-y-3 p-4">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="month"
            value={mes}
            onChange={(e) => e.target.value && setMes(e.target.value)}
            className="rounded-xl border border-line bg-surface px-3 py-1.5 text-sm"
          />
          <Button variant="secondary" onClick={exportar}>
            {plataforma ? "Exportar CSV del mes" : "Exportar CSV (12 meses)"}
          </Button>
        </div>
        {filas && (
          <Table head={[...(plataforma ? ["Empresa"] : []), ...COLUMNAS.map(([, t]) => t)]}>
            {filas.map((f) => (
              <Tr key={f.tenant_id}>
                {plataforma && <Td strong>{f.empresa}</Td>}
                {COLUMNAS.map(([k]) => (
                  <Td key={k} mono>
                    {String(f[k] ?? "")}
                  </Td>
                ))}
              </Tr>
            ))}
          </Table>
        )}
      </div>
    </Card>
  );
}
