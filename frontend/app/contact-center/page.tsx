"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Check,
  ErrorBanner,
  Input,
  Modal,
  PageHeader,
  RowActions,
  Select,
  Table,
  TableSkeleton,
  Td,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { CategoriaDisposicion, CodigoPausa, Disposicion } from "@/lib/types";

const CATEGORIAS: { value: CategoriaDisposicion; label: string; efecto: string }[] = [
  { value: "venta", label: "Venta", efecto: "Cierra el lead" },
  { value: "contacto", label: "Contacto", efecto: "Cierra el lead" },
  { value: "promesa", label: "Promesa de pago", efecto: "Cierra el lead" },
  { value: "no_contacto", label: "No contacto", efecto: "Lo recicla según la campaña" },
  { value: "callback", label: "Volver a llamar", efecto: "Lo agenda (pide fecha y hora)" },
  { value: "no_llamar", label: "No llamar", efecto: "Lo pasa a la lista de no llamar" },
];

const dispoVacia = { id: 0, codigo: "", nombre: "", categoria: "contacto" as CategoriaDisposicion, color: "#64748b", contacto_humano: true };
const pausaVacia = { id: 0, codigo: "", nombre: "", pagada: true, max_minutos: "" };

/**
 * Catálogos del contact center. Vienen con ejemplos y cada empresa los
 * adapta. No se borran (quedan en la bitácora y en el historial): se
 * desactivan.
 */
export default function ContactCenterPage() {
  const [disposiciones, setDisposiciones] = useState<Disposicion[] | null>(null);
  const [pausas, setPausas] = useState<CodigoPausa[] | null>(null);
  const [error, setError] = useState("");
  const [dispo, setDispo] = useState<typeof dispoVacia | null>(null);
  const [pausa, setPausa] = useState<typeof pausaVacia | null>(null);
  const [guardando, setGuardando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const [d, p] = await Promise.all([
        api.get<Disposicion[]>("/api/contact-center/disposiciones"),
        api.get<CodigoPausa[]>("/api/contact-center/pausas"),
      ]);
      setDisposiciones(d);
      setPausas(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los catálogos");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const guardar = async (accion: () => Promise<unknown>, cerrar: () => void) => {
    setGuardando(true);
    try {
      await accion();
      cerrar();
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const alternar = async (ruta: string, cuerpo: object) => {
    try {
      await api.put(ruta, cuerpo);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar");
    }
  };

  return (
    <div>
      <PageHeader
        title="Pausas y disposiciones"
        subtitle="Lo que el agente elige al pausar y al terminar cada llamada. Vienen con ejemplos: adáptalos a tu operación."
      />
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card className="mb-4">
        <CardHeader
          title="Disposiciones"
          subtitle="La categoría decide qué pasa con el lead"
          actions={<Button onClick={() => setDispo({ ...dispoVacia })}>+ Nueva</Button>}
        />
        {!disposiciones ? (
          <TableSkeleton cols={5} />
        ) : (
          <Table head={["Nombre", "Código", "Categoría", "Activa", ""]}>
            {disposiciones.map((d) => (
              <Tr key={d.id}>
                <Td strong>
                  <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: d.color ?? "var(--line)" }} />
                  {d.nombre}
                </Td>
                <Td mono>{d.codigo}</Td>
                <Td muted>
                  {CATEGORIAS.find((c) => c.value === d.categoria)?.label}
                  {!d.contacto_humano && <span className="ml-2 text-faint">· sin contacto</span>}
                </Td>
                <Td>
                  <Toggle checked={!!d.activa} onChange={(v) => alternar(`/api/contact-center/disposiciones/${d.id}`, { activa: v })} />
                </Td>
                <Td>
                  <RowActions>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setDispo({ id: d.id, codigo: d.codigo, nombre: d.nombre, categoria: d.categoria, color: d.color ?? "#64748b", contacto_humano: d.contacto_humano ?? true })
                      }
                    >
                      Editar
                    </Button>
                  </RowActions>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Códigos de pausa"
          subtitle="Pasado el máximo, el supervisor lo verá en rojo"
          actions={<Button onClick={() => setPausa({ ...pausaVacia })}>+ Nuevo</Button>}
        />
        {!pausas ? (
          <TableSkeleton cols={5} />
        ) : (
          <Table head={["Nombre", "Código", "Máximo", "Activo", ""]}>
            {pausas.map((p) => (
              <Tr key={p.id}>
                <Td strong>
                  {p.nombre}
                  {p.pagada === false && (
                    <span className="ml-2">
                      <Badge color="slate">No pagada</Badge>
                    </span>
                  )}
                </Td>
                <Td mono>{p.codigo}</Td>
                <Td muted>{p.max_minutos ? `${p.max_minutos} min` : "—"}</Td>
                <Td>
                  <Toggle checked={!!p.activo} onChange={(v) => alternar(`/api/contact-center/pausas/${p.id}`, { activo: v })} />
                </Td>
                <Td>
                  <RowActions>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setPausa({ id: p.id, codigo: p.codigo, nombre: p.nombre, pagada: p.pagada ?? true, max_minutos: p.max_minutos ? String(p.max_minutos) : "" })}
                    >
                      Editar
                    </Button>
                  </RowActions>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={dispo !== null}
        onClose={() => setDispo(null)}
        title={dispo?.id ? "Editar disposición" : "Nueva disposición"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDispo(null)}>
              Cancelar
            </Button>
            <Button
              loading={guardando}
              disabled={!dispo?.nombre.trim() || (!dispo?.id && !dispo?.codigo.trim())}
              onClick={() =>
                dispo &&
                guardar(
                  () => {
                    const cuerpo = { nombre: dispo.nombre.trim(), categoria: dispo.categoria, color: dispo.color, contacto_humano: dispo.contacto_humano };
                    return dispo.id
                      ? api.put(`/api/contact-center/disposiciones/${dispo.id}`, cuerpo)
                      : api.post("/api/contact-center/disposiciones", { ...cuerpo, codigo: dispo.codigo.trim() });
                  },
                  () => setDispo(null)
                )
              }
            >
              Guardar
            </Button>
          </>
        }
      >
        {dispo && (
          <div className="space-y-4">
            <Input label="Nombre" value={dispo.nombre} onChange={(v) => setDispo({ ...dispo, nombre: v })} placeholder="Venta cerrada" />
            <Input
              label="Código"
              value={dispo.codigo}
              disabled={!!dispo.id}
              mono
              onChange={(v) => setDispo({ ...dispo, codigo: v.toUpperCase().replace(/[^A-Z0-9_]/g, "_") })}
              hint="Corto, en mayúsculas. Es el que aparece en los reportes; no cambia después."
            />
            <Select
              label="Categoría"
              value={dispo.categoria}
              onChange={(v) => setDispo({ ...dispo, categoria: v as CategoriaDisposicion })}
              options={CATEGORIAS.map((c) => ({ value: c.value, label: `${c.label} — ${c.efecto}` }))}
            />
            <Check
              checked={dispo.contacto_humano}
              onChange={(v) => setDispo({ ...dispo, contacto_humano: v })}
              label="Hubo conversación con una persona (cuenta para la tasa de contacto)"
            />
            <label className="flex items-center gap-3 text-sm text-fg-soft">
              Color
              <input type="color" value={dispo.color} onChange={(e) => setDispo({ ...dispo, color: e.target.value })} />
            </label>
          </div>
        )}
      </Modal>

      <Modal
        open={pausa !== null}
        onClose={() => setPausa(null)}
        title={pausa?.id ? "Editar código de pausa" : "Nuevo código de pausa"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPausa(null)}>
              Cancelar
            </Button>
            <Button
              loading={guardando}
              disabled={!pausa?.nombre.trim() || (!pausa?.id && !pausa?.codigo.trim())}
              onClick={() =>
                pausa &&
                guardar(
                  () => {
                    const cuerpo = { nombre: pausa.nombre.trim(), pagada: pausa.pagada, max_minutos: pausa.max_minutos ? Number(pausa.max_minutos) : null };
                    return pausa.id
                      ? api.put(`/api/contact-center/pausas/${pausa.id}`, cuerpo)
                      : api.post("/api/contact-center/pausas", { ...cuerpo, codigo: pausa.codigo.trim() });
                  },
                  () => setPausa(null)
                )
              }
            >
              Guardar
            </Button>
          </>
        }
      >
        {pausa && (
          <div className="space-y-4">
            <Input label="Nombre" value={pausa.nombre} onChange={(v) => setPausa({ ...pausa, nombre: v })} placeholder="Descanso" />
            <Input
              label="Código"
              value={pausa.codigo}
              disabled={!!pausa.id}
              mono
              onChange={(v) => setPausa({ ...pausa, codigo: v.toUpperCase().replace(/[^A-Z0-9_]/g, "_") })}
            />
            <Input
              label="Máximo (minutos, opcional)"
              type="number"
              value={pausa.max_minutos}
              onChange={(v) => setPausa({ ...pausa, max_minutos: v })}
            />
            <Check checked={pausa.pagada} onChange={(v) => setPausa({ ...pausa, pagada: v })} label="Tiempo pagado" />
          </div>
        )}
      </Modal>
    </div>
  );
}
