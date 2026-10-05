"use client";

import { useState } from "react";

import { Badge, Button, Card, CardHeader, Check, ErrorBanner, Input, Modal, Note, Select, Table, Td, Tr } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { Empresa, NodoFreeswitch } from "@/lib/types";

// Servidores FreeSWITCH de la plataforma y en cuál vive cada empresa
// (opción A de docs/escala.md §4; backend/app/api/nodos.py).

const vacio = { nombre: "", esl_host: "", esl_port: "8021", esl_password: "", sip_host: "", capacidad_agentes: "200", activo: true };

export function nombreServidor(nodos: NodoFreeswitch[], id: number | null): string {
  return nodos.find((n) => n.id === id)?.nombre ?? "principal";
}

export function ServidoresFreeswitch({ nodos, onCambio }: { nodos: NodoFreeswitch[]; onCambio: () => Promise<void> | void }) {
  const [form, setForm] = useState<(typeof vacio & { id: number | null }) | null>(null);
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState("");
  const [prueba, setPrueba] = useState<Record<number, string>>({});

  const hacer = async (clave: string, fn: () => Promise<unknown>) => {
    setTrabajando(clave);
    setError("");
    try {
      await fn();
      await onCambio();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar");
    } finally {
      setTrabajando("");
    }
  };

  const guardar = () =>
    form &&
    hacer("guardar", async () => {
      const cuerpo: Record<string, unknown> = {
        esl_host: form.esl_host.trim(),
        esl_port: Number(form.esl_port),
        sip_host: form.sip_host.trim(),
        capacidad_agentes: Number(form.capacidad_agentes),
        activo: form.activo,
      };
      // Vacía al editar = se deja la que está.
      if (form.esl_password) cuerpo.esl_password = form.esl_password;
      if (form.id === null) await api.post("/api/plataforma/nodos", { ...cuerpo, nombre: form.nombre.trim() });
      else await api.put(`/api/plataforma/nodos/${form.id}`, cuerpo);
      setForm(null);
    });

  const probar = (n: NodoFreeswitch) =>
    hacer(`probar-${n.id}`, async () => {
      const r = await api.post<{ conectado: boolean; version?: string; canales?: number; error?: string }>(`/api/plataforma/nodos/${n.id}/probar`);
      setPrueba((p) => ({
        ...p,
        [n.id as number]: r.conectado ? `Conecta: FreeSWITCH ${r.version ?? ""}, ${r.canales ?? 0} canales` : `No conecta: ${r.error ?? ""}`,
      }));
    });

  const borrar = (n: NodoFreeswitch) => {
    if (!confirm(`¿Borrar el servidor ${n.nombre}?`)) return;
    hacer(`borrar-${n.id}`, () => api.del(`/api/plataforma/nodos/${n.id}`));
  };

  const editar = (n: NodoFreeswitch) =>
    setForm({
      id: n.id,
      nombre: n.nombre,
      esl_host: n.esl_host,
      esl_port: String(n.esl_port),
      esl_password: "",
      sip_host: n.sip_host ?? "",
      capacidad_agentes: String(n.capacidad_agentes ?? 200),
      activo: n.activo,
    });

  const valido =
    !!form &&
    form.esl_host.trim() !== "" &&
    form.sip_host.trim() !== "" &&
    (form.id !== null || (form.nombre.trim().length >= 2 && form.esl_password.length >= 8)) &&
    (form.esl_password === "" || form.esl_password.length >= 8);

  return (
    <Card className="mb-4">
      <CardHeader
        title="Servidores FreeSWITCH"
        subtitle="Cada empresa vive en un servidor. Uno soporta unos 200 agentes en predictivo; al pasar de ahí, agrega otro y mueve empresas."
        actions={
          <Button size="sm" onClick={() => setForm({ ...vacio, id: null })}>
            + Servidor
          </Button>
        }
      />
      {error && (
        <div className="px-4 pt-3">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      <Table head={["Servidor", "Conexión", "Estado", "Empresas", "Agentes", ""]}>
        {nodos.map((n) => {
          const cap = n.capacidad_agentes;
          const lleno = cap != null && n.agentes_conectados >= cap * 0.9;
          return (
            <Tr key={n.id ?? "principal"}>
              <Td strong>
                <div className="flex items-center gap-1.5">
                  {n.nombre}
                  {n.principal && <Badge color="blue">Principal</Badge>}
                  {!n.activo && <Badge color="slate">Desactivado</Badge>}
                </div>
                {n.id !== null && prueba[n.id] && <div className="mt-0.5 text-[11px] font-normal text-faint">{prueba[n.id]}</div>}
              </Td>
              <Td muted>
                <span className="font-mono text-xs">
                  {n.esl_host}:{n.esl_port}
                </span>
                {n.sip_host && <div className="font-mono text-[11px] text-faint">SIP {n.sip_host}</div>}
              </Td>
              <Td>
                {n.conectado ? (
                  <Badge color="green" dot>
                    {n.canales ?? 0} canales
                  </Badge>
                ) : (
                  <span title={n.error}>
                    <Badge color="red" dot>
                      Sin conexión
                    </Badge>
                  </span>
                )}
              </Td>
              <Td>{n.empresas}</Td>
              <Td>
                <span className={lleno ? "font-semibold text-danger-text" : ""}>
                  {n.agentes_conectados}
                  {cap != null && ` / ${cap}`}
                </span>
              </Td>
              <Td>
                {n.id !== null && (
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="ghost" loading={trabajando === `probar-${n.id}`} onClick={() => probar(n)}>
                      Probar
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => editar(n)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" loading={trabajando === `borrar-${n.id}`} onClick={() => borrar(n)}>
                      Borrar
                    </Button>
                  </div>
                )}
              </Td>
            </Tr>
          );
        })}
      </Table>

      <Modal
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id === null ? "Nuevo servidor FreeSWITCH" : `Editar ${form?.nombre ?? ""}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button onClick={guardar} loading={trabajando === "guardar"} disabled={!valido}>
              Guardar
            </Button>
          </>
        }
      >
        {form && (
          <div className="space-y-4">
            {form.id === null && (
              <Input
                label="Nombre"
                value={form.nombre}
                onChange={(v) => setForm({ ...form, nombre: v })}
                required
                mono
                placeholder="fs2"
                hint="Letras, números y guiones. Su carpeta de troncales es FS_CONF/nodos/<nombre>/sip_profiles/external."
              />
            )}
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Input label="Servidor ESL" value={form.esl_host} onChange={(v) => setForm({ ...form, esl_host: v })} required mono placeholder="10.0.0.12" />
              </div>
              <Input label="Puerto" type="number" value={form.esl_port} onChange={(v) => setForm({ ...form, esl_port: v })} />
            </div>
            <Input
              label="Clave ESL"
              type="password"
              value={form.esl_password}
              onChange={(v) => setForm({ ...form, esl_password: v })}
              required={form.id === null}
              hint={form.id === null ? "Mínimo 8 caracteres. Se guarda cifrada." : "Vacía = se deja la que está."}
            />
            <Input
              label="Dirección SIP"
              value={form.sip_host}
              onChange={(v) => setForm({ ...form, sip_host: v })}
              required
              mono
              placeholder="fs2.pbx.ejemplo.com"
              hint="A donde apunta el DNS del dominio SIP de sus empresas (ahí se registran sus teléfonos)."
            />
            <Input
              label="Capacidad (agentes)"
              type="number"
              value={form.capacidad_agentes}
              onChange={(v) => setForm({ ...form, capacidad_agentes: v })}
              hint="Referencia para repartir empresas; la tabla se marca en rojo al pasar del 90 %."
            />
            <Check checked={form.activo} onChange={(v) => setForm({ ...form, activo: v })} label="Activo" />
            {!form.activo && <Note tone="warn">Desactivado no recibe nada: sus empresas pasan a usar el servidor principal.</Note>}
          </div>
        )}
      </Modal>
    </Card>
  );
}

/** Mover una empresa de servidor. Con agentes conectados pide confirmación aparte. */
export function MoverEmpresa({
  empresa,
  nodos,
  onCerrar,
  onCambio,
}: {
  empresa: Empresa | null;
  nodos: NodoFreeswitch[];
  onCerrar: () => void;
  onCambio: () => Promise<void> | void;
}) {
  const [destino, setDestino] = useState<string>("");
  const [error, setError] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);
  const [moviendo, setMoviendo] = useState(false);
  const [abierta, setAbierta] = useState<number | null>(null);

  // Al abrir otra empresa, arranca desde su servidor actual.
  if (empresa && abierta !== empresa.id) {
    setAbierta(empresa.id);
    setDestino(empresa.nodo_id === null ? "" : String(empresa.nodo_id));
    setError("");
    setAvisos([]);
  }

  const cerrar = () => {
    setAbierta(null);
    onCerrar();
  };

  const mover = async (forzar = false) => {
    if (!empresa) return;
    setMoviendo(true);
    setError("");
    try {
      const r = await api.put<{ cambio: boolean; avisos?: string[] }>(`/api/plataforma/nodos/empresas/${empresa.id}`, {
        nodo_id: destino === "" ? null : Number(destino),
        forzar,
      });
      setAvisos(r.avisos ?? []);
      await onCambio();
      if (!r.cambio) cerrar();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !forzar && e.message.includes("conectados")) {
        if (confirm(`${e.message}.\n\nSus agentes perderán la sesión y tendrán que volver a entrar. ¿Mover igual?`)) {
          setMoviendo(false);
          return mover(true);
        }
      } else {
        setError(e instanceof Error ? e.message : "No se pudo mover");
      }
    } finally {
      setMoviendo(false);
    }
  };

  const opciones = nodos
    .filter((n) => n.activo)
    .map((n) => ({ value: n.id === null ? "" : String(n.id), label: `${n.nombre} (${n.agentes_conectados}${n.capacidad_agentes ? ` / ${n.capacidad_agentes}` : ""} agentes)` }));

  return (
    <Modal
      open={!!empresa}
      onClose={cerrar}
      title={`Servidor de ${empresa?.name ?? ""}`}
      footer={
        avisos.length ? (
          <Button onClick={cerrar}>Entendido</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={cerrar}>
              Cancelar
            </Button>
            <Button onClick={() => mover()} loading={moviendo} disabled={!empresa || destino === (empresa.nodo_id === null ? "" : String(empresa.nodo_id))}>
              Mover
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {avisos.length ? (
          <Note tone="warn">
            <div className="font-medium">Empresa movida. Falta:</div>
            <ul className="mt-1 list-disc pl-4">
              {avisos.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </Note>
        ) : (
          <>
            <Select label="Servidor" value={destino} onChange={setDestino} options={opciones} />
            <Note tone="muted">
              Sus troncales pasan al servidor nuevo y se registran ahí. Sus teléfonos y softphones tienen que registrarse en el
              servidor nuevo: cambia el DNS de su dominio SIP ({empresa?.sip_domain}). Hazlo fuera de la jornada.
            </Note>
          </>
        )}
      </div>
    </Modal>
  );
}
