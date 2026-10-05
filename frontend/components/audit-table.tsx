"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Card, CardHeader, EmptyState, Select, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";
import { RegistroAuditoria } from "@/lib/types";

const COLOR_RESULTADO: Record<string, string> = {
  ok: "green",
  denegado: "amber",
  rechazado: "amber",
  error: "red",
};

/** Registro de auditoría: quién hizo qué, cuándo y desde dónde. Lo usan
 *  Seguridad (la empresa, `/api/security/auditoria`) y Empresas (la
 *  plataforma, `/api/plataforma/auditoria`). */
export function AuditTable({ endpoint, title, subtitle }: { endpoint: string; title: string; subtitle: string }) {
  const [filas, setFilas] = useState<RegistroAuditoria[] | null>(null);
  const [resultado, setResultado] = useState("");

  const cargar = useCallback(async () => {
    const q = new URLSearchParams({ limite: "100" });
    if (resultado) q.set("resultado", resultado);
    try {
      setFilas(await api.get<RegistroAuditoria[]>(`${endpoint}?${q}`));
    } catch {
      setFilas(null);
    }
  }, [endpoint, resultado]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga inicial y al cambiar el filtro
    cargar();
  }, [cargar]);

  if (filas === null) return null;

  return (
    <Card className="mt-4">
      <CardHeader
        title={title}
        subtitle={subtitle}
        actions={
          <div className="w-40">
            <Select
              label=""
              value={resultado}
              onChange={setResultado}
              options={[
                { value: "", label: "Todos" },
                { value: "ok", label: "Correctos" },
                { value: "denegado", label: "Denegados" },
                { value: "rechazado", label: "Rechazados" },
                { value: "error", label: "Con error" },
              ]}
            />
          </div>
        }
      />
      {filas.length === 0 ? (
        <EmptyState title="Sin registros" hint="Todavía no hay acciones con este filtro." />
      ) : (
        <Table head={["Cuándo", "Quién", "Acción", "Recurso", "Resultado", "IP"]}>
          {filas.map((f) => (
            <Tr key={f.id}>
              <Td muted>{new Date(f.cuando + "Z").toLocaleString()}</Td>
              <Td>{f.actor ?? "—"}</Td>
              <Td mono>
                <span title={f.detalle ? JSON.stringify(f.detalle, null, 1) : undefined}>{f.accion}</span>
              </Td>
              <Td mono muted>
                {f.recurso ?? ""}
              </Td>
              <Td>
                <Badge color={COLOR_RESULTADO[f.resultado] ?? "blue"}>{f.resultado}</Badge>
              </Td>
              <Td mono muted>
                {f.ip ?? ""}
              </Td>
            </Tr>
          ))}
        </Table>
      )}
    </Card>
  );
}
