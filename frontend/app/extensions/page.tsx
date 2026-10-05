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
import { Extension, SystemSettings, Trunk } from "@/lib/types";

const empty: Omit<Extension, "id" | "created_at"> = {
  number: "",
  password: "",
  caller_id_name: "",
  voicemail: true,
  enabled: true,
  outbound_after_hours: false,
};

const emptyCall = { destination: "", trunk_id: "" };

export default function ExtensionsPage() {
  const [items, setItems] = useState<Extension[]>([]);
  const [trunks, setTrunks] = useState<Trunk[]>([]);
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [softphoneExt, setSoftphoneExt] = useState<Extension | null>(null);
  const [copied, setCopied] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Extension | null>(null);
  const [form, setForm] = useState(empty);
  const [reloading, setReloading] = useState(false);

  const [callModal, setCallModal] = useState<Extension | null>(null);
  const [callForm, setCallForm] = useState(emptyCall);
  const [calling, setCalling] = useState(false);
  const [callResult, setCallResult] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [exts, trs, settingsRes] = await Promise.all([
        api.get<Extension[]>("/api/extensions"),
        api.get<Trunk[]>("/api/trunks"),
        api.get<SystemSettings>("/api/system/settings"),
      ]);
      setItems(exts);
      setTrunks(trs);
      setSettings(settingsRes);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setModal(true);
  };

  const openEdit = (ext: Extension) => {
    setEditing(ext);
    setForm({ ...ext });
    setModal(true);
  };

  const save = async () => {
    try {
      if (editing) {
        await api.put(`/api/extensions/${editing.id}`, form);
      } else {
        await api.post("/api/extensions", form);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    }
  };

  const remove = async (ext: Extension) => {
    if (!confirm(`¿Eliminar la extensión ${ext.number}?`)) return;
    try {
      await api.del(`/api/extensions/${ext.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const reload = async () => {
    setReloading(true);
    try {
      await api.post<{ ok: boolean }>("/api/extensions/reload");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al recargar");
    } finally {
      setReloading(false);
    }
  };

  const openCall = (ext: Extension) => {
    setCallModal(ext);
    setCallForm(emptyCall);
    setCallResult("");
  };

  const placeCall = async () => {
    if (!callModal) return;
    setCalling(true);
    setCallResult("");
    try {
      await api.post(`/api/extensions/${callModal.id}/call`, {
        destination: callForm.destination,
        trunk_id: callForm.trunk_id ? Number(callForm.trunk_id) : null,
      });
      setCallResult(`Marcando ${callModal.number} → ${callForm.destination}… contesta la extensión para que se conecte.`);
    } catch (e) {
      setCallResult(e instanceof Error ? e.message : "Error al originar la llamada");
    } finally {
      setCalling(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Extensiones"
        subtitle="Cuentas SIP que se conectan con un softphone o teléfono IP"
        actions={
          <>
            <Button variant="secondary" onClick={reload} loading={reloading}>
              {reloading ? "Recargando…" : "Recargar en FreeSWITCH"}
            </Button>
            <Button onClick={openCreate}>+ Nueva extensión</Button>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Lista de extensiones" subtitle={`${items.length} registrada(s)`} />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay extensiones"
            hint="Crea la primera para dar de alta un teléfono o softphone."
            action={<Button onClick={openCreate}>+ Nueva extensión</Button>}
          />
        ) : (
          <Table
            head={["Número", "Nombre", "Password", "Buzón", "Estado", { label: "Acciones", align: "right" }]}
          >
            {items.map((ext, i) => (
              <Tr key={ext.id} delay={i * 35}>
                <Td mono strong>
                  {ext.number}
                </Td>
                <Td>{ext.caller_id_name || "—"}</Td>
                <Td mono muted>
                  {ext.password}
                </Td>
                <Td>{ext.voicemail ? <Badge color="blue">Sí</Badge> : <Badge color="slate">No</Badge>}</Td>
                <Td>
                  {ext.enabled ? (
                    <Badge color="green" dot>
                      Activa
                    </Badge>
                  ) : (
                    <Badge color="red" dot>
                      Inactiva
                    </Badge>
                  )}
                </Td>
                <Td align="right">
                  <RowActions>
                    <Button size="sm" variant="success" onClick={() => openCall(ext)} disabled={!ext.enabled}>
                      Llamar
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => setSoftphoneExt(ext)}>
                      Softphone
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => openEdit(ext)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(ext)}>
                      Eliminar
                    </Button>
                  </RowActions>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar extensión ${editing.number}` : "Nueva extensión"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save}>{editing ? "Guardar" : "Crear"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Número" value={form.number} onChange={(v) => setForm({ ...form, number: v })} required mono />
          <Input
            label="Password"
            value={form.password}
            onChange={(v) => setForm({ ...form, password: v })}
            hint="Vacía = se genera una segura. Mínimo 12 caracteres, no solo números ni el número de la extensión."
          />
          <Input
            label="Nombre (Caller ID)"
            value={form.caller_id_name ?? ""}
            onChange={(v) => setForm({ ...form, caller_id_name: v })}
          />
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Buzón de voz</span>
            <Toggle checked={form.voicemail} onChange={(v) => setForm({ ...form, voicemail: v })} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitada</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
          <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <div>
              <div className="text-sm text-fg-soft">Llama afuera fuera de horario</div>
              <div className="mt-0.5 text-[11px] leading-snug text-faint">
                Solo cuenta si la empresa limita las salientes al horario laboral (Ajustes). Para guardias.
              </div>
            </div>
            <Toggle
              checked={form.outbound_after_hours}
              onChange={(v) => setForm({ ...form, outbound_after_hours: v })}
            />
          </div>
        </div>
      </Modal>

      <Modal
        open={!!callModal}
        onClose={() => setCallModal(null)}
        title={callModal ? `Llamar desde la extensión ${callModal.number}` : "Llamar"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCallModal(null)}>
              Cerrar
            </Button>
            <Button variant="success" onClick={placeCall} loading={calling} disabled={!callForm.destination}>
              {calling ? "Originando…" : "Llamar"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="Número o extensión destino"
            value={callForm.destination}
            onChange={(v) => setCallForm({ ...callForm, destination: v })}
            placeholder="Ej. 1002 (interna) o 5551234567 (externo)"
            required
            mono
          />
          <Select
            label="Vía"
            value={callForm.trunk_id}
            onChange={(v) => setCallForm({ ...callForm, trunk_id: v })}
            placeholder="— Extensión interna —"
            options={trunks.filter((t) => t.enabled).map((t) => ({ value: String(t.id), label: t.name }))}
          />
          <Note tone="muted">
            Sonará primero la extensión {callModal?.number}; al contestar, se conectará automáticamente con el destino.
            Deja &quot;Vía&quot; vacío para llamar a otra extensión interna, o elige una troncal para marcar un número
            externo.
          </Note>
          {callResult && <Note tone="brand">{callResult}</Note>}
        </div>
      </Modal>

      <Modal
        open={!!softphoneExt}
        onClose={() => setSoftphoneExt(null)}
        title={softphoneExt ? `Softphone — extensión ${softphoneExt.number}` : "Configurar softphone"}
        subtitle="Datos de conexión para 3CXPhone, X-Lite, Zoiper o cualquier teléfono IP SIP"
        footer={
          <Button variant="secondary" onClick={() => setSoftphoneExt(null)}>
            Cerrar
          </Button>
        }
      >
        {softphoneExt && settings && (
          <div className="space-y-2.5">
            {[
              { label: "Servidor / Dominio SIP", value: settings.sip_server_ip },
              { label: "Puerto", value: String(settings.sip_server_port) },
              { label: "Usuario / ID de autenticación", value: softphoneExt.number },
              { label: "Contraseña", value: softphoneExt.password },
              { label: "Transporte", value: "UDP" },
            ].map((row, i) => (
              <div
                key={row.label}
                style={{ animationDelay: `${i * 45}ms` }}
                className="animate-fade-up flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-[11px] text-muted">{row.label}</div>
                  <div className="truncate font-mono text-sm text-fg">{row.value}</div>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    navigator.clipboard.writeText(row.value);
                    setCopied(row.label);
                    setTimeout(() => setCopied(""), 1500);
                  }}
                >
                  {copied === row.label ? "Copiado ✓" : "Copiar"}
                </Button>
              </div>
            ))}
            {(!settings.sip_server_ip ||
              settings.sip_server_ip.startsWith("127.") ||
              settings.sip_server_ip === "localhost") && (
              <Note tone="warn">
                La IP configurada en Ajustes no parece alcanzable desde otro equipo. Configúrala en{" "}
                <span className="font-medium">Ajustes → IP del servidor SIP</span> con la IP de red de este servidor (o
                la IP pública si el softphone se conecta desde fuera de la red).
              </Note>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
