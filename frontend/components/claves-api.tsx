"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, ErrorBanner, Input, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

// Claves de la API pública (/api/v1). Ver backend/app/core/claves_api.py.

interface Clave {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  created_by: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
}

function fecha(valor: string | null): string {
  return valor ? new Date(valor + "Z").toLocaleString() : "—";
}

export function ClavesApi() {
  const [claves, setClaves] = useState<Clave[]>([]);
  const [escopos, setEscopos] = useState<Record<string, string>>({});
  const [nombre, setNombre] = useState("");
  const [elegidos, setElegidos] = useState<string[]>([]);
  const [dias, setDias] = useState("365");
  const [nueva, setNueva] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");

  const cargar = useCallback(async () => {
    try {
      setClaves(await api.get<Clave[]>("/api/claves-api"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las claves");
    }
  }, []);

  useEffect(() => {
    api.get<Record<string, string>>("/api/claves-api/escopos").then(setEscopos).catch(() => setEscopos({}));
    api
      .get<Clave[]>("/api/claves-api")
      .then(setClaves)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudieron cargar las claves"));
  }, []);

  async function crear() {
    setError("");
    setCargando(true);
    try {
      const r = await api.post<Clave & { clave: string }>("/api/claves-api", {
        name: nombre,
        scopes: elegidos,
        dias_validez: dias.trim() ? Number(dias) : null,
      });
      setNueva(r.clave);
      setNombre("");
      setElegidos([]);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear la clave");
    } finally {
      setCargando(false);
    }
  }

  async function revocar(c: Clave) {
    if (!confirm(`¿Revocar la clave "${c.name}"? Lo que la use deja de funcionar ya.`)) return;
    try {
      await api.del(`/api/claves-api/${c.id}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo revocar");
    }
  }

  function alternar(s: string) {
    setElegidos((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title="Claves de la API"
        subtitle="Para conectar otros sistemas (CRM, agenda, ERP) por /api/v1. Cada clave puede solo lo que marques."
      />
      <div className="space-y-4 p-4">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {nueva && (
          <div className="rounded-xl border border-line bg-surface-2 p-3 text-sm">
            <p className="mb-1 font-medium">Copia la clave ahora: no se vuelve a mostrar.</p>
            <code className="block break-all font-mono text-xs">{nueva}</code>
            <Button size="sm" variant="secondary" className="mt-2" onClick={() => setNueva(null)}>
              Ya la guardé
            </Button>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Nombre" value={nombre} onChange={setNombre} placeholder="crm-ventas" />
          <Input
            label="Días de validez"
            value={dias}
            onChange={setDias}
            type="number"
            hint="Vacío = no vence. Conviene que venza y rotarla."
          />
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          {Object.entries(escopos).map(([s, etiqueta]) => (
            <label key={s} className="flex items-center gap-1.5">
              <input type="checkbox" checked={elegidos.includes(s)} onChange={() => alternar(s)} />
              {etiqueta}
            </label>
          ))}
        </div>
        <Button onClick={crear} loading={cargando} disabled={nombre.trim().length < 2 || elegidos.length === 0}>
          Crear clave
        </Button>

        {claves.length > 0 && (
          <Table head={["Nombre", "Prefijo", "Permisos", "Último uso", "Vence", "Estado", ""]}>
            {claves.map((c) => (
              <Tr key={c.id}>
                <Td strong>{c.name}</Td>
                <Td mono>{c.prefix}</Td>
                <Td muted>{c.scopes.join(", ")}</Td>
                <Td muted>{fecha(c.last_used_at)}</Td>
                <Td muted>{fecha(c.expires_at)}</Td>
                <Td>
                  {c.revoked_at ? (
                    <Badge color="red">Revocada</Badge>
                  ) : c.expires_at && new Date(c.expires_at + "Z") < new Date() ? (
                    <Badge color="amber">Vencida</Badge>
                  ) : (
                    <Badge color="green">Activa</Badge>
                  )}
                </Td>
                <Td>
                  {!c.revoked_at && (
                    <Button size="sm" variant="danger" onClick={() => revocar(c)}>
                      Revocar
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </div>
    </Card>
  );
}
