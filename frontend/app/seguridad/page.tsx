"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { AuditTable } from "@/components/audit-table";
import { ClavesApi } from "@/components/claves-api";
import { WebhooksCrm } from "@/components/webhooks-crm";
import { PrivacidadTitular } from "@/components/privacidad-titular";
import { api } from "@/lib/api";
import { AlertaTrafico } from "@/lib/types";

const TIPO_ALERTA: Record<string, string> = {
  pico: "Pico de salientes",
  madrugada: "Salientes de madrugada",
  destino_nuevo: "Destino internacional nuevo",
  cupo: "Cerca del cupo diario",
};

interface Bloqueo {
  jail: string;
  ip: string;
  desde: number;
  hasta: number | null;
  segundos: number;
  veces: number;
  vigente: boolean;
}

interface ClaveDebil {
  id: number;
  number: string;
  motivo: string;
}

interface Datos {
  disponible: boolean;
  vigentes: Bloqueo[];
  historico: Bloqueo[];
}

const JAILS: Record<string, string> = {
  "nspbx-freeswitch": "Central telefónica",
  sshd: "Acceso SSH",
};

function fecha(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString();
}

function duracion(segundos: number): string {
  if (segundos <= 0) return "permanente";
  if (segundos < 3600) return `${Math.round(segundos / 60)} min`;
  if (segundos < 86400) return `${Math.round(segundos / 3600)} h`;
  return `${Math.round(segundos / 86400)} días`;
}

function restante(hasta: number | null): string {
  if (hasta === null) return "permanente";
  const seg = hasta - Date.now() / 1000;
  if (seg <= 0) return "venciendo";
  return duracion(seg);
}

export default function SeguridadPage() {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [debiles, setDebiles] = useState<ClaveDebil[] | null>(null);
  const [alertas, setAlertas] = useState<AlertaTrafico[] | null>(null);

  useEffect(() => {
    // Independiente de fail2ban: aunque no se pueda leer, esto sí.
    api.get<ClaveDebil[]>("/api/security/claves-debiles").then(setDebiles).catch(() => setDebiles(null));
    api.get<AlertaTrafico[]>("/api/security/alertas").then(setAlertas).catch(() => setAlertas(null));
  }, []);

  const load = useCallback(async () => {
    try {
      setDatos(await api.get<Datos>("/api/security/bans"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    // Un ataque en curso cambia la lista cada pocos segundos; sin esto hay
    // que recargar a mano para ver si la defensa está reaccionando.
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  const porJail = (bs: Bloqueo[]) => {
    const m = new Map<string, number>();
    for (const b of bs) m.set(b.jail, (m.get(b.jail) ?? 0) + 1);
    return [...m.entries()];
  };

  const filas = (bs: Bloqueo[], conRestante: boolean) =>
    bs.map((b, i) => (
      <Tr key={`${b.jail}-${b.ip}-${b.desde}`} delay={i * 25}>
        <Td mono strong>
          {b.ip}
        </Td>
        <Td>{JAILS[b.jail] ?? b.jail}</Td>
        <Td muted>{fecha(b.desde)}</Td>
        <Td>{conRestante ? restante(b.hasta) : duracion(b.segundos)}</Td>
        <Td>
          {b.veces > 1 ? (
            <Badge color="amber">{b.veces}ª vez</Badge>
          ) : (
            <span className="text-fg-soft">1ª</span>
          )}
        </Td>
      </Tr>
    ));

  return (
    <div>
      <PageHeader
        title="Seguridad"
        subtitle="IPs que fail2ban está bloqueando por intentos fallidos de registro SIP o de acceso SSH"
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {alertas && alertas.length > 0 && (
        <Card className="mb-4">
          <CardHeader
            title="Alertas de tráfico saliente"
            subtitle="Avisan, no cortan. Si no reconoces el tráfico, pausa las salientes en Ajustes y revisa las extensiones."
          />
          <Table head={["Cuándo", "Tipo", "Detalle"]}>
            {alertas.map((a) => (
              <Tr key={a.id}>
                <Td muted>{new Date(a.cuando + "Z").toLocaleString()}</Td>
                <Td>
                  <Badge color="amber">{TIPO_ALERTA[a.tipo] ?? a.tipo}</Badge>
                </Td>
                <Td>{a.detalle}</Td>
              </Tr>
            ))}
          </Table>
        </Card>
      )}

      {debiles && debiles.length > 0 && (
        <Card className="mb-4">
          <CardHeader
            title="Contraseñas SIP débiles"
            subtitle={`${debiles.length} extensión(es) con una contraseña que los escáneres de Internet adivinan. Cámbialas en Extensiones.`}
          />
          <Table head={["Extensión", "Problema"]}>
            {debiles.map((d) => (
              <Tr key={d.id}>
                <Td mono strong>
                  {d.number}
                </Td>
                <Td>{d.motivo}</Td>
              </Tr>
            ))}
          </Table>
        </Card>
      )}

      {loading ? (
        <Card>
          <TableSkeleton cols={5} />
        </Card>
      ) : !datos?.disponible ? (
        <Card>
          <EmptyState
            title="No se puede leer fail2ban"
            hint="O no está instalado en el servidor, o falta montar su base en el contenedor. Instalación: copiar deploy/fail2ban/ a /etc/fail2ban/ y reiniciar el servicio."
          />
        </Card>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Bloqueos vigentes"
              subtitle={
                datos.vigentes.length === 0
                  ? "Ninguno en este momento"
                  : porJail(datos.vigentes)
                      .map(([j, n]) => `${n} en ${JAILS[j] ?? j}`)
                      .join(" · ")
              }
            />
            {datos.vigentes.length === 0 ? (
              <EmptyState
                title="Sin bloqueos activos"
                hint="Nadie está bloqueado ahora mismo. Los intentos fallidos se siguen contando: 6 en 10 minutos activan un bloqueo de 24 horas."
              />
            ) : (
              <Table head={["IP", "Origen", "Bloqueada el", "Le queda", "Reincidencia"]}>
                {filas(datos.vigentes, true)}
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Histórico"
              subtitle={`Últimos ${datos.historico.length} bloqueos aplicados, vigentes o ya vencidos`}
            />
            {datos.historico.length === 0 ? (
              <EmptyState title="Sin registros" hint="Todavía no hubo ningún bloqueo." />
            ) : (
              <Table head={["IP", "Origen", "Bloqueada el", "Duración", "Reincidencia"]}>
                {filas(datos.historico, false)}
              </Table>
            )}
          </Card>

          <Card>
            <div className="p-4 text-sm text-fg-soft">
              <p className="mb-2">
                Esta pantalla es de solo lectura por diseño. El socket de control de fail2ban no permite únicamente
                desbloquear: también bloquear, recargar y reconfigurar. Dárselo al panel web convertiría cualquier fallo
                de autenticación en control del cortafuegos del servidor.
              </p>
              <p className="font-mono text-xs">
                Para desbloquear, en el servidor: fail2ban-client set &lt;jail&gt; unbanip &lt;ip&gt;
              </p>
            </div>
          </Card>
        </div>
      )}
      <PrivacidadTitular />
      <ClavesApi />
      <WebhooksCrm />
      <AuditTable
        endpoint="/api/security/auditoria"
        title="Registro de auditoría"
        subtitle="Cada cambio y cada escucha de grabación: quién, cuándo, desde dónde y con qué resultado. Las contraseñas y claves no se guardan."
      />
    </div>
  );
}
