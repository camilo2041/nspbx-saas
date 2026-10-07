"use client";

import { useCallback, useEffect, useState } from "react";

import { FichaContacto } from "@/components/crm/ficha-contacto";
import { DatosContacto, FormularioContacto, contactoVacio, cuerpoDe } from "@/components/crm/formulario-contacto";
import { ImportarCsv } from "@/components/crm/importar-csv";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Check,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  PageHeader,
  Pagination,
  RowActions,
  SearchInput,
  Segmented,
  Select,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CampoContacto, Contacto, PERMISOS, RegistroNoLlamar, TipoCampo } from "@/lib/types";

type Pestana = "contactos" | "importar" | "no_llamar" | "campos";
const POR_PAGINA = 50;

function fecha(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" });
}

export default function CrmPage() {
  const { puede } = useAuth();
  const gestiona = puede(PERMISOS.crmGestionar);
  const [pestana, setPestana] = useState<Pestana>("contactos");
  const [campos, setCampos] = useState<CampoContacto[]>([]);
  const [version, setVersion] = useState(0);

  const cargarCampos = useCallback(async () => {
    try {
      setCampos(await api.get<CampoContacto[]>("/api/crm/campos"));
    } catch {
      setCampos([]);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargarCampos();
  }, [cargarCampos]);

  return (
    <div>
      <PageHeader
        title="Contactos"
        subtitle="El CRM de la empresa: cada cliente una sola vez, con su historial de llamadas, campañas, cobranza y citas."
      />
      <div className="mb-4 max-w-xl">
        <Segmented
          guia="crm"
          value={pestana}
          onChange={setPestana}
          options={[
            { value: "contactos", label: "Contactos" },
            { value: "importar", label: "Importar", disabled: !gestiona, title: gestiona ? undefined : "Tu rol no puede importar" },
            { value: "no_llamar", label: "No llamar" },
            { value: "campos", label: "Campos" },
          ]}
        />
      </div>
      {pestana === "contactos" && <Contactos campos={campos} gestiona={gestiona} version={version} />}
      {pestana === "importar" && gestiona && <ImportarCsv campos={campos} onImportado={() => setVersion((v) => v + 1)} />}
      {pestana === "no_llamar" && <NoLlamar gestiona={gestiona} />}
      {pestana === "campos" && <Campos campos={campos} gestiona={gestiona} onCambio={cargarCampos} />}
    </div>
  );
}

function Contactos({ campos, gestiona, version }: { campos: CampoContacto[]; gestiona: boolean; version: number }) {
  const [items, setItems] = useState<Contacto[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [abierto, setAbierto] = useState<number | null>(null);
  const [nuevo, setNuevo] = useState<DatosContacto | null>(null);
  const [guardando, setGuardando] = useState(false);

  // Desde la ficha de quien llama (components/ficha-cliente.tsx):
  // ?contacto=<id> abre la ficha; ?nuevo=<teléfono> abre «Nuevo» con el número.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const id = Number(p.get("contacto"));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (id > 0) setAbierto(id);
    const tel = p.get("nuevo");
    if (tel && gestiona) setNuevo({ ...contactoVacio, telefono: tel.slice(0, 40) });
  }, [gestiona]);

  const cargar = useCallback(async (busqueda: string, desde: number) => {
    setCargando(true);
    try {
      const qs = new URLSearchParams({ limit: String(POR_PAGINA), offset: String(desde) });
      if (busqueda.trim()) qs.set("q", busqueda.trim());
      const r = await api.get<{ total: number; contactos: Contacto[] }>(`/api/crm/contactos?${qs}`);
      setItems(r.contactos);
      setTotal(r.total);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los contactos");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => cargar(q, offset), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [cargar, q, offset, version]);

  const crear = async () => {
    if (!nuevo) return;
    setGuardando(true);
    try {
      const c = await api.post<Contacto>("/api/crm/contactos", cuerpoDe(nuevo, campos));
      setNuevo(null);
      await cargar(q, offset);
      setAbierto(c.id);
    } catch (e) {
      // 409: ya existe con ese teléfono → se abre el existente.
      if (e instanceof ApiError && e.status === 409) {
        try {
          const id = JSON.parse(e.message).contacto_id as number;
          setNuevo(null);
          setAbierto(id);
          return;
        } catch {
          /* cae al error genérico */
        }
      }
      setError(e instanceof Error ? e.message : "No se pudo crear el contacto");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      <Card>
        <CardHeader
          title="Contactos"
          subtitle={`${total} en total`}
          actions={
            <div className="flex items-center gap-2">
              <SearchInput
                value={q}
                onChange={(v) => {
                  setQ(v);
                  setOffset(0);
                }}
                placeholder="Nombre, documento, teléfono…"
                className="w-64"
              />
              {gestiona && <Button guia="crm:nuevo" onClick={() => setNuevo({ ...contactoVacio })}>+ Nuevo</Button>}
            </div>
          }
        />
        {cargando && items.length === 0 ? (
          <TableSkeleton cols={5} />
        ) : items.length === 0 ? (
          <EmptyState
            title={q ? "Sin coincidencias" : "Todavía no hay contactos"}
            hint={q ? "Prueba con otra parte del nombre o del teléfono." : "Se crean solos al cargar números en una campaña, o impórtalos desde un CSV."}
          />
        ) : (
          <>
            <Table head={["Nombre", "Teléfono", "Documento", "Ciudad", "Actualizado"]}>
              {items.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => setAbierto(c.id)}
                  className="cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-brand-soft/40"
                >
                  <Td strong>
                    {c.nombre || <span className="text-faint">Sin nombre</span>}
                    {c.no_llamar && (
                      <span className="ml-2">
                        <Badge color="red">No llamar</Badge>
                      </span>
                    )}
                  </Td>
                  <Td mono>{c.telefono}</Td>
                  <Td mono>{c.documento ?? "—"}</Td>
                  <Td muted>{c.ciudad ?? "—"}</Td>
                  <Td muted>{fecha(c.updated_at)}</Td>
                </tr>
              ))}
            </Table>
            <Pagination offset={offset} limit={POR_PAGINA} recibidos={items.length} onChange={setOffset} cargando={cargando} />
          </>
        )}
      </Card>

      <FichaContacto contactoId={abierto} onClose={() => setAbierto(null)} onCambio={() => cargar(q, offset)} />

      <Modal
        open={nuevo !== null}
        onClose={() => setNuevo(null)}
        size="lg"
        title="Nuevo contacto"
        footer={
          <>
            <Button variant="secondary" onClick={() => setNuevo(null)}>
              Cancelar
            </Button>
            <Button onClick={crear} loading={guardando} disabled={!nuevo?.telefono.trim()}>
              Crear
            </Button>
          </>
        }
      >
        {nuevo && <FormularioContacto datos={nuevo} onChange={setNuevo} defs={campos} />}
      </Modal>
    </>
  );
}

function NoLlamar({ gestiona }: { gestiona: boolean }) {
  const [items, setItems] = useState<RegistroNoLlamar[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ telefono: "", motivo: "", hasta: "" });
  const [guardando, setGuardando] = useState(false);

  const cargar = useCallback(async (busqueda: string) => {
    try {
      const qs = busqueda.trim() ? `?q=${encodeURIComponent(busqueda.trim())}` : "";
      const r = await api.get<{ total: number; registros: RegistroNoLlamar[] }>(`/api/crm/no-llamar${qs}`);
      setItems(r.registros);
      setTotal(r.total);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la lista");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => cargar(q), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [cargar, q]);

  const agregar = async () => {
    setGuardando(true);
    try {
      await api.post("/api/crm/no-llamar", {
        telefono: form.telefono.trim(),
        motivo: form.motivo.trim() || null,
        hasta: form.hasta ? `${form.hasta}T23:59:59` : null,
      });
      setForm({ telefono: "", motivo: "", hasta: "" });
      await cargar(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo agregar");
    } finally {
      setGuardando(false);
    }
  };

  const quitar = async (r: RegistroNoLlamar) => {
    if (!window.confirm(`¿Quitar ${r.telefono} de la lista de no llamar? Las campañas podrán volver a marcarlo.`)) return;
    try {
      await api.del(`/api/crm/no-llamar/${r.id}`);
      await cargar(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo quitar");
    }
  };

  return (
    <>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      {gestiona && (
        <Card className="mb-4">
          <CardHeader
            title="Agregar a no llamar"
            subtitle="Ninguna campaña marca estos números (en ninguna de sus formas: con o sin +57). Si pones fecha, vuelve a valer después."
          />
          <div className="grid items-end gap-3 p-5 sm:grid-cols-[1fr_2fr_1fr_auto]">
            <Input label="Teléfono" value={form.telefono} onChange={(v) => setForm({ ...form, telefono: v })} mono />
            <Input label="Motivo (opcional)" value={form.motivo} onChange={(v) => setForm({ ...form, motivo: v })} />
            <Input label="Hasta (opcional)" type="date" value={form.hasta} onChange={(v) => setForm({ ...form, hasta: v })} />
            <Button onClick={agregar} loading={guardando} disabled={!form.telefono.trim()}>
              Agregar
            </Button>
          </div>
        </Card>
      )}
      <Card>
        <CardHeader
          title="Lista de no llamar"
          subtitle={`${total} número(s)`}
          actions={<SearchInput value={q} onChange={setQ} placeholder="Buscar teléfono…" />}
        />
        {cargando ? (
          <TableSkeleton cols={5} />
        ) : items.length === 0 ? (
          <EmptyState title="La lista está vacía" hint="Agrega aquí a quien pidió que no lo llamen." />
        ) : (
          <Table head={["Teléfono", "Motivo", "Vigencia", "Agregado por", ""]}>
            {items.map((r) => (
              <Tr key={r.id}>
                <Td mono>{r.telefono}</Td>
                <Td muted>{r.motivo ?? "—"}</Td>
                <Td>
                  {r.vigente ? (
                    <Badge color="red">{r.hasta ? `Hasta ${fecha(r.hasta)}` : "Siempre"}</Badge>
                  ) : (
                    <Badge color="slate">Venció {fecha(r.hasta)}</Badge>
                  )}
                </Td>
                <Td muted>
                  {r.creado_por ?? "—"} · {fecha(r.created_at)}
                </Td>
                <Td>
                  {gestiona && (
                    <RowActions>
                      <Button size="sm" variant="ghost" onClick={() => quitar(r)}>
                        Quitar
                      </Button>
                    </RowActions>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

const TIPOS: { value: TipoCampo; label: string }[] = [
  { value: "texto", label: "Texto" },
  { value: "numero", label: "Número" },
  { value: "fecha", label: "Fecha" },
  { value: "opciones", label: "Lista de opciones" },
  { value: "si_no", label: "Sí / No" },
];

const campoVacio = { id: 0, clave: "", nombre: "", tipo: "texto" as TipoCampo, opciones: "", obligatorio: false };

function Campos({ campos, gestiona, onCambio }: { campos: CampoContacto[]; gestiona: boolean; onCambio: () => void }) {
  const [form, setForm] = useState<typeof campoVacio | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  const guardar = async () => {
    if (!form) return;
    setGuardando(true);
    try {
      const cuerpo = {
        nombre: form.nombre.trim(),
        tipo: form.tipo,
        opciones: form.tipo === "opciones" ? form.opciones.split(",").map((o) => o.trim()).filter(Boolean) : null,
        obligatorio: form.obligatorio,
      };
      if (form.id) await api.put(`/api/crm/campos/${form.id}`, cuerpo);
      else await api.post("/api/crm/campos", { ...cuerpo, clave: form.clave.trim() });
      setForm(null);
      onCambio();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar el campo");
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (c: CampoContacto) => {
    if (!window.confirm(`¿Borrar el campo «${c.nombre}»? Deja de pedirse y de mostrarse en los contactos.`)) return;
    try {
      await api.del(`/api/crm/campos/${c.id}`);
      onCambio();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar");
    }
  };

  return (
    <>
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      <Card>
        <CardHeader
          title="Campos propios"
          subtitle="Lo que tu operación necesita guardar de cada cliente (plan, saldo, sede…). Se piden al crear, se validan al importar y aparecen en la ficha."
          actions={gestiona ? <Button onClick={() => setForm({ ...campoVacio })}>+ Nuevo campo</Button> : undefined}
        />
        {campos.length === 0 ? (
          <EmptyState title="Sin campos propios" hint="Los contactos ya traen nombre, documento, teléfonos, correo, dirección y ciudad." />
        ) : (
          <Table head={["Nombre", "Clave", "Tipo", "Obligatorio", ""]}>
            {campos.map((c) => (
              <Tr key={c.id}>
                <Td strong>{c.nombre}</Td>
                <Td mono>{c.clave}</Td>
                <Td muted>
                  {TIPOS.find((t) => t.value === c.tipo)?.label}
                  {c.tipo === "opciones" && `: ${c.opciones.join(", ")}`}
                </Td>
                <Td>{c.obligatorio ? <Badge color="amber">Sí</Badge> : <span className="text-faint">No</span>}</Td>
                <Td>
                  {gestiona && (
                    <RowActions>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          setForm({ id: c.id, clave: c.clave, nombre: c.nombre, tipo: c.tipo, opciones: c.opciones.join(", "), obligatorio: c.obligatorio })
                        }
                      >
                        Editar
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => borrar(c)}>
                        Borrar
                      </Button>
                    </RowActions>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={form !== null}
        onClose={() => setForm(null)}
        title={form?.id ? "Editar campo" : "Nuevo campo"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button onClick={guardar} loading={guardando} disabled={!form?.nombre.trim() || (!form?.id && !form?.clave.trim())}>
              Guardar
            </Button>
          </>
        }
      >
        {form && (
          <div className="space-y-4">
            <Input label="Nombre" value={form.nombre} onChange={(v) => setForm({ ...form, nombre: v })} placeholder="Plan contratado" />
            <Input
              label="Clave"
              value={form.clave}
              disabled={!!form.id}
              mono
              onChange={(v) => setForm({ ...form, clave: v.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
              placeholder="plan"
              hint="Con la que se guarda y se nombra la columna al importar. No cambia después."
            />
            <Select label="Tipo" value={form.tipo} onChange={(v) => setForm({ ...form, tipo: v as TipoCampo })} options={TIPOS} />
            {form.tipo === "opciones" && (
              <Input
                label="Opciones (separadas por coma)"
                value={form.opciones}
                onChange={(v) => setForm({ ...form, opciones: v })}
                placeholder="Oro, Plata, Bronce"
              />
            )}
            <Check checked={form.obligatorio} onChange={(v) => setForm({ ...form, obligatorio: v })} label="Obligatorio" />
          </div>
        )}
      </Modal>
    </>
  );
}
