"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, ErrorBanner, PageHeader, TableSkeleton } from "@/components/ui";
import { api } from "@/lib/api";

interface Opcion {
  value: string;
  label: string;
  description?: string;
}

interface Datos {
  roles: Opcion[];
  permisos: Opcion[];
  matriz: Record<string, Record<string, boolean>>;
  fijos: Record<string, string[]>;
  por_defecto: Record<string, string[]>;
}

export default function RolesPage() {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [matriz, setMatriz] = useState<Record<string, Record<string, boolean>>>({});
  const [loading, setLoading] = useState(true);
  const [guardando, setGuardando] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.get<Datos>("/api/role-permissions");
      setDatos(d);
      setMatriz(d.matriz);
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

  const alternar = (rol: string, permiso: string) => {
    setMatriz((m) => ({ ...m, [rol]: { ...m[rol], [permiso]: !m[rol]?.[permiso] } }));
    setAviso("");
  };

  const guardar = async (rol: string) => {
    if (guardando) return;
    setGuardando(rol);
    try {
      await api.put("/api/role-permissions", { role: rol, permisos: matriz[rol] });
      setAviso(`Permisos de ${etiquetaRol(rol)} guardados.`);
      // Se recarga en vez de confiar en el estado local: el servidor
      // ignora las casillas fijas, así que lo que quedó guardado puede no
      // ser exactamente lo que se envió.
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setGuardando("");
    }
  };

  const etiquetaRol = (rol: string) => datos?.roles.find((r) => r.value === rol)?.label ?? rol;

  const cambiado = (rol: string) => {
    if (!datos) return false;
    return datos.permisos.some((p) => (matriz[rol]?.[p.value] ?? false) !== (datos.matriz[rol]?.[p.value] ?? false));
  };

  const esDefecto = (rol: string, permiso: string) => datos?.por_defecto[rol]?.includes(permiso) ?? false;

  return (
    <div>
      <PageHeader
        title="Roles y permisos"
        subtitle="Qué puede hacer cada rol en esta empresa. Los cambios afectan a todos sus usuarios."
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}
      {aviso && (
        <div className="mb-4 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg-soft">{aviso}</div>
      )}

      {loading || !datos ? (
        <Card>
          <TableSkeleton cols={4} />
        </Card>
      ) : (
        <div className="space-y-4">
          {datos.roles.map((rol) => {
            const fijos = datos.fijos[rol.value] ?? [];
            return (
              <Card key={rol.value}>
                <CardHeader
                  title={rol.label}
                  subtitle={rol.description}
                  actions={
                    <Button
                      size="sm"
                      onClick={() => guardar(rol.value)}
                      loading={guardando === rol.value}
                      disabled={!cambiado(rol.value)}
                    >
                      Guardar
                    </Button>
                  }
                />
                <div className="grid gap-2 p-4 sm:grid-cols-2">
                  {datos.permisos.map((p) => {
                    const fijo = fijos.includes(p.value);
                    const activo = matriz[rol.value]?.[p.value] ?? false;
                    return (
                      <label
                        key={p.value}
                        className={`flex items-center gap-2.5 rounded-xl border border-line px-3.5 py-2 ${
                          fijo ? "bg-surface-2 opacity-60" : "cursor-pointer bg-surface-2"
                        }`}
                        title={fijo ? "Fijo: sin esto nadie podría revertir un cambio de permisos" : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={activo}
                          disabled={fijo}
                          onChange={() => alternar(rol.value, p.value)}
                        />
                        <span className="text-sm">{p.label}</span>
                        {!fijo && activo !== esDefecto(rol.value, p.value) && (
                          <span className="ml-auto">
                            <Badge color="amber">{activo ? "agregado" : "quitado"}</Badge>
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              </Card>
            );
          })}

          <Card>
            <div className="p-4 text-sm text-fg-soft">
              <p className="mb-2">
                Las casillas atenuadas del Administrador son fijas a propósito: sin ellas, un cambio equivocado dejaría
                a la empresa sin nadie que pueda entrar a esta pantalla a revertirlo.
              </p>
              <p>
                Gestionar empresas y sus módulos contratados no aparece acá: pertenece al rol de plataforma, que
                administra todas las empresas y no se configura desde una.
              </p>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
