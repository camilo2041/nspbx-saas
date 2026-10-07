"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, Note, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

interface Bloqueo {
  jail: string;
  ip: string;
  desde: number;
  hasta: number | null;
  veces: number;
}

interface Pedido {
  id: number;
  jail: string;
  ip: string;
  pedido_por: string;
  pedido_en: string;
  estado: "pendiente" | "hecho" | "no_estaba" | "error";
  detalle: string | null;
  sin_atender: boolean;
}

interface Datos {
  disponible: boolean;
  bloqueos: Bloqueo[];
  pedidos: Pedido[];
}

const ESTADO: Record<Pedido["estado"], { texto: string; color: "amber" | "green" | "gray" | "red" }> = {
  pendiente: { texto: "Pendiente", color: "amber" },
  hecho: { texto: "Desbloqueada", color: "green" },
  no_estaba: { texto: "Ya no estaba", color: "gray" },
  error: { texto: "Falló", color: "red" },
};

const fecha = (epoch: number) => new Date(epoch * 1000).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });

/**
 * Quitar una IP de un bloqueo de fail2ban (services/desbloqueos.py): el panel
 * deja el pedido y un script del host lo ejecuta en menos de un minuto. La
 * aplicación nunca tiene el cortafuegos en sus manos.
 */
export function DesbloqueosPlataforma() {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [trabajando, setTrabajando] = useState<string | null>(null);
  const [error, setError] = useState("");

  const cargar = useCallback(() => {
    api.get<Datos>("/api/plataforma/desbloqueos").then(setDatos, () => undefined);
  }, []);
  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 20_000);
    return () => clearInterval(t);
  }, [cargar]);

  if (!datos || (!datos.disponible && !datos.pedidos.length)) return null;
  const pendiente = (b: Bloqueo) => datos.pedidos.some((p) => p.estado === "pendiente" && p.ip === b.ip && p.jail === b.jail);
  const atascado = datos.pedidos.some((p) => p.sin_atender);

  const desbloquear = async (b: Bloqueo) => {
    if (!window.confirm(`¿Quitar el bloqueo de ${b.ip} (${b.jail})? Si sigue atacando, fail2ban la vuelve a bloquear.`)) return;
    setTrabajando(`${b.jail}|${b.ip}`);
    setError("");
    try {
      await api.post("/api/plataforma/desbloqueos", { jail: b.jail, ip: b.ip });
      cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo pedir el desbloqueo");
    } finally {
      setTrabajando(null);
    }
  };

  return (
    <Card className="mb-4">
      <CardHeader
        title="IP bloqueadas (fail2ban)"
        subtitle="Por ejemplo, la oficina de un cliente que se equivocó de clave varias veces. El desbloqueo lo hace un script del servidor en menos de un minuto."
      />
      <div className="space-y-3 px-5 pb-5">
        {atascado && (
          <Note tone="warn">
            Hay pedidos de hace más de 5 minutos sin atender: el script del servidor no está corriendo. Ver
            docs/runbooks/desbloquear-ip.md.
          </Note>
        )}
        {error && <Note tone="warn">{error}</Note>}
        {datos.bloqueos.length === 0 ? (
          <p className="text-sm text-muted">No hay IP bloqueadas ahora.</p>
        ) : (
          <Table head={["IP", "Origen", "Desde", "Hasta", "Veces", ""]}>
            {datos.bloqueos.map((b) => (
              <Tr key={`${b.jail}|${b.ip}`}>
                <Td>
                  <span className="font-mono">{b.ip}</span>
                </Td>
                <Td muted>{b.jail}</Td>
                <Td muted>{fecha(b.desde)}</Td>
                <Td muted>{b.hasta ? fecha(b.hasta) : "Permanente"}</Td>
                <Td muted>{b.veces}</Td>
                <Td align="right">
                  {pendiente(b) ? (
                    <Badge color="amber">Pedido</Badge>
                  ) : (
                    <Button size="sm" variant="secondary" loading={trabajando === `${b.jail}|${b.ip}`} onClick={() => desbloquear(b)}>
                      Desbloquear
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
        {datos.pedidos.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-fg-soft">Últimos pedidos ({datos.pedidos.length})</summary>
            <ul className="mt-2 divide-y divide-line rounded-xl border border-line">
              {datos.pedidos.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                  <span className="font-mono">{p.ip}</span>
                  <span className="text-muted">{p.jail}</span>
                  <Badge color={ESTADO[p.estado].color}>{ESTADO[p.estado].texto}</Badge>
                  <span className="text-xs text-muted">
                    {p.pedido_por} · {new Date(`${p.pedido_en}Z`).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" })}
                    {p.detalle ? ` · ${p.detalle}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}
