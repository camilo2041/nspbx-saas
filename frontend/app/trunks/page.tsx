"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  Note,
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
import { useAuth } from "@/lib/auth";
import { Trunk, TrunkStatus } from "@/lib/types";

const empty = {
  name: "",
  gateway_host: "",
  gateway_port: 5060,
  username: "",
  password: "",
  from_domain: "",
  register_enabled: true,
  caller_id_number: "",
  transport: "udp",
  ping: "",
  codec_prefs: "",
  enabled: true,
};

// Estados de FreeSWITCH (REGED, FAIL_WAIT…) dichos en palabras.
function statusBadgeFor(state: string | null | undefined): { color: string; label: string; detalle: string } {
  if (!state) return { color: "slate", label: "Sin datos", detalle: "No se pudo preguntar a la central." };
  if (state === "REGED") return { color: "green", label: "Conectado", detalle: "El proveedor aceptó usuario y clave." };
  if (state === "NOREG") return { color: "green", label: "Activo (por IP)", detalle: "Sin registro: el proveedor reconoce tu servidor por su IP." };
  if (state === "TRYING" || state === "REGISTER")
    return { color: "amber", label: "Conectando…", detalle: "Esperando respuesta del proveedor." };
  if (state === "FAILED" || state === "FAIL_WAIT")
    return {
      color: "red",
      label: "No conecta",
      detalle: "El proveedor rechazó el usuario o la clave, o el servidor no responde. Revisa los datos que te dio el proveedor.",
    };
  if (state === "DOWN") return { color: "red", label: "Caído", detalle: "El proveedor no responde." };
  return { color: "slate", label: state, detalle: "" };
}

export default function TrunksPage() {
  const [items, setItems] = useState<Trunk[]>([]);
  const [statuses, setStatuses] = useState<Record<number, TrunkStatus>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Trunk | null>(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState<number | null>(null);
  const [prueba, setPrueba] = useState<{ cargando: boolean; estado?: string | null } | null>(null);
  const { usuario } = useAuth();
  const [celular, setCelular] = useState("");
  const [llamada, setLlamada] = useState<{ cargando: boolean; texto?: string; ok?: boolean } | null>(null);

  // «Llamada de prueba»: la central hace sonar TU extensión y, al
  // contestar, marca el número por este proveedor (click-to-call). Si se oye
  // bien en los dos lados, el proveedor funciona de punta a punta.
  const llamarPrueba = async (trunk: Trunk) => {
    if (!usuario?.extension_id) return;
    setLlamada({ cargando: true });
    try {
      await api.post(`/api/extensions/${usuario.extension_id}/call`, { destination: celular.trim(), trunk_id: trunk.id });
      setLlamada({
        cargando: false,
        ok: true,
        texto: `Contesta en tu extensión ${usuario.extension_number}: al hacerlo, la central marcará ${celular.trim()} por ${trunk.name}.`,
      });
    } catch (e) {
      setLlamada({ cargando: false, ok: false, texto: e instanceof Error ? e.message : "No se pudo llamar" });
    }
  };

  const loadStatuses = useCallback(async (trunks: Trunk[]) => {
    const entries = await Promise.all(
      trunks
        .filter((t) => t.enabled)
        .map(async (t) => {
          try {
            return [t.id, await api.get<TrunkStatus>(`/api/trunks/${t.id}/status`)] as const;
          } catch {
            return [t.id, { state: null, status: null, ping_ms: null }] as const;
          }
        })
    );
    setStatuses(Object.fromEntries(entries));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const trunks = await api.get<Trunk[]>("/api/trunks");
      setItems(trunks);
      setError("");
      loadStatuses(trunks);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [loadStatuses]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setPrueba(null);
    setModal(true);
  };

  // «Probar conexión»: vuelve a cargar la troncal en la central y espera a
  // que el proveedor responda (el registro tarda unos segundos).
  const probar = async (trunk: Trunk) => {
    setPrueba({ cargando: true });
    try {
      await api.post(`/api/trunks/${trunk.id}/rescan`);
      let st: TrunkStatus | null = null;
      for (let i = 0; i < 6; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        st = await api.get<TrunkStatus>(`/api/trunks/${trunk.id}/status`);
        if (st.state === "REGED" || st.state === "NOREG" || st.state === "FAIL_WAIT" || st.state === "FAILED") break;
      }
      setPrueba({ cargando: false, estado: st?.state ?? null });
      setStatuses((prev) => (st ? { ...prev, [trunk.id]: st } : prev));
    } catch (e) {
      setPrueba(null);
      setError(e instanceof Error ? e.message : "No se pudo probar");
    }
  };

  const openEdit = (trunk: Trunk) => {
    setEditing(trunk);
    setPrueba(null);
    setForm({
      name: trunk.name,
      gateway_host: trunk.gateway_host,
      gateway_port: trunk.gateway_port,
      username: trunk.username ?? "",
      password: trunk.password ?? "",
      from_domain: trunk.from_domain ?? "",
      register_enabled: trunk.register_enabled,
      caller_id_number: trunk.caller_id_number ?? "",
      transport: trunk.transport,
      ping: trunk.ping != null ? String(trunk.ping) : "",
      codec_prefs: trunk.codec_prefs ?? "",
      enabled: trunk.enabled,
    });
    setModal(true);
  };

  const save = async () => {
    try {
      const payload = {
        ...form,
        ping: form.ping ? Number(form.ping) : null,
        caller_id_number: form.caller_id_number || null,
        codec_prefs: form.codec_prefs || null,
      };
      if (editing) {
        await api.put(`/api/trunks/${editing.id}`, payload);
      } else {
        await api.post("/api/trunks", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    }
  };

  const remove = async (trunk: Trunk) => {
    if (!confirm(`¿Eliminar el proveedor ${trunk.name}? Las llamadas dejarán de salir y entrar por él.`)) return;
    try {
      await api.del(`/api/trunks/${trunk.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const rescan = async (trunk: Trunk) => {
    setBusy(trunk.id);
    try {
      const res = await api.post<{ ok: boolean }>(`/api/trunks/${trunk.id}/rescan`);
      setError(res.ok ? "" : "Rescan devolvió error");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al rescan");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Proveedor de telefonía"
        subtitle="La línea por la que entran y salen tus llamadas (Claro, Tigo, ETB, Movistar…). Término técnico: troncal SIP."
        actions={<Button guia="proveedores:nuevo" onClick={openCreate}>+ Conectar proveedor</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Tus proveedores" subtitle={`${items.length} conectado(s)`} />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Todavía no conectas un proveedor"
            hint="Pide a tu proveedor de telefonía el servidor, el usuario y la clave de tu línea SIP, y conéctala aquí."
            action={<Button onClick={openCreate}>+ Conectar proveedor</Button>}
          />
        ) : (
          <Table head={["Nombre", "Servidor", "Acceso", "Estado", "Activo", { label: "Acciones", align: "right" }]}>
            {items.map((trunk, i) => {
              const st = statuses[trunk.id];
              const sb = statusBadgeFor(st?.state);
              return (
                <Tr key={trunk.id} delay={i * 35}>
                  <Td strong>{trunk.name}</Td>
                  <Td mono>
                    {trunk.gateway_host}:{trunk.gateway_port}
                    {trunk.transport !== "udp" && (
                      <span className="ml-1 font-sans text-xs text-faint">({trunk.transport.toUpperCase()})</span>
                    )}
                  </Td>
                  <Td muted>
                    {trunk.username ? (
                      <span
                        title={trunk.register_enabled ? "Se registra en el proveedor" : "Solo autentica, sin registro"}
                      >
                        {trunk.username} {trunk.register_enabled ? "· usuario y clave" : "· sin registro"}
                      </span>
                    ) : (
                      <span title="Sin credenciales: autenticación por IP">Por IP</span>
                    )}
                  </Td>
                  <Td>
                    {trunk.enabled ? (
                      <span title={sb.detalle}>
                        <Badge color={sb.color} dot pulse={sb.color === "amber"}>
                          {sb.label}
                        </Badge>
                      </span>
                    ) : (
                      <Badge color="slate">—</Badge>
                    )}
                  </Td>
                  <Td>{trunk.enabled ? <Badge color="green">Sí</Badge> : <Badge color="red">No</Badge>}</Td>
                  <Td align="right">
                    <RowActions>
                      <Button size="sm" variant="secondary" onClick={() => rescan(trunk)} loading={busy === trunk.id}>
                        {busy === trunk.id ? "Reconectando…" : "Reconectar"}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => openEdit(trunk)}>
                        Editar
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => remove(trunk)}>
                        Eliminar
                      </Button>
                    </RowActions>
                  </Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar proveedor ${editing.name}` : "Conectar proveedor de telefonía"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save}>{editing ? "Guardar" : "Conectar"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          {!editing && (
            <Note tone="brand">
              Tu proveedor te da estos datos al contratar la línea: <b>servidor</b>, <b>usuario</b> y <b>clave</b>. Si no los
              tienes, pídeselos como «datos de la troncal SIP».
            </Note>
          )}
          <Input
            label="Nombre"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="claro, tigo, linea-principal…"
            hint="Para reconocerlo en el panel. Sin espacios ni tildes: letras, números, punto, guion."
            required
          />
          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">¿Cómo te conecta tu proveedor?</span>
            <div className="grid grid-cols-2 gap-2">
              {[
                { porIp: false, titulo: "Con usuario y clave", detalle: "Lo más común." },
                { porIp: true, titulo: "Por IP", detalle: "El proveedor reconoce tu servidor; no hay usuario." },
              ].map((o) => {
                const activo = (form.username.trim() === "" && !form.register_enabled) === o.porIp;
                return (
                  <button
                    key={o.titulo}
                    type="button"
                    aria-pressed={activo}
                    onClick={() =>
                      setForm(
                        o.porIp
                          ? { ...form, username: "", password: "", register_enabled: false }
                          : { ...form, register_enabled: true }
                      )
                    }
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      activo ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                    }`}
                  >
                    <span className="block text-sm font-semibold text-fg">{o.titulo}</span>
                    <span className="mt-0.5 block text-xs text-muted">{o.detalle}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <Input
            label="Servidor del proveedor"
            value={form.gateway_host}
            onChange={(v) => setForm({ ...form, gateway_host: v })}
            placeholder="sip.proveedor.com o 200.1.2.3"
            hint="Dominio o IP que te dio el proveedor (técnico: host del gateway)."
            required
            mono
          />
          {!(form.username.trim() === "" && !form.register_enabled) && (
            <div className="grid grid-cols-2 gap-2">
              <Input label="Usuario" value={form.username} onChange={(v) => setForm({ ...form, username: v })} mono />
              <Input label="Clave" value={form.password} onChange={(v) => setForm({ ...form, password: v })} />
            </div>
          )}
          <Input
            label="Tu número para llamar afuera (opcional)"
            value={form.caller_id_number}
            onChange={(v) => setForm({ ...form, caller_id_number: v })}
            placeholder="6011234567"
            mono
            hint="El número que verá quien contestes, si tu proveedor te lo tiene autorizado. Muchos proveedores muestran siempre el número de la cuenta, pongas lo que pongas aquí."
          />
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Activo</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>

          {editing && (
            <div className="rounded-xl border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-fg-soft">¿Conecta con el proveedor?</span>
                <Button size="sm" variant="secondary" onClick={() => probar(editing)} loading={prueba?.cargando}>
                  {prueba?.cargando ? "Probando…" : "Probar conexión"}
                </Button>
              </div>
              {prueba && !prueba.cargando && (
                <p className={`mt-2 text-sm ${prueba.estado === "REGED" || prueba.estado === "NOREG" ? "text-ok-text" : "text-danger-text"}`}>
                  <b>{statusBadgeFor(prueba.estado).label}.</b> {statusBadgeFor(prueba.estado).detalle}
                </p>
              )}
              <p className="mt-1 text-xs text-muted">Guarda los cambios antes de probar.</p>

              <div className="mt-3 border-t border-line pt-3">
                <span className="text-sm text-fg-soft">Llamada de prueba</span>
                {usuario?.extension_id ? (
                  <>
                    <p className="mt-0.5 text-xs text-muted">
                      Primero suena tu extensión {usuario.extension_number} (ten el softphone abierto); al contestar, la central
                      llama a este número por este proveedor.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <div className="flex-1">
                        <Input label="Tu celular" value={celular} onChange={setCelular} placeholder="3001234567" mono />
                      </div>
                      <div className="self-end">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => llamarPrueba(editing)}
                          loading={llamada?.cargando}
                          disabled={celular.trim().length < 7}
                        >
                          Llamar
                        </Button>
                      </div>
                    </div>
                    {llamada?.texto && (
                      <p className={`mt-2 text-sm ${llamada.ok ? "text-ok-text" : "text-danger-text"}`}>{llamada.texto}</p>
                    )}
                  </>
                ) : (
                  <p className="mt-0.5 text-xs text-muted">
                    Para hacerla necesitas una extensión: asígnatela en Usuarios (editándote) y abre el Softphone.
                  </p>
                )}
              </div>
            </div>
          )}
          {!editing && <p className="text-xs text-muted">Al conectarlo verás en la lista si el proveedor lo aceptó.</p>}

          <details className="rounded-xl border border-line">
            <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium text-fg-soft">
              Opciones avanzadas <span className="text-xs font-normal text-muted">(solo si tu proveedor lo pide)</span>
            </summary>
            <div className="space-y-4 border-t border-line p-3">
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label="Puerto"
                  type="number"
                  value={form.gateway_port}
                  onChange={(v) => setForm({ ...form, gateway_port: Number(v) })}
                  hint="Casi siempre 5060."
                />
                <Select
                  label="Transporte"
                  value={form.transport}
                  onChange={(v) => setForm({ ...form, transport: v })}
                  options={[
                    { value: "udp", label: "UDP (normal)" },
                    { value: "tcp", label: "TCP" },
                    { value: "tls", label: "TLS (cifrado)" },
                  ]}
                />
              </div>
              <Input
                label="Dominio de origen (From domain)"
                value={form.from_domain}
                onChange={(v) => setForm({ ...form, from_domain: v })}
                hint="Vacío casi siempre. Algunos proveedores piden su dominio aquí."
                mono
              />
              {!(form.username.trim() === "" && !form.register_enabled) && (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                  <span className="text-sm text-fg-soft">
                    Registrarse en el proveedor
                    <span className="mt-0.5 block text-xs text-faint">
                      Lo normal con usuario y clave. Apágalo solo si el proveedor dice que no hay que registrarse.
                    </span>
                  </span>
                  <Toggle checked={form.register_enabled} onChange={(v) => setForm({ ...form, register_enabled: v })} />
                </div>
              )}
              <Input
                label="Comprobar la conexión cada (segundos)"
                type="number"
                value={form.ping}
                onChange={(v) => setForm({ ...form, ping: v })}
                placeholder="30 — vacío = no comprobar"
                hint="Detecta si el proveedor deja de responder (técnico: OPTIONS / qualify)."
              />
              <Input
                label="Códecs preferidos"
                value={form.codec_prefs}
                onChange={(v) => setForm({ ...form, codec_prefs: v })}
                placeholder="PCMU,PCMA,G729"
                hint="Vacío = los de siempre. Solo si el proveedor exige alguno."
                mono
              />
            </div>
          </details>
        </div>
      </Modal>
    </div>
  );
}
