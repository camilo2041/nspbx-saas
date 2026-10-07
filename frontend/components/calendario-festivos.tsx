"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Input, Toggle } from "@/components/ui";
import { api } from "@/lib/api";

interface FechaEspecial {
  id: number;
  fecha: string;
  nombre: string;
  franja: string | null;
}

interface Calendario {
  cerrar_festivos: boolean;
  nacionales: string[];
  especiales: FechaEspecial[];
}

const dia = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es-CO", { weekday: "short", day: "numeric", month: "short", year: "numeric" });

/**
 * Festivos y fechas especiales (services/festivos.py): cierran lo que tiene
 * horario de atención (rutas entrantes, el bloque Horario del IVR, el widget
 * web). Las fechas especiales también frenan las campañas.
 */
export function CalendarioFestivos() {
  const [cal, setCal] = useState<Calendario | null>(null);
  const [nueva, setNueva] = useState({ fecha: "", nombre: "", franja: "" });
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargar = useCallback(() => {
    api.get<Calendario>("/api/festivos").then(setCal, (e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);
  useEffect(() => {
    cargar();
  }, [cargar]);

  if (!cal) return null;

  const agregar = async () => {
    setGuardando(true);
    setError("");
    try {
      await api.post("/api/festivos/especiales", { fecha: nueva.fecha, nombre: nueva.nombre, franja: nueva.franja || null });
      setNueva({ fecha: "", nombre: "", franja: "" });
      cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo agregar");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Card className="mb-4" guia="ajustes:festivos">
      <CardHeader
        title="Festivos y fechas especiales"
        subtitle="Para lo que tiene horario de atención: números entrantes, el bloque «Horario» del IVR y el botón de llamada web. Lo que atiende 24 horas no se cierra."
      />
      <CardBody className="space-y-5">
        <div className="flex items-start justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
          <span className="text-sm text-fg-soft">
            Cerrar en los festivos de Colombia
            <span className="block text-xs text-muted">
              Próximos: {cal.nacionales.slice(0, 4).map(dia).join(" · ")}. Las campañas ya no marcan en festivos.
            </span>
          </span>
          <Toggle
            guia="festivos:cerrar"
            checked={cal.cerrar_festivos}
            onChange={async (v) => {
              setCal({ ...cal, cerrar_festivos: v });
              await api.put("/api/festivos", { cerrar_festivos: v }).catch(cargar);
            }}
          />
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium text-fg">Fechas propias de la empresa</p>
          {cal.especiales.length === 0 ? (
            <p className="text-xs text-muted">Ninguna. Por ejemplo: cierre por inventario, o el 24 de diciembre solo hasta el mediodía.</p>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {cal.especiales.map((f) => (
                <li key={f.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="w-44 text-fg">{dia(f.fecha)}</span>
                  <span className="flex-1 text-fg-soft">{f.nombre}</span>
                  {f.franja ? <Badge color="amber">Abierto {f.franja}</Badge> : <Badge color="red">Cerrado</Badge>}
                  <Button size="sm" variant="ghost" onClick={() => api.del(`/api/festivos/especiales/${f.id}`).then(cargar)}>
                    Quitar
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div className="grid gap-2 sm:grid-cols-[10rem_1fr_9rem_auto] sm:items-end">
            <Input label="Fecha" type="date" value={nueva.fecha} onChange={(v) => setNueva({ ...nueva, fecha: v })} />
            <Input label="Motivo" value={nueva.nombre} onChange={(v) => setNueva({ ...nueva, nombre: v })} placeholder="Cierre por inventario" />
            <Input
              label="Abierto (opcional)"
              value={nueva.franja}
              onChange={(v) => setNueva({ ...nueva, franja: v })}
              placeholder="08:00-12:00"
            />
            <Button onClick={agregar} loading={guardando} disabled={!nueva.fecha || !nueva.nombre.trim()}>
              Agregar
            </Button>
          </div>
          <p className="text-xs text-muted">Sin franja, ese día se atiende como «cerrado» todo el día y las campañas no marcan.</p>
          {error && <p className="text-xs text-danger-text">{error}</p>}
        </div>
      </CardBody>
    </Card>
  );
}
