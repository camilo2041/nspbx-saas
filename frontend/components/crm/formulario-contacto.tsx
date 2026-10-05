"use client";

import { Check, Input, Select } from "@/components/ui";
import { CampoContacto, Contacto, TelefonoExtra } from "@/lib/types";

export interface DatosContacto {
  nombre: string;
  documento: string;
  telefono: string;
  telefonos: TelefonoExtra[];
  email: string;
  direccion: string;
  ciudad: string;
  campos: Record<string, string | boolean>;
}

export const contactoVacio: DatosContacto = {
  nombre: "",
  documento: "",
  telefono: "",
  telefonos: [],
  email: "",
  direccion: "",
  ciudad: "",
  campos: {},
};

export function datosDe(c: Contacto): DatosContacto {
  const campos: Record<string, string | boolean> = {};
  for (const [k, v] of Object.entries(c.campos ?? {})) campos[k] = typeof v === "boolean" ? v : String(v);
  return {
    nombre: c.nombre ?? "",
    documento: c.documento ?? "",
    telefono: c.telefono,
    telefonos: c.telefonos ?? [],
    email: c.email ?? "",
    direccion: c.direccion ?? "",
    ciudad: c.ciudad ?? "",
    campos,
  };
}

/** Cuerpo para la API: vacíos como null y solo los campos propios definidos. */
export function cuerpoDe(d: DatosContacto, defs: CampoContacto[]) {
  const campos: Record<string, string | boolean> = {};
  for (const def of defs) {
    const v = d.campos[def.clave];
    if (v === undefined || v === "") continue;
    campos[def.clave] = v;
  }
  return {
    nombre: d.nombre.trim(),
    documento: d.documento.trim() || null,
    telefono: d.telefono.trim(),
    telefonos: d.telefonos.filter((t) => t.numero.trim()).map((t) => ({ numero: t.numero.trim(), tipo: t.tipo || "otro" })),
    email: d.email.trim() || null,
    direccion: d.direccion.trim() || null,
    ciudad: d.ciudad.trim() || null,
    campos,
  };
}

export function CampoPropio({
  def,
  valor,
  onChange,
}: {
  def: CampoContacto;
  valor: string | boolean | undefined;
  onChange: (v: string | boolean) => void;
}) {
  const etiqueta = def.obligatorio ? `${def.nombre} *` : def.nombre;
  if (def.tipo === "si_no") {
    return <Check checked={valor === true} onChange={onChange} label={def.nombre} />;
  }
  if (def.tipo === "opciones") {
    return (
      <Select
        label={etiqueta}
        value={typeof valor === "string" ? valor : ""}
        onChange={onChange}
        placeholder="—"
        options={def.opciones.map((o) => ({ value: o, label: o }))}
      />
    );
  }
  return (
    <Input
      label={etiqueta}
      type={def.tipo === "numero" ? "number" : def.tipo === "fecha" ? "date" : "text"}
      value={typeof valor === "string" ? valor : ""}
      onChange={onChange}
    />
  );
}

export function FormularioContacto({
  datos,
  onChange,
  defs,
}: {
  datos: DatosContacto;
  onChange: (d: DatosContacto) => void;
  defs: CampoContacto[];
}) {
  const set = <K extends keyof DatosContacto>(k: K, v: DatosContacto[K]) => onChange({ ...datos, [k]: v });
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Nombre" value={datos.nombre} onChange={(v) => set("nombre", v)} />
        <Input label="Documento" value={datos.documento} onChange={(v) => set("documento", v)} mono />
        <Input label="Teléfono principal" value={datos.telefono} onChange={(v) => set("telefono", v)} required mono />
        <Input label="Correo" type="email" value={datos.email} onChange={(v) => set("email", v)} />
        <Input label="Dirección" value={datos.direccion} onChange={(v) => set("direccion", v)} />
        <Input label="Ciudad" value={datos.ciudad} onChange={(v) => set("ciudad", v)} />
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-medium text-fg-soft">Otros teléfonos</span>
          {datos.telefonos.length < 5 && (
            <button
              type="button"
              onClick={() => set("telefonos", [...datos.telefonos, { numero: "", tipo: "movil" }])}
              className="text-xs font-medium text-brand-text hover:underline"
            >
              + Agregar
            </button>
          )}
        </div>
        <div className="space-y-2">
          {datos.telefonos.map((t, i) => (
            <div key={i} className="flex items-end gap-2">
              <div className="flex-1">
                <Input
                  label=""
                  value={t.numero}
                  mono
                  placeholder="6011234567"
                  onChange={(v) => set("telefonos", datos.telefonos.map((x, j) => (j === i ? { ...x, numero: v } : x)))}
                />
              </div>
              <div className="w-32">
                <Select
                  label=""
                  value={t.tipo}
                  onChange={(v) => set("telefonos", datos.telefonos.map((x, j) => (j === i ? { ...x, tipo: v } : x)))}
                  options={[
                    { value: "movil", label: "Móvil" },
                    { value: "fijo", label: "Fijo" },
                    { value: "trabajo", label: "Trabajo" },
                    { value: "otro", label: "Otro" },
                  ]}
                />
              </div>
              <button
                type="button"
                aria-label="Quitar teléfono"
                onClick={() => set("telefonos", datos.telefonos.filter((_, j) => j !== i))}
                className="mb-2 rounded-lg p-1.5 text-faint hover:bg-surface-2 hover:text-danger-text"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {defs.length > 0 && (
        <div className="grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
          {defs.map((def) => (
            <CampoPropio
              key={def.clave}
              def={def}
              valor={datos.campos[def.clave]}
              onChange={(v) => set("campos", { ...datos.campos, [def.clave]: v })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
