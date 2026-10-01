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
import { AuditTable } from "@/components/audit-table";
import { AvisosCsp } from "@/components/avisos-csp";
import { ConsumoMensual } from "@/components/consumo-mensual";
import { api } from "@/lib/api";
import { AlertaTrafico, Empresa, EmpresaCreada } from "@/lib/types";

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

// `minutos` vacío = el del plan. Solo se envía si se cambió: la API
// devuelve el límite efectivo, y reenviarlo tal cual lo dejaría fijo aunque
// después se cambie de plan.
const vacioLic = { plan: "trial", status: "trial", expires_at: "", minutos: "", minutosInicial: "", cps: "", cpsInicial: "" };

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
  const [globalCortado, setGlobalCortado] = useState<boolean | null>(null);
  const [cambiandoGlobal, setCambiandoGlobal] = useState(false);
  const [alertas, setAlertas] = useState<AlertaTrafico[]>([]);

  const abrirLicencia = (e: Empresa) => {
    const lic = e.licencia;
    setLicTarget(e);
    setLicForm({
      plan: lic?.plan ?? "trial",
      status: lic?.status ?? "trial",
      expires_at: lic?.expires_at ? lic.expires_at.slice(0, 10) : "",
      minutos: lic?.max_outbound_minutes_day != null ? String(lic.max_outbound_minutes_day) : "",
      minutosInicial: lic?.max_outbound_minutes_day != null ? String(lic.max_outbound_minutes_day) : "",
      cps: lic?.max_outbound_cps != null ? String(lic.max_outbound_cps) : "",
      cpsInicial: lic?.max_outbound_cps != null ? String(lic.max_outbound_cps) : "",
    });
  };

  const guardarLicencia = async () => {
    if (!licTarget) return;
    setGuardandoLic(true);
    setError("");
    try {
      const cuerpo: Record<string, unknown> = {
        plan: licForm.plan,
        status: licForm.status,
        expires_at: licForm.expires_at ? `${licForm.expires_at}T23:59:59` : null,
      };
      if (licForm.minutos.trim() !== licForm.minutosInicial) {
        cuerpo.max_outbound_minutes_day = licForm.minutos.trim() === "" ? null : Number(licForm.minutos);
      }
      if (licForm.cps.trim() !== licForm.cpsInicial) {
        cuerpo.max_outbound_cps = licForm.cps.trim() === "" ? null : Number(licForm.cps);
      }
      await api.put(`/api/tenants/${licTarget.id}/licencia`, cuerpo);
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
      const [empresas, global] = await Promise.all([
        api.get<Empresa[]>("/api/tenants"),
        api.get<{ outbound_blocked: boolean }>("/api/plataforma/salientes"),
      ]);
      setItems(empresas);
      setGlobalCortado(global.outbound_blocked);
      // Informativo: si falla, la lista de empresas igual se muestra.
      api.get<AlertaTrafico[]>("/api/plataforma/alertas").then(setAlertas).catch(() => setAlertas([]));
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

  // Controles de emergencia: cortan toda llamada saliente NUEVA al instante
  // (dialplan, clic para llamar y campañas). Las que ya están hablando se
  // cuelgan aparte (backend/app/services/emergencia.py): se pregunta enseguida,
  // porque en un fraude son justo las que se están facturando.
  const colgarEnCurso = async (ruta: string, quien: string) => {
    if (!confirm(`Salientes cortadas. ¿Colgar también las llamadas salientes de ${quien} que están en curso ahora?`)) return;
    try {
      await api.post(ruta);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron colgar las llamadas en curso");
    }
  };

  const cambiarSalientesEmpresa = async (e: Empresa) => {
    const cortar = !e.outbound_blocked;
    if (cortar && !confirm(`¿Cortar todas las llamadas salientes de ${e.name}? La empresa no podrá reactivarlas.`)) return;
    try {
      await api.put(`/api/tenants/${e.id}`, { outbound_blocked: cortar });
      if (cortar) await colgarEnCurso(`/api/tenants/${e.id}/salientes/colgar`, e.name);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cambiar las salientes");
    }
  };

  const cambiarSalientesGlobal = async () => {
    const cortar = !globalCortado;
    if (cortar && !confirm("¿Cortar las llamadas salientes de TODAS las empresas?")) return;
    setCambiandoGlobal(true);
    try {
      const r = await api.put<{ outbound_blocked: boolean }>("/api/plataforma/salientes", { outbound_blocked: cortar });
      setGlobalCortado(r.outbound_blocked);
      if (cortar) await colgarEnCurso("/api/plataforma/salientes/colgar", "todas las empresas");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cambiar las salientes");
    } finally {
      setCambiandoGlobal(false);
    }
  };

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

      {globalCortado !== null && (
        <div
          className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4 ${
            globalCortado ? "border-danger/30 bg-danger-soft" : "border-line bg-surface-2"
          }`}
        >
          <div>
            <div className={`text-sm font-semibold ${globalCortado ? "text-danger-text" : "text-fg"}`}>
              {globalCortado ? "Salientes cortadas en toda la plataforma" : "Salientes de la plataforma"}
            </div>
            <p className="mt-0.5 text-xs text-fg-soft">
              Interruptor de emergencia: corta toda llamada saliente nueva de todas las empresas (fraude en curso,
              problema con el proveedor).
            </p>
          </div>
          <Button
            variant={globalCortado ? "secondary" : "danger"}
            loading={cambiandoGlobal}
            onClick={cambiarSalientesGlobal}
          >
            {globalCortado ? "Reactivar salientes" : "Cortar todas las salientes"}
          </Button>
        </div>
      )}

      {alertas.length > 0 && (
        <Card className="mb-4">
          <CardHeader
            title="Alertas de tráfico saliente"
            subtitle="Las más recientes de todas las empresas. Avisan, no cortan: para cortar usa los botones de salientes."
          />
          <Table head={["Cuándo", "Empresa", "Detalle"]}>
            {alertas.slice(0, 20).map((a) => (
              <Tr key={a.id}>
                <Td muted>{new Date(a.cuando + "Z").toLocaleString()}</Td>
                <Td strong>{a.empresa}</Td>
                <Td>{a.detalle}</Td>
              </Tr>
            ))}
          </Table>
        </Card>
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
                      {e.outbound_blocked && <Badge color="red">Salientes cortadas</Badge>}
                      <Button
                        size="sm"
                        variant={e.outbound_blocked ? "secondary" : "ghost"}
                        onClick={() => cambiarSalientesEmpresa(e)}
                        title="Cortar o reactivar las llamadas salientes de esta empresa"
                      >
                        {e.outbound_blocked ? "Reactivar salientes" : "Cortar salientes"}
                      </Button>
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
          <Input
            label="Minutos salientes por día"
            type="number"
            value={licForm.minutos}
            onChange={(v) => setLicForm((f) => ({ ...f, minutos: v }))}
            hint="Al llegar se cortan las salientes hasta medianoche. Vacío = el del plan (Prueba 60, Gratis 120, Pro 5000, Enterprise sin tope)."
          />
          <Input
            label="Llamadas salientes por segundo"
            type="number"
            value={licForm.cps}
            onChange={(v) => setLicForm((f) => ({ ...f, cps: v }))}
            hint="Freno de fraude: las que pasan de este ritmo se rechazan (teléfonos y clic para llamar; las campañas van por su concurrencia). Vacío = el del plan (Prueba y Gratis 1, Pro 5, Enterprise 10)."
          />
          <div className="rounded-xl border border-line bg-surface-2 p-3 text-xs text-fg-soft">
            <div className="mb-1 font-medium text-fg">Límites del plan</div>
            {licTarget?.licencia && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <span>Extensiones: <b className="text-fg">{licTarget.licencia.max_extensions ?? "∞"}</b></span>
                <span>Troncales: <b className="text-fg">{licTarget.licencia.max_trunks ?? "∞"}</b></span>
                <span>Concurrentes: <b className="text-fg">{licTarget.licencia.max_concurrent_calls ?? "∞"}</b></span>
                <span>Campañas: <b className="text-fg">{licTarget.licencia.max_campaigns ?? "∞"}</b></span>
                <span>Min. salientes/día: <b className="text-fg">{licTarget.licencia.max_outbound_minutes_day ?? "∞"}</b></span>
                <span>Salientes/segundo: <b className="text-fg">{licTarget.licencia.max_outbound_cps ?? "∞"}</b></span>
              </div>
            )}
            <p className="mt-2 text-faint">
              Los límites se aplican al crear extensiones/troncales/campañas y al originar llamadas. Si la licencia
              está vencida o suspendida, la empresa no puede operar.
            </p>
          </div>
        </div>
      </Modal>
      <ConsumoMensual plataforma />
      <AvisosCsp />
      <AuditTable
        endpoint="/api/plataforma/auditoria"
        title="Auditoría de la plataforma"
        subtitle="Acciones de todas las empresas y de la plataforma, incluidos los intentos de acceso fallidos."
      />
    </div>
  );
}
