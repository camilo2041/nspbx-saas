"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, EmptyState, ErrorBanner, Input, Modal, Note, Select, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";

// Servidores de clientes que corren el sistema completo con una empresa
// nuestra (docs/plan-fase-k.md; backend/app/api/instalaciones.py). Su
// licencia les llega firmada en cada latido.

interface Instalacion {
  id: number;
  nombre: string;
  empresa_id: number;
  empresa: string | null;
  estado: "pendiente" | "activa" | "suspendida" | "revocada";
  codigo_vence: string | null;
  activada_at: string | null;
  ultimo_latido: string | null;
  en_linea: boolean;
  version: string | null;
  ip: string | null;
  uso: Record<string, number>;
  subdominio: string | null;
  ip_local: string | null;
  cert_vence: string | null;
  cert_error: string | null;
  codigo?: string;
}

interface Listado {
  central_lista: boolean;
  dns_listo: boolean;
  gracia_horas: number;
  instalaciones: Instalacion[];
}

const COLOR_ESTADO: Record<Instalacion["estado"], string> = {
  pendiente: "amber",
  activa: "green",
  suspendida: "red",
  revocada: "slate",
};

const ETIQUETA_USO: Record<string, string> = {
  extensiones: "ext.",
  usuarios: "usuarios",
  minutos_salientes_mes: "min salientes este mes",
  llamadas_entrantes_mes: "entrantes este mes",
};

function hace(fecha: string | null): string {
  if (!fecha) return "nunca";
  const min = Math.round((Date.now() - new Date(fecha + "Z").getTime()) / 60000);
  if (min < 2) return "ahora";
  if (min < 120) return `hace ${min} min`;
  if (min < 48 * 60) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} días`;
}

export function InstalacionesLocales({ empresas }: { empresas: { id: number; name: string }[] }) {
  const [datos, setDatos] = useState<Listado | null>(null);
  const [error, setError] = useState("");
  const [nueva, setNueva] = useState<{ empresa_id: string; nombre: string } | null>(null);
  const [codigo, setCodigo] = useState<Instalacion | null>(null);
  const [trabajando, setTrabajando] = useState("");
  const [copiado, setCopiado] = useState("");

  const cargar = useCallback(async () => {
    try {
      setDatos(await api.get<Listado>("/api/plataforma/instalaciones"));
    } catch {
      setDatos(null);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- carga datos de la API al montar
    cargar();
  }, [cargar]);

  const hacer = async (clave: string, fn: () => Promise<unknown>) => {
    setTrabajando(clave);
    setError("");
    try {
      await fn();
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar");
    } finally {
      setTrabajando("");
    }
  };

  const crear = () =>
    nueva &&
    hacer("crear", async () => {
      const r = await api.post<Instalacion>("/api/plataforma/instalaciones", {
        empresa_id: Number(nueva.empresa_id),
        nombre: nueva.nombre.trim(),
      });
      setNueva(null);
      setCodigo(r);
    });

  const otroCodigo = (i: Instalacion) => {
    if (i.estado === "activa" && !confirm(`Con el código nuevo, ${i.nombre} se puede reinstalar y el servidor actual deja de valer. ¿Seguir?`)) return;
    hacer(`codigo-${i.id}`, async () => setCodigo(await api.post<Instalacion>(`/api/plataforma/instalaciones/${i.id}/codigo`)));
  };

  const accion = (i: Instalacion, que: "suspender" | "reactivar" | "revocar", aviso?: string) => {
    if (aviso && !confirm(aviso)) return;
    hacer(`${que}-${i.id}`, () => api.post(`/api/plataforma/instalaciones/${i.id}/${que}`));
  };

  const copiar = (texto: string, clave: string) => {
    navigator.clipboard?.writeText(texto).then(() => {
      setCopiado(clave);
      setTimeout(() => setCopiado(""), 1500);
    });
  };

  if (datos === null) return null;
  const comando = `curl -fsSL ${typeof window !== "undefined" ? window.location.origin : ""}/api/licencia/instalar.sh | sudo bash`;

  return (
    <Card className="mb-4">
      <CardHeader
        title="Instalaciones locales"
        subtitle={`Servidores de clientes con el sistema completo y una empresa. Hablan con esta central cada hora; sin contacto, siguen ${datos.gracia_horas} h y después se detienen las campañas y los cambios (los teléfonos siguen funcionando).`}
        actions={
          <Button size="sm" onClick={() => setNueva({ empresa_id: "", nombre: "" })} disabled={!datos.central_lista}>
            + Instalación
          </Button>
        }
      />
      {!datos.central_lista && (
        <div className="px-4 pt-3">
          <Note tone="warn">
            Esta central todavía no puede emitir licencias: falta <span className="font-mono">LICENCIA_CLAVE_PRIVADA</span> en el .env.
            Genérala con <span className="font-mono">docker compose exec backend python -m app.cli.claves_licencia</span>.
          </Note>
        </div>
      )}
      {datos.central_lista && !datos.dns_listo && (
        <div className="px-4 pt-3">
          <Note tone="muted">
            Las instalaciones «solo red local» usan un certificado propio (el navegador pide aceptarlo una vez). Para darles una
            dirección segura sin advertencias, configura <span className="font-mono">DNS_CLOUDFLARE_TOKEN</span>,{" "}
            <span className="font-mono">DNS_CLOUDFLARE_ZONA_ID</span> y <span className="font-mono">DOMINIO_LOCAL_SUFIJO</span> en el .env.
          </Note>
        </div>
      )}
      {error && (
        <div className="px-4 pt-3">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      {datos.instalaciones.length === 0 ? (
        <EmptyState title="Sin instalaciones locales" hint="Crea una para darle a un cliente su código de activación." />
      ) : (
        <Table head={["Instalación", "Estado", "Contacto", "Red local", "Uso", ""]}>
          {datos.instalaciones.map((i) => (
            <Tr key={i.id}>
              <Td strong>
                {i.nombre}
                <div className="text-[11px] font-normal text-faint">{i.empresa ?? `Empresa ${i.empresa_id}`}</div>
              </Td>
              <Td>
                <Badge color={COLOR_ESTADO[i.estado]} dot>
                  {i.estado}
                </Badge>
                {i.estado === "pendiente" && i.codigo_vence && (
                  <div className="mt-0.5 text-[11px] text-faint">código vence {new Date(i.codigo_vence + "Z").toLocaleDateString()}</div>
                )}
              </Td>
              <Td>
                {i.ultimo_latido ? (
                  <>
                    <Badge color={i.en_linea ? "green" : "red"} dot>
                      {i.en_linea ? "En línea" : "Sin contacto"}
                    </Badge>
                    <div className="mt-0.5 text-[11px] text-faint">
                      {hace(i.ultimo_latido)}
                      {i.version && ` · v${i.version}`}
                      {i.ip && ` · ${i.ip}`}
                    </div>
                  </>
                ) : (
                  <span className="text-xs text-faint">Sin activar</span>
                )}
              </Td>
              <Td>
                {i.subdominio && i.cert_vence ? (
                  <>
                    <span className="break-all font-mono text-xs text-fg">{i.subdominio}</span>
                    <div className="mt-0.5 text-[11px] text-faint">
                      {i.ip_local} · certificado hasta {new Date(i.cert_vence + "Z").toLocaleDateString()}
                    </div>
                  </>
                ) : (
                  <span className="text-xs text-faint">—</span>
                )}
                {i.cert_error && (
                  <div className="mt-0.5 text-[11px] text-danger-text" title={i.cert_error}>
                    Certificado: {i.cert_error.slice(0, 80)}
                  </div>
                )}
              </Td>
              <Td muted>
                <span className="text-xs">
                  {Object.entries(ETIQUETA_USO)
                    .filter(([k]) => i.uso[k] !== undefined)
                    .map(([k, t]) => `${i.uso[k]} ${t}`)
                    .join(" · ") || "—"}
                </span>
              </Td>
              <Td>
                <div className="flex flex-wrap justify-end gap-1.5">
                  {i.estado !== "revocada" && (
                    <Button size="sm" variant="ghost" loading={trabajando === `codigo-${i.id}`} onClick={() => otroCodigo(i)}>
                      Nuevo código
                    </Button>
                  )}
                  {i.estado === "activa" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={trabajando === `suspender-${i.id}`}
                      onClick={() => accion(i, "suspender", `¿Suspender ${i.nombre}? En su próximo latido deja de operar (los teléfonos siguen).`)}
                    >
                      Suspender
                    </Button>
                  )}
                  {i.estado === "suspendida" && (
                    <Button size="sm" variant="secondary" loading={trabajando === `reactivar-${i.id}`} onClick={() => accion(i, "reactivar")}>
                      Reactivar
                    </Button>
                  )}
                  {i.estado !== "revocada" ? (
                    <Button
                      size="sm"
                      variant="danger"
                      loading={trabajando === `revocar-${i.id}`}
                      onClick={() => accion(i, "revocar", `¿Revocar ${i.nombre} para siempre? No se puede volver a activar.`)}
                    >
                      Revocar
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="danger"
                      loading={trabajando === `borrar-${i.id}`}
                      onClick={() => confirm(`¿Borrar ${i.nombre} de la lista?`) && hacer(`borrar-${i.id}`, () => api.del(`/api/plataforma/instalaciones/${i.id}`))}
                    >
                      Borrar
                    </Button>
                  )}
                </div>
              </Td>
            </Tr>
          ))}
        </Table>
      )}

      <Modal
        open={!!nueva}
        onClose={() => setNueva(null)}
        title="Nueva instalación local"
        subtitle="El cliente la activa con un código que se muestra una sola vez."
        footer={
          <>
            <Button variant="secondary" onClick={() => setNueva(null)}>
              Cancelar
            </Button>
            <Button onClick={crear} loading={trabajando === "crear"} disabled={!nueva?.empresa_id || (nueva?.nombre.trim().length ?? 0) < 2}>
              Crear y ver el código
            </Button>
          </>
        }
      >
        {nueva && (
          <div className="space-y-4">
            <Select
              label="Empresa"
              value={nueva.empresa_id}
              onChange={(v) => setNueva({ ...nueva, empresa_id: v })}
              placeholder="Elige la empresa"
              options={empresas.map((e) => ({ value: String(e.id), label: e.name }))}
              hint="Su nombre, tipo, módulos y licencia (plan, topes, vencimiento) son los que recibe el servidor del cliente. Se cambian acá, en la empresa."
            />
            <Input
              label="Nombre del servidor"
              value={nueva.nombre}
              onChange={(v) => setNueva({ ...nueva, nombre: v })}
              placeholder="Sede principal"
              hint="Para reconocerlo en esta lista."
            />
          </div>
        )}
      </Modal>

      <Modal
        open={!!codigo}
        onClose={() => setCodigo(null)}
        title={`Código de activación · ${codigo?.nombre ?? ""}`}
        subtitle="Cópialo ahora: no se vuelve a mostrar. Vence en 7 días y sirve una sola vez."
        footer={<Button onClick={() => setCodigo(null)}>Listo</Button>}
      >
        {codigo?.codigo && (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3">
              <span className="select-all font-mono text-lg font-semibold tracking-wider text-fg">{codigo.codigo}</span>
              <Button size="sm" variant="secondary" onClick={() => copiar(codigo.codigo!, "codigo")}>
                {copiado === "codigo" ? "Copiado" : "Copiar"}
              </Button>
            </div>
            <div>
              <span className="mb-1.5 block text-xs font-medium text-fg-soft">En el servidor del cliente (Ubuntu 22.04/24.04 o Debian 12):</span>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3">
                <span className="select-all break-all font-mono text-xs text-fg">{comando}</span>
                <Button size="sm" variant="secondary" onClick={() => copiar(comando, "comando")}>
                  {copiado === "comando" ? "Copiado" : "Copiar"}
                </Button>
              </div>
            </div>
            <Note tone="muted">
              El asistente revisa el equipo, pide este código, muestra la empresa y el plan, y deja todo instalado con el usuario
              admin y su contraseña en la pantalla final.
            </Note>
          </div>
        )}
      </Modal>
    </Card>
  );
}
