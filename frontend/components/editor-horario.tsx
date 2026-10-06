"use client";

import { useMemo } from "react";

const DIAS: { key: string; label: string }[] = [
  { key: "mon", label: "Lunes" },
  { key: "tue", label: "Martes" },
  { key: "wed", label: "Miércoles" },
  { key: "thu", label: "Jueves" },
  { key: "fri", label: "Viernes" },
  { key: "sat", label: "Sábado" },
  { key: "sun", label: "Domingo" },
];

type Horario = Record<string, [string, string]>;

function leer(raw: string | null | undefined): Horario {
  if (!raw) return {};
  try {
    const d = JSON.parse(raw);
    const out: Horario = {};
    for (const { key } of DIAS) {
      const v = d[key];
      if (Array.isArray(v) && v.length === 2) out[key] = [String(v[0]), String(v[1])];
    }
    return out;
  } catch {
    return {};
  }
}

/** Horario semanal ({"mon": ["08:00", "18:00"], ...}). Sin días = null. */
export function EditorHorario({ value, onChange }: { value: string | null | undefined; onChange: (v: string | null) => void }) {
  const horario = useMemo(() => leer(value), [value]);

  const guardar = (h: Horario) => onChange(Object.keys(h).length ? JSON.stringify(h) : null);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 text-xs">
        <button
          type="button"
          className="rounded-lg border border-line px-2.5 py-1 hover:bg-surface-2"
          onClick={() => guardar(Object.fromEntries(DIAS.slice(0, 5).map((d) => [d.key, ["08:00", "18:00"]])) as Horario)}
        >
          Lunes a viernes 8 a 6
        </button>
        <button
          type="button"
          className="rounded-lg border border-line px-2.5 py-1 hover:bg-surface-2"
          onClick={() =>
            guardar({
              ...(Object.fromEntries(DIAS.slice(0, 5).map((d) => [d.key, ["08:00", "18:00"]])) as Horario),
              sat: ["08:00", "13:00"],
            })
          }
        >
          + sábado 8 a 1
        </button>
      </div>
      {DIAS.map(({ key, label }) => {
        const activo = !!horario[key];
        return (
          <div key={key} className="flex items-center gap-3">
            <label className="flex w-28 items-center gap-2 text-sm text-fg">
              <input
                type="checkbox"
                checked={activo}
                onChange={(e) => {
                  const h = { ...horario };
                  if (e.target.checked) h[key] = h[key] ?? ["08:00", "18:00"];
                  else delete h[key];
                  guardar(h);
                }}
              />
              {label}
            </label>
            {(["desde", "hasta"] as const).map((nombre, i) => (
              <span key={nombre} className="flex items-center gap-3">
                {i === 1 && <span className="text-muted">a</span>}
                <input
                  type="time"
                  aria-label={`${label} ${nombre}`}
                  disabled={!activo}
                  value={horario[key]?.[i] ?? (i === 0 ? "08:00" : "18:00")}
                  onChange={(e) => {
                    const par = [...(horario[key] ?? ["08:00", "18:00"])] as [string, string];
                    par[i] = e.target.value;
                    guardar({ ...horario, [key]: par });
                  }}
                  className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-40"
                />
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}
