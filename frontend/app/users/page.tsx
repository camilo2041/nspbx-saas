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
import { Extension, Rol, RolInfo, Usuario } from "@/lib/types";

const COLOR_ROL: Record<string, string> = {
  admin: "red",
  supervisor: "violet",
  coordinador: "blue",
  asesor: "green",
};

function fecha(iso: string | null) {
  if (!iso) return "Nunca";
  return new Date(iso + "Z").toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

interface Formulario {
  username: string;
  full_name: string;
  email: string;
  role: Rol;
  extension_id: string;
  enabled: boolean;
  password: string;
}

const VACIO: Formulario = {
  username: "",
  full_name: "",
  email: "",
  role: "asesor",
  extension_id: "",
  enabled: true,
  password: "",
};

export default function UsersPage() {
  const { usuario: yo } = useAuth();
  const [items, setItems] = useState<Usuario[]>([]);
  const [roles, setRoles] = useState<RolInfo[]>([]);
  const [extensiones, setExtensiones] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [abierto, setAbierto] = useState(false);
  const [editando, setEditando] = useState<Usuario | null>(null);
  const [form, setForm] = useState<Formulario>(VACIO);
  const [guardando, setGuardando] = useState(false);
  const [errorForm, setErrorForm] = useState("");
  const [aBorrar, setABorrar] = useState<Usuario | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [us, rs, exts] = await Promise.all([
        api.get<Usuario[]>("/api/users"),
        api.get<RolInfo[]>("/api/users/roles"),
        api.get<Extension[]>("/api/extensions"),
      ]);
      setItems(us);
      setRoles(rs);
      setExtensiones(exts);
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

  const abrirNuevo = () => {
    setEditando(null);
    setForm(VACIO);
    setErrorForm("");
    setAbierto(true);
  };

  const abrirEditar = (u: Usuario) => {
    setEditando(u);
    setForm({
      username: u.username,
      full_name: u.full_name,
      email: u.email ?? "",
      role: u.role,
      extension_id: u.extension_id ? String(u.extension_id) : "",
      enabled: u.enabled,
      password: "",
    });
    setErrorForm("");
    setAbierto(true);
  };

  const rolActual = roles.find((r) => r.value === form.role);

  // Una extensión por persona: se ofrecen solo las libres, más la que ya
  // tenga quien se está editando.
  const ocupadas = new Set(
    items.filter((u) => u.id !== editando?.id && u.extension_id).map((u) => u.extension_id)
  );
  const extensionesLibres = extensiones.filter((e) => !ocupadas.has(e.id));

  const guardar = async () => {
    setGuardando(true);
    setErrorForm("");
    const cuerpo: Record<string, unknown> = {
      full_name: form.full_name.trim(),
      email: form.email.trim() || null,
      role: form.role,
      extension_id: form.extension_id ? Number(form.extension_id) : null,
      enabled: form.enabled,
    };
    if (form.password) cuerpo.password = form.password;
    try {
      if (editando) {
        await api.put(`/api/users/${editando.id}`, cuerpo);
      } else {
        await api.post("/api/users", { ...cuerpo, username: form.username.trim() });
      }
      setAbierto(false);
      await load();
    } catch (e) {
      setErrorForm(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  // Para quien perdió el teléfono y los códigos de recuperación (ver
  // backend POST /api/users/{id}/mfa/reset). Cierra sus sesiones.
  const restablecerMfa = async (u: Usuario) => {
    if (!confirm(`¿Restablecer la verificación en dos pasos de ${u.full_name}? Tendrá que configurarla de nuevo al entrar.`)) return;
    try {
      await api.post(`/api/users/${u.id}/mfa/reset`, {});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo restablecer");
    }
  };

  const borrar = async () => {
    if (!aBorrar) return;
    try {
      await api.del(`/api/users/${aBorrar.id}`);
      setABorrar(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo eliminar");
      setABorrar(null);
    }
  };

  const faltaExtension = rolActual?.requiere_extension && !form.extension_id;
  const puedeGuardar =
    form.full_name.trim().length >= 2 &&
    (editando || (form.username.trim().length >= 3 && form.password.length >= 8)) &&
    (!form.password || form.password.length >= 8) &&
    !faltaExtension;

  return (
    <div>
      <PageHeader
        title="Usuarios"
        subtitle="Quién entra al sistema y qué puede hacer cada uno"
        actions={<Button onClick={abrirNuevo}>Nuevo usuario</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {roles.map((r) => (
          <div key={r.value} className="rounded-xl border border-line bg-surface p-4">
            <Badge color={COLOR_ROL[r.value] ?? "slate"}>{r.label}</Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted">{r.description}</p>
            <p className="mt-2 text-[11px] text-faint">
              {items.filter((u) => u.role === r.value).length} usuario(s)
            </p>
          </div>
        ))}
      </div>

      <Card>
        <CardHeader title="Cuentas" subtitle={`${items.length} en total`} />
        {loading && items.length === 0 ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState title="No hay usuarios" hint="Crea el primero con el botón de arriba." />
        ) : (
          <Table head={["Nombre", "Usuario", "Rol", "Extensión", "Último acceso", "Estado", ""]}>
            {items.map((u, i) => (
              <Tr key={u.id} delay={Math.min(i, 12) * 30}>
                <Td>
                  {u.full_name}
                  {u.id === yo?.id && <span className="ml-1.5 text-[11px] text-faint">(tú)</span>}
                  {u.email && <div className="text-xs text-faint">{u.email}</div>}
                </Td>
                <Td mono>{u.username}</Td>
                <Td>
                  <Badge color={COLOR_ROL[u.role] ?? "slate"}>
                    {roles.find((r) => r.value === u.role)?.label ?? u.role}
                  </Badge>
                </Td>
                <Td mono>{u.extension_number ?? "—"}</Td>
                <Td muted>{fecha(u.last_login_at)}</Td>
                <Td>
                  <Badge color={u.enabled ? "green" : "slate"} dot>
                    {u.enabled ? "Activo" : "Desactivado"}
                  </Badge>
                  {u.mfa_enabled && (
                    <span className="ml-1.5">
                      <Badge color="blue">2 pasos</Badge>
                    </span>
                  )}
                </Td>
                <Td>
                  <RowActions>
                    <Button size="sm" variant="ghost" onClick={() => abrirEditar(u)}>
                      Editar
                    </Button>
                    {u.mfa_enabled && u.id !== yo?.id && (
                      <Button size="sm" variant="ghost" onClick={() => restablecerMfa(u)} title="Perdió el teléfono">
                        Restablecer 2 pasos
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={u.id === yo?.id}
                      title={u.id === yo?.id ? "No puedes eliminar tu propia cuenta" : undefined}
                      onClick={() => setABorrar(u)}
                    >
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
        open={abierto}
        onClose={() => setAbierto(false)}
        title={editando ? `Editar ${editando.full_name}` : "Nuevo usuario"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAbierto(false)}>
              Cancelar
            </Button>
            <Button onClick={guardar} loading={guardando} disabled={!puedeGuardar}>
              Guardar
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {errorForm && <ErrorBanner message={errorForm} onClose={() => setErrorForm("")} />}

          <Input label="Nombre completo" value={form.full_name} onChange={(v) => setForm({ ...form, full_name: v })} required />

          <Input
            label="Usuario"
            value={form.username}
            onChange={(v) => setForm({ ...form, username: v })}
            disabled={!!editando}
            hint={
              editando
                ? "El nombre de usuario no se cambia: es con lo que la persona inicia sesión."
                : "Mínimo 3 caracteres. Letras, números, punto, guion y guion bajo."
            }
            mono
          />

          <Input
            label="Correo (opcional)"
            type="email"
            value={form.email}
            onChange={(v) => setForm({ ...form, email: v })}
          />

          <Select
            label="Rol"
            value={form.role}
            onChange={(v) => setForm({ ...form, role: v as Rol })}
            options={roles.map((r) => ({ value: r.value, label: r.label }))}
            hint={rolActual?.description}
          />

          <Select
            label={rolActual?.requiere_extension ? "Extensión (obligatoria)" : "Extensión (opcional)"}
            value={form.extension_id}
            onChange={(v) => setForm({ ...form, extension_id: v })}
            placeholder="Sin extensión"
            options={extensionesLibres.map((e) => ({
              value: String(e.id),
              label: `${e.number}${e.caller_id_name ? ` — ${e.caller_id_name}` : ""}`,
            }))}
            hint={
              rolActual?.requiere_extension
                ? "Un asesor atiende desde su extensión, y su historial de llamadas se filtra por ella."
                : "Solo hace falta si esta persona va a usar el softphone."
            }
          />
          {faltaExtension && <Note tone="warn">Este rol necesita una extensión asignada.</Note>}
          {extensionesLibres.length === 0 && (
            <Note tone="muted">
              No quedan extensiones libres. Crea una en Telefonía → Extensiones, o libera la de otro usuario.
            </Note>
          )}

          <Input
            label={editando ? "Nueva contraseña" : "Contraseña"}
            type="password"
            value={form.password}
            onChange={(v) => setForm({ ...form, password: v })}
            hint={
              editando
                ? "Déjala vacía para no cambiarla. Mínimo 8 caracteres."
                : "Mínimo 8 caracteres. Compártela por un medio seguro."
            }
          />

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-3">
            <div>
              <div className="text-sm font-medium text-fg">Cuenta activa</div>
              <div className="text-[11px] text-faint">
                Al desactivarla, la persona no puede entrar y su sesión abierta se corta.
              </div>
            </div>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
        </div>
      </Modal>

      <Modal
        open={!!aBorrar}
        onClose={() => setABorrar(null)}
        title="Eliminar usuario"
        footer={
          <>
            <Button variant="ghost" onClick={() => setABorrar(null)}>
              Cancelar
            </Button>
            <Button variant="danger" onClick={borrar}>
              Eliminar
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-soft">
          Se va a eliminar la cuenta de <strong>{aBorrar?.full_name}</strong> ({aBorrar?.username}).
        </p>
        <Note tone="warn">
          Si solo quieres impedirle el acceso temporalmente, desactívala en vez de borrarla: así conservas
          el registro de quién hizo qué.
        </Note>
      </Modal>
    </div>
  );
}
