"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Sesiones abiertas del propio usuario (backend /api/auth/sesiones): un
// equipo por fila (la app móvil). El panel no se lista uno por uno: vive de
// una sesión de 8 h, y «Cerrar todas» también la corta.

interface SesionAbierta {
  id: number;
  plataforma: string | null;
  dispositivo: string | null;
  ultima_actividad: string;
  vence: string;
}

const PLATAFORMA: Record<string, string> = { android: "Android", ios: "iPhone", web: "Navegador" };

export function SesionesAbiertas() {
  const { salir } = useAuth();
  const [sesiones, setSesiones] = useState<SesionAbierta[] | null>(null);
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState<number | "todas" | null>(null);

  const cargar = useCallback(async () => {
    try {
      setSesiones(await api.get<SesionAbierta[]>("/api/auth/sesiones"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las sesiones");
    }
  }, []);

  useEffect(() => {
    (async () => {
      await cargar();
    })();
  }, [cargar]);

  const cerrar = async (s: SesionAbierta) => {
    setTrabajando(s.id);
    try {
      await api.del(`/api/auth/sesiones/${s.id}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cerrar");
    } finally {
      setTrabajando(null);
    }
  };

  const cerrarTodas = async () => {
    if (!confirm("¿Cerrar todas tus sesiones, también esta? Vas a tener que volver a entrar en cada equipo.")) return;
    setTrabajando("todas");
    try {
      await api.post("/api/auth/sesiones/cerrar-todas");
      salir();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cerrar");
      setTrabajando(null);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Sesiones abiertas"
        subtitle="Los equipos con la app abierta en tu cuenta. Si no reconoces uno, ciérralo y cambia tu contraseña."
        actions={
          <Button size="sm" variant="danger" onClick={cerrarTodas} loading={trabajando === "todas"}>
            Cerrar todas
          </Button>
        }
      />
      <CardBody className="space-y-2">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {sesiones && sesiones.length === 0 && (
          <p className="text-sm text-fg-soft">No tienes la app móvil abierta en ningún equipo. Este navegador sí tiene sesión.</p>
        )}
        {sesiones?.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-fg">{s.dispositivo || "Equipo sin nombre"}</div>
              <div className="text-xs text-muted">
                Última actividad: {new Date(s.ultima_actividad + "Z").toLocaleString()}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Badge color="blue">{PLATAFORMA[s.plataforma ?? ""] ?? "App"}</Badge>
              <Button size="sm" variant="secondary" onClick={() => cerrar(s)} loading={trabajando === s.id}>
                Cerrar
              </Button>
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
