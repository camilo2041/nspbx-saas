"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, Input, Note, Select } from "@/components/ui";
import { api } from "@/lib/api";

interface Intento {
  id: number;
  clave: string;
  estado: "en_curso" | "ok" | "fallo" | "omitida";
  iniciada_en: string;
  terminada_en: string | null;
  quien: string;
  evidencia: string | null;
  nota: string | null;
}

interface Prueba {
  clave: string;
  titulo: string;
  fase: string;
  pasos: string[];
  automatica: boolean;
  ultima: Intento | null;
}

const ESTADO: Record<Intento["estado"], { texto: string; color: "amber" | "green" | "red" | "gray" }> = {
  en_curso: { texto: "En curso", color: "amber" },
  ok: { texto: "Pasó", color: "green" },
  fallo: { texto: "Falló", color: "red" },
  omitida: { texto: "Omitida", color: "gray" },
};

const fecha = (iso: string) => new Date(`${iso}Z`).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });

/**
 * Verificación en vivo (services/verificacion.py): las pruebas que necesitan
 * teléfonos reales. Cada una dice qué marcar; «Comprobar» busca el rastro en
 * el backend desde que se empezó, y las demás se confirman a mano.
 */
export function VerificacionVivo({ empresas }: { empresas: { id: number; name: string }[] }) {
  const [tenant, setTenant] = useState<string>("");
  const [pruebas, setPruebas] = useState<Prueba[] | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [nota, setNota] = useState("");
  const [aviso, setAviso] = useState("");
  const [trabajando, setTrabajando] = useState<string | null>(null);

  const cargar = useCallback((tid: string) => {
    if (!tid) return;
    api.get<Prueba[]>(`/api/plataforma/verificacion?tenant_id=${tid}`).then(setPruebas, () => setPruebas(null));
  }, []);
  useEffect(() => {
    cargar(tenant);
  }, [tenant, cargar]);

  if (!empresas.length) return null;

  const hacer = async (clave: string, accion: () => Promise<unknown>) => {
    setTrabajando(clave);
    setAviso("");
    try {
      await accion();
      cargar(tenant);
    } catch (e) {
      setAviso(e instanceof Error ? e.message : "No se pudo");
    } finally {
      setTrabajando(null);
    }
  };

  const hechas = pruebas?.filter((p) => p.ultima && p.ultima.estado !== "en_curso").length ?? 0;
  const fallas = pruebas?.filter((p) => p.ultima?.estado === "fallo").length ?? 0;

  return (
    <Card className="mb-4">
      <CardHeader
        title="Verificación en vivo"
        subtitle="Lo que la prueba de humo no puede hacer sola: llamadas reales con teléfonos. Empieza una prueba, haz lo que dice y pulsa «Comprobar»."
      />
      <div className="space-y-3 px-5 pb-5">
        <div className="max-w-xs">
          <Select
            label="Empresa"
            value={tenant}
            onChange={(v) => {
              setTenant(v);
              setPruebas(null);
              setAbierta(null);
            }}
            placeholder="Elige la empresa de prueba"
            options={empresas.map((e) => ({ value: String(e.id), label: e.name }))}
          />
        </div>
        {aviso && <Note tone="warn">{aviso}</Note>}
        {pruebas && (
          <>
            <p className="text-sm text-fg-soft">
              {hechas} de {pruebas.length} hechas{fallas ? ` · ${fallas} con fallas` : ""}
            </p>
            <ul className="divide-y divide-line rounded-xl border border-line">
              {pruebas.map((p) => {
                const u = p.ultima;
                const enCurso = u?.estado === "en_curso";
                return (
                  <li key={p.clave} className="px-3.5 py-2.5">
                    <button
                      type="button"
                      onClick={() => {
                        setAbierta(abierta === p.clave ? null : p.clave);
                        setNota("");
                      }}
                      className="flex w-full flex-wrap items-center gap-2 text-left"
                    >
                      <span className="w-20 shrink-0 text-xs text-muted">{p.fase}</span>
                      <span className="flex-1 text-sm font-medium text-fg">{p.titulo}</span>
                      {!p.automatica && <span className="text-xs text-faint">a mano</span>}
                      {u ? <Badge color={ESTADO[u.estado].color}>{ESTADO[u.estado].texto}</Badge> : <Badge color="gray">Sin hacer</Badge>}
                    </button>
                    {abierta === p.clave && (
                      <div className="mt-3 space-y-3 pl-0 sm:pl-[5.5rem]">
                        <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-soft">
                          {p.pasos.map((s) => (
                            <li key={s}>{s}</li>
                          ))}
                        </ol>
                        {u && (
                          <p className="text-xs text-muted">
                            {enCurso ? "Empezada" : "Última vez"} el {fecha(u.terminada_en ?? u.iniciada_en)} por {u.quien}
                            {u.evidencia ? ` · ${u.evidencia}` : ""}
                            {u.nota ? ` · «${u.nota}»` : ""}
                          </p>
                        )}
                        <div className="flex flex-wrap items-end gap-2">
                          {!enCurso ? (
                            <Button
                              size="sm"
                              loading={trabajando === p.clave}
                              onClick={() => hacer(p.clave, () => api.post("/api/plataforma/verificacion", { tenant_id: Number(tenant), clave: p.clave }))}
                            >
                              {u ? "Repetir" : "Empezar"}
                            </Button>
                          ) : (
                            <>
                              {p.automatica && (
                                <Button
                                  size="sm"
                                  loading={trabajando === p.clave}
                                  onClick={() =>
                                    hacer(p.clave, async () => {
                                      const r = await api.post<{ encontrada: boolean }>(`/api/plataforma/verificacion/${u!.id}/comprobar`);
                                      if (!r.encontrada) setAviso("Todavía no aparece. Termina los pasos (cuelga la llamada) y vuelve a comprobar.");
                                    })
                                  }
                                >
                                  Comprobar
                                </Button>
                              )}
                              <div className="w-64">
                                <Input label="Nota (opcional)" value={nota} onChange={setNota} placeholder="Qué se oyó, qué falló" />
                              </div>
                              {(["ok", "fallo", "omitida"] as const).map((estado) => (
                                <Button
                                  key={estado}
                                  size="sm"
                                  variant={estado === "ok" ? "success" : estado === "fallo" ? "danger" : "ghost"}
                                  onClick={() =>
                                    hacer(p.clave, () => api.post(`/api/plataforma/verificacion/${u!.id}/resultado`, { estado, nota }))
                                  }
                                >
                                  {estado === "ok" ? "Pasó" : estado === "fallo" ? "Falló" : "Omitir"}
                                </Button>
                              ))}
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
    </Card>
  );
}
