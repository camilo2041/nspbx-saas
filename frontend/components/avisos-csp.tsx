"use client";

import { useEffect, useState } from "react";

import { Card, CardHeader, EmptyState, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

// Lo que la política de contenido completa bloquearía si se aplicara (ver
// backend/app/api/csp.py y frontend/next.config.ts).

interface Aviso {
  directiva: string;
  origen: string;
  pagina: string;
  veces: number;
  primera: string;
  ultima: string;
}

export function AvisosCsp() {
  const [avisos, setAvisos] = useState<Aviso[] | null>(null);

  useEffect(() => {
    api.get<Aviso[]>("/api/plataforma/csp").then(setAvisos).catch(() => setAvisos(null));
  }, []);

  if (avisos === null) return null;
  return (
    <Card className="mt-4">
      <CardHeader
        title="Política de contenido (CSP): qué bloquearía"
        subtitle="Avisos de los navegadores desde el último reinicio del backend. Cuando quede vacía (o solo con extensiones del navegador), la política se puede aplicar."
      />
      {avisos.length === 0 ? (
        <EmptyState title="Sin avisos" hint="Ningún navegador reportó algo que la política completa bloquearía." />
      ) : (
        <Table head={["Directiva", "Origen bloqueado", "Página", "Veces", "Última"]}>
          {avisos.map((a) => (
            <Tr key={`${a.directiva}|${a.origen}|${a.pagina}`}>
              <Td mono>{a.directiva}</Td>
              <Td mono>{a.origen}</Td>
              <Td muted>{a.pagina}</Td>
              <Td>{a.veces}</Td>
              <Td muted>{new Date(a.ultima + "Z").toLocaleString()}</Td>
            </Tr>
          ))}
        </Table>
      )}
    </Card>
  );
}
