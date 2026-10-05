"use client";

import { useState } from "react";

import { Button, Card, CardHeader, ErrorBanner, Input } from "@/components/ui";
import { api } from "@/lib/api";

// Solicitudes de un titular de datos (Ley 1581): qué guarda la empresa de
// un teléfono, y suprimirlo. Ver backend/app/services/privacidad.py.

type Datos = Record<string, Record<string, unknown>[]>;

const NOMBRES: Record<string, string> = {
  citas: "Citas",
  deudas: "Deudas",
  promesas_de_pago: "Promesas de pago",
  numeros_de_campana: "Números de campaña",
  llamadas: "Llamadas",
  conversaciones_voicebot: "Conversaciones con el voizbot",
};

function descargar(telefono: string, datos: Datos) {
  const blob = new Blob([JSON.stringify({ telefono, datos }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `datos-${telefono.replace(/\D/g, "")}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function PrivacidadTitular() {
  const [telefono, setTelefono] = useState("");
  const [datos, setDatos] = useState<Datos | null>(null);
  const [confirmacion, setConfirmacion] = useState("");
  const [resultado, setResultado] = useState<Record<string, number> | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");

  async function consultar() {
    setError("");
    setResultado(null);
    setConfirmacion("");
    setCargando(true);
    try {
      const r = await api.post<{ datos: Datos }>("/api/privacidad/titular/consultar", { telefono });
      setDatos(r.datos);
    } catch (e) {
      setDatos(null);
      setError(e instanceof Error ? e.message : "No se pudo consultar");
    } finally {
      setCargando(false);
    }
  }

  async function suprimir() {
    setError("");
    setCargando(true);
    try {
      setResultado(
        await api.post<Record<string, number>>("/api/privacidad/titular/suprimir", { telefono, confirmacion }),
      );
      setDatos(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo suprimir");
    } finally {
      setCargando(false);
    }
  }

  const total = datos ? Object.values(datos).reduce((n, filas) => n + filas.length, 0) : 0;

  return (
    <Card className="mt-4">
      <CardHeader
        title="Datos de una persona (Ley 1581)"
        subtitle="Cuando alguien pide saber qué datos suyos tiene la empresa, o que se borren. Se busca por teléfono."
      />
      <div className="space-y-4 p-4">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64">
            <Input label="Teléfono" value={telefono} onChange={setTelefono} placeholder="3001234567" mono />
          </div>
          <Button onClick={consultar} loading={cargando} disabled={!telefono.trim()}>
            Consultar
          </Button>
        </div>

        {datos && (
          <div className="space-y-3 text-sm">
            {total === 0 ? (
              <p className="text-fg-soft">La empresa no tiene datos de este teléfono.</p>
            ) : (
              <>
                <ul className="text-fg-soft">
                  {Object.entries(datos)
                    .filter(([, filas]) => filas.length > 0)
                    .map(([k, filas]) => (
                      <li key={k}>
                        {NOMBRES[k] ?? k}: {filas.length}
                      </li>
                    ))}
                </ul>
                <Button variant="secondary" onClick={() => descargar(telefono, datos)}>
                  Descargar (JSON)
                </Button>
                <div className="rounded-xl border border-line p-3">
                  <p className="mb-2 text-fg-soft">
                    Suprimir borra citas, deudas, promesas y números de campaña, y las grabaciones. Las llamadas
                    quedan sin número, nombre ni resumen (se conservan para facturación). No se puede deshacer.
                  </p>
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="w-64">
                      <Input
                        label="Escribe el teléfono otra vez"
                        value={confirmacion}
                        onChange={setConfirmacion}
                        mono
                      />
                    </div>
                    <Button variant="danger" onClick={suprimir} loading={cargando} disabled={!confirmacion.trim()}>
                      Suprimir
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {resultado && (
          <p className="text-sm text-fg-soft">
            Listo:{" "}
            {Object.entries(resultado)
              .filter(([, n]) => n > 0)
              .map(([k, n]) => `${k.replace(/_/g, " ")}: ${n}`)
              .join(" · ") || "no había nada que borrar"}
            .
          </p>
        )}
      </div>
    </Card>
  );
}
