"use client";

import { useCallback, useEffect, useState } from "react";

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
  Note,
  PageHeader,
  Select,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Empresa, EmpresaCreada } from "@/lib/types";

const vacio = { name: "", slug: "", sip_domain: "", subdomain: "", business_type: "general", modules: ["voicebot", "pbx"] as string[] };

const MODULOS = [
  { value: "voicebot", label: "Voicebot IA", hint: "Voizbots, campañas, cobranza y consumo de IA" },
  { value: "pbx", label: "Telefonía / Call", hint: "Extensiones, troncales, softphone, llamadas y colas" },
];

const TIPOS = [
  { value: "general", label: "General / PBX" },
  { value: "clinica", label: "Consultorio / Salud (citas)" },
  { value: "cobranza", label: "Cobranza / Cartera" },
];

const TIPO_ETIQUETA: Record<string, { label: string; badge: string }> = {
  general: { label: "General", badge: "blue" },
  clinica: { label: "Salud", badge: "green" },
  cobranza: { label: "Cobranza", badge: "amber" },
};

const PLAN_ETIQUETA: Record<string, string> = {
  trial: "Prueba",
  free: "Gratis",
  pro: "Pro",
  enterprise: "Enterprise",
  custom: "Personalizado",
};

const ESTADO_LICENCIA: Record<string, { label: string; badge: string }> = {
  ok: { label: "Activa", badge: "green" },
  vencida: { label: "Vencida", badge: "red" },
  suspendida: { label: "Suspendida", badge: "amber" },
};

const PLANES = [
  { value: "trial", label: "Prueba (15 días)" },
  { value: "free", label: "Gratis" },
  { value: "pro", label: "Pro" },
  { value: "enterprise", label: "Enterprise (sin límites)" },
  { value: "custom", label: "Personalizado" },
];

const vacioLic = { plan: "trial", status: "trial", expires_at: "" };

function urlPanel(subdomain: string | null) {
  if (!subdomain) return null;
  if (typeof window === "undefined") return subdomain;
  const base = window.location.host;
  // base puede ser "localhost:3005" (dev) o "pbx.ejemplo.com" (prod).
  const sinPuerto = base.split(":")[0];
  const puerto = base.includes(":") ? `:${base.split(":")[1]}` : "";
  return `${subdomain}.${sinPuerto}${puerto}`;
}

export default function EmpresasPage() {
  const [items, setItems] = useState<Empresa[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editando, setEditando] = useState<Empresa | null>(null);
  const [creando, setCreando] = useState(false);
  const [form, setForm] = useState(vacio);
  const [creada, setCreada] = useState<EmpresaCreada | null>(null);
  const [licTarget, setLicTarget] = useState<Empresa | null>(null);
  const [licForm, setLicForm] = useState(vacioLic);
  const [guardandoLic, setGuardandoLic] = useState(false);

  const abrirLicencia = (e: Empresa) => {
    const lic = e.licencia;
    setLicTarget(e);
    setLicForm({
      plan: lic?.plan ?? "trial",
      status: lic?.status ?? "trial",
      expires_at: lic?.expires_at ? lic.expires_at.slice(0, 10) : "",
    });
  };

  const guardarLicencia = async () => {
    if (!licTarget) return;
    setGuardandoLic(true);
    setError("");
    try {
      await api.put(`/api/tenants/${licTarget.id}/licencia`, {
        plan: licForm.plan,
        status: licForm.status,
        expires_at: licForm.expires_at ? `${licForm.expires_at}T23:59:59` : null,
      });
      setLicTarget(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar la licencia");
    } finally {
      setGuardandoLic(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.get<Empresa[]>("/api/tenants"));
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

  const abrirCrear = () => {
    setEditando(null);
    setForm(vacio);
    setModal(true);
  };

  const abrirEditar = (e: Empresa) => {
    setEditando(e);
    setForm({
      name: e.name,
      slug: e.slug,
      sip_domain: e.sip_domain,
      subdomain: e.subdomain ?? "",
      business_type: e.business_type,
      modules: e.modules.length ? [...e.modules] : ["voicebot", "pbx"],
    });
    setModal(true);
  };

  const toggleModulo = (m: string) => {
    setForm((f) => {
      const actual = f.modules.includes(m);
      const next = actual ? f.modules.filter((x) => x !== m) : [...f.modules, m];
      // Nunca dejar la empresa sin ningún módulo.
      return { ...f, modules: next.length ? next : ["voicebot"] };
    });
  };

  const guardar = async () => {
    setCreando(true);
    setError("");
    try {
      if (editando) {
        await api.put(`/api/tenants/${editando.id}`, {
          name: form.name.trim(),
          sip_domain: form.sip_domain.trim(),
          subdomain: form.subdomain.trim() || null,
          business_type: form.business_type,
          modules: form.modules,
        });
      } else {
        const creada = await api.post<EmpresaCreada>("/api/tenants", {
          name: form.name.trim(),
          slug: form.slug.trim().toLowerCase(),
          sip_domain: form.sip_domain.trim(),
          subdomain: form.subdomain.trim() || null,
          business_type: form.business_type,
          modules: form.modules,
        });
        setCreada(creada);
      }
      setModal(false);
      setForm(vacio);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setCreando(false);
    }
  };

  const eliminar = async (e: Empresa) => {
    if (!confirm(`¿Eliminar la empresa ${e.name} y TODOS sus datos? Esta acción no se puede deshacer.`)) return;
    try {
      await api.del(`/api/tenants/${e.id}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  };

  const set = <K extends keyof typeof vacio>(k: K, v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div>
      <PageHeader
        title="Empresas"
        subtitle="Multiempresa: cada empresa tiene su subdominio de panel, su dominio SIP y sus datos aislados"
        actions={<Button onClick={abrirCrear}>+ Nueva empresa</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {creada && (
        <div className="mb-4 rounded-xl border border-ok/25 bg-ok-soft p-4">
          <div className="mb-1 text-sm font-semibold text-ok-text">Empresa creada</div>
          <p className="mb-2 text-xs text-fg-soft">
            Estas credenciales solo se muestran una vez. Con ellas entra el administrador de la empresa en su
            subdominio.
          </p>
          <div className="flex flex-wrap gap-3 text-sm">
            <div className="rounded-lg border border-line bg-surface px-3 py-1.5 font-mono">
              {creada.admin_username}
            </div>
            <div className="rounded-lg border border-line bg-surface px-3 py-1.5 font-mono">{creada.admin_password}</div>
            <div className="rounded-lg border border-line bg-surface px-3 py-1.5 font-mono">{creada.sip_domain}</div>
          </div>
          <div className="mt-2 text-xs text-fg-soft">
            Panel: <span className="font-mono text-fg">{urlPanel(creada.subdomain)}</span>
          </div>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => setCreada(null)}>
            Entendido
          </Button>
        </div>
      )}

      <Card>
        <CardHeader title="Empresas" subtitle={`${items.length} en la plataforma`} />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState title="No hay empresas" hint="Crea la primera para empezar a operar." action={<Button onClick={abrirCrear}>+ Nueva empresa</Button>} />
        ) : (
          <Table head={["Nombre", "Tipo", "Módulos", "Licencia", "Subdominio", "Usuarios", "Estado"]}>
            {items.map((e) => {
              const url = urlPanel(e.subdomain);
              const tipo = TIPO_ETIQUETA[e.business_type] ?? TIPO_ETIQUETA.general;
              const lic = e.licencia;
              const estLic = ESTADO_LICENCIA[lic?.estado ?? "ok"] ?? ESTADO_LICENCIA.ok;
              return (
                <Tr key={e.id}>
                  <Td strong>{e.name}</Td>
                  <Td>
                    <Badge color={tipo.badge}>{tipo.label}</Badge>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1.5">
                      {e.modules.includes("voicebot") && <Badge color="indigo">Voicebot</Badge>}
                      {e.modules.includes("pbx") && <Badge color="blue">Call</Badge>}
                    </div>
                  </Td>
                  <Td>
                    <button
                      type="button"
                      onClick={() => abrirLicencia(e)}
                      className="flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-xs font-medium text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
                      title="Administrar licencia"
                    >
                      <Badge color={estLic.badge} dot>
                        {estLic.label}
                      </Badge>
                      <span className="text-faint">{PLAN_ETIQUETA[lic?.plan ?? "free"] ?? lic?.plan}</span>
                    </button>
                  </Td>
                  <Td>
                    {url ? (
                      <a
                        href={`http://${url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-brand-text underline underline-offset-2"
                      >
                        {e.subdomain}
                      </a>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </Td>
                  <Td>{e.users_count}</Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Badge color={e.enabled ? "green" : "red"} dot>
                        {e.enabled ? "Activa" : "Inactiva"}
                      </Badge>
                      <Button size="sm" variant="secondary" onClick={() => abrirEditar(e)}>
                        Editar
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => eliminar(e)}>
                        Eliminar
                      </Button>
                    </div>
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
        title={editando ? `Editar ${editando.name}` : "Nueva empresa"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={guardar} loading={creando} disabled={!form.name.trim() || !form.sip_domain.trim()}>
              {editando ? "Guardar" : "Crear"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre" value={form.name} onChange={(v) => set("name", v)} required placeholder="Consultorio Andino" />
          <Select
            label="Tipo de empresa"
            value={form.business_type}
            onChange={(v) => set("business_type", v)}
            options={TIPOS}
            hint="Define el enfoque: citas (Salud), cartera (Cobranza) o general. Ajusta el nombre del panel al crearla."
          />
          <div>
            <div className="mb-1.5 text-xs font-medium text-fg-soft">Módulos (pack)</div>
            <div className="space-y-1 rounded-xl border border-line bg-surface-2 p-2">
              {MODULOS.map((m) => (
                <Check
                  key={m.value}
                  checked={form.modules.includes(m.value)}
                  onChange={() => toggleModulo(m.value)}
                  label={
                    <span className="flex flex-col">
                      <span>{m.label}</span>
                      <span className="text-[11px] font-normal text-faint">{m.hint}</span>
                    </span>
                  }
                />
              ))}
            </div>
            <p className="mt-1 text-[11px] text-faint">
              Ampliable después desde esta misma pantalla (agregá un módulo cuando lo necesites).
            </p>
          </div>
          {!editando && (
            <Input
              label="Slug (identificador interno)"
              value={form.slug}
              onChange={(v) => set("slug", v)}
              required
              mono
              placeholder="consultorio-andino"
              hint="Minúsculas y guiones. De él salen el contexto del dialplan (ctx_&lt;slug&gt;) y el prefijo de las troncales."
            />
          )}
          <Input
            label="Dominio SIP"
            value={form.sip_domain}
            onChange={(v) => set("sip_domain", v)}
            required
            mono
            placeholder="consultorio-andino.pbx.local"
            hint="Con el que se registran los teléfonos de esta empresa. Debe ser distinto al de las demás."
          />
          <Input
            label="Subdominio del panel"
            value={form.subdomain}
            onChange={(v) => set("subdomain", v)}
            mono
            placeholder="consultorio-andino"
            hint="La etiqueta antes del dominio base (ej. consultorio-andino.pbx.ejemplo.com). Vacío en alta = se usa el slug. El login desde ese subdominio queda atado a esta empresa."
          />
          {!editando && (
            <Note tone="muted">
              Al crear se genera automáticamente el administrador de la empresa. Verás sus credenciales una sola vez.
            </Note>
          )}
        </div>
      </Modal>

      <Modal
        open={!!licTarget}
        onClose={() => setLicTarget(null)}
        title={`Licencia · ${licTarget?.name ?? ""}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setLicTarget(null)}>
              Cerrar
            </Button>
            <Button onClick={guardarLicencia} loading={guardandoLic}>
              Guardar
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Select
            label="Plan"
            value={licForm.plan}
            onChange={(v) => setLicForm((f) => ({ ...f, plan: v }))}
            options={PLANES}
            hint="Al cambiar de plan se aplican los límites del nuevo; 'Personalizado' permite ajustarlos a mano después."
          />
          <Select
            label="Estado"
            value={licForm.status}
            onChange={(v) => setLicForm((f) => ({ ...f, status: v }))}
            options={[
              { value: "trial", label: "Prueba" },
              { value: "active", label: "Activa" },
              { value: "suspended", label: "Suspendida" },
            ]}
          />
          <Input
            label="Vence el"
            type="date"
            value={licForm.expires_at}
            onChange={(v) => setLicForm((f) => ({ ...f, expires_at: v }))}
            hint="Vacío = sin vencimiento."
          />
          <div className="rounded-xl border border-line bg-surface-2 p-3 text-xs text-fg-soft">
            <div className="mb-1 font-medium text-fg">Límites del plan</div>
            {licTarget?.licencia && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <span>Extensiones: <b className="text-fg">{licTarget.licencia.max_extensions ?? "∞"}</b></span>
                <span>Troncales: <b className="text-fg">{licTarget.licencia.max_trunks ?? "∞"}</b></span>
                <span>Concurrentes: <b className="text-fg">{licTarget.licencia.max_concurrent_calls ?? "∞"}</b></span>
                <span>Campañas: <b className="text-fg">{licTarget.licencia.max_campaigns ?? "∞"}</b></span>
              </div>
            )}
            <p className="mt-2 text-faint">
              Los límites se aplican al crear extensiones/troncales/campañas y al originar llamadas. Si la licencia
              está vencida o suspendida, la empresa no puede operar.
            </p>
          </div>
        </div>
      </Modal>
    </div>
  );
}
