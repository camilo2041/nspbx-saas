"use client";

import Link from "next/link";
import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/* ------------------------------------------------------------------
   Clases compartidas
   Los <input>/<textarea> sueltos de algunas páginas importan `fieldClass`
   para verse igual que los componentes de este archivo.
------------------------------------------------------------------ */
export const fieldClass =
  "w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-faint transition-all duration-200 outline-none focus:border-brand focus:bg-surface focus:ring-4 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-60";

/* ------------------------------------------------------------------
   Card
------------------------------------------------------------------ */
export function Card({
  children,
  className = "",
  hover = false,
  delay = 0,
  animate = true,
}: {
  children: ReactNode;
  className?: string;
  /** Eleva la tarjeta y le da brillo al pasar el mouse. */
  hover?: boolean;
  /** Retardo de la animación de entrada, en ms (para escalonar grillas). */
  delay?: number;
  animate?: boolean;
}) {
  return (
    <div
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
      className={`rounded-2xl border border-line bg-gradient-to-b from-surface to-surface-2/60 shadow-[var(--shadow-1)] ${
        hover ? "card-lift sheen" : ""
      } ${animate ? "animate-fade-up" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-text">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-tight text-fg">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`p-5 ${className}`}>{children}</div>;
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="h-6 w-1 shrink-0 rounded-full bg-gradient-to-b from-brand to-accent" />
          <h1 className="bg-gradient-to-br from-fg via-fg to-brand bg-clip-text text-2xl font-bold tracking-tight text-transparent sm:text-[1.7rem]">
            {title}
          </h1>
        </div>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------
   Button
------------------------------------------------------------------ */
type Variant = "primary" | "secondary" | "danger" | "success" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-gradient-to-r from-brand to-accent text-on-brand shadow-[var(--shadow-brand)] hover:from-brand-hover hover:to-brand hover:shadow-[0_10px_26px_-8px_rgb(234_88_12/0.55)]",
  secondary:
    "border border-line bg-surface text-fg-soft hover:border-line-strong hover:bg-surface-2 hover:text-fg",
  danger: "bg-danger text-white shadow-[0_6px_18px_-8px_var(--danger)] hover:brightness-110",
  success: "bg-ok text-white shadow-[0_6px_18px_-8px_var(--ok)] hover:brightness-110",
  ghost: "text-muted hover:bg-surface-2 hover:text-fg",
};

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  type = "button",
  disabled,
  loading,
  title,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: Variant;
  size?: "sm" | "md";
  type?: "button" | "submit";
  disabled?: boolean;
  loading?: boolean;
  title?: string;
  className?: string;
}) {
  const sizes = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm";
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || loading}
      className={`press inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none ${sizes} ${VARIANTS[variant]} ${className}`}
    >
      {loading && (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      )}
      {children}
    </button>
  );
}

export function IconButton({
  children,
  onClick,
  label,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  label: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`press inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-fg ${className}`}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------
   Campos de formulario
------------------------------------------------------------------ */
export function Field({
  label,
  hint,
  children,
}: {
  label?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-xs font-medium text-fg-soft">{label}</span>}
      {children}
      {hint && <span className="mt-1.5 block text-[11px] leading-snug text-faint">{hint}</span>}
    </label>
  );
}

export function Input({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
  hint,
  disabled,
  mono,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  hint?: string;
  disabled?: boolean;
  mono?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type={type}
        value={value}
        required={required}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`${fieldClass} ${mono ? "font-mono" : ""}`}
      />
    </Field>
  );
}

/**
 * Buscador de tabla. Estaba escrito a mano dentro de /calls (input +
 * lupa posicionada absoluta); se extrae acá porque el resto de las
 * pantallas con listados largos —agenda, números de campaña, consumo—
 * no tenía ninguno y no tiene sentido volver a copiar el mismo bloque.
 */
export function SearchInput({
  value,
  onChange,
  placeholder = "Buscar…",
  className = "w-52",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
      >
        <circle cx="11" cy="11" r="7" />
        <path strokeLinecap="round" d="M20 20l-3.5-3.5" />
      </svg>
      <input
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${fieldClass} w-full py-1.5 pl-8 pr-8`}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Limpiar búsqueda"
          title="Limpiar búsqueda"
          className="press absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-faint transition-colors hover:text-fg"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}
    </div>
  );
}

/**
 * Paginación por páginas de tamaño fijo. Trabaja con `offset` (no con
 * número de página) porque es lo que ya aceptan los endpoints del
 * backend, y evita tener que traducir de un lado al otro.
 *
 * `hayMas` se deduce de "vinieron exactamente `limit` filas": el backend
 * no devuelve el total y contarlo en cada request cuesta un COUNT(*)
 * extra sobre tablas que crecen sin techo. La consecuencia es que si el
 * total es múltiplo exacto del tamaño de página, "Siguiente" queda
 * habilitado una vez de más y esa página sale vacía — a cambio de no
 * pagar un conteo en cada carga.
 */
export function Pagination({
  offset,
  limit,
  recibidos,
  onChange,
  cargando = false,
}: {
  offset: number;
  limit: number;
  recibidos: number;
  onChange: (nuevoOffset: number) => void;
  cargando?: boolean;
}) {
  const hayMas = recibidos === limit;
  const desde = recibidos === 0 ? 0 : offset + 1;
  const hasta = offset + recibidos;
  // Sin nada que paginar (cabe entero en la primera página) no se dibuja:
  // una barra con los dos botones apagados es ruido, no información.
  if (offset === 0 && !hayMas) return null;

  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
      <span className="text-xs text-muted">
        Mostrando <span className="font-medium text-fg-soft">{desde}</span>–
        <span className="font-medium text-fg-soft">{hasta}</span>
      </span>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={offset === 0 || cargando}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          ← Anterior
        </Button>
        <Button size="sm" variant="secondary" disabled={!hayMas || cargando} onClick={() => onChange(offset + limit)}>
          Siguiente →
        </Button>
      </div>
    </div>
  );
}

export function Textarea({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
  hint,
  mono,
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      <textarea
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`${fieldClass} resize-y ${mono ? "font-mono" : ""}`}
      />
    </Field>
  );
}

export function Select({
  label,
  value,
  onChange,
  options,
  placeholder,
  hint,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="relative">
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className={`${fieldClass} cursor-pointer appearance-none pr-9`}
        >
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6" />
        </svg>
      </div>
    </Field>
  );
}

export function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-300 disabled:opacity-50 ${
        checked ? "bg-brand shadow-[var(--shadow-brand)]" : "bg-line-strong"
      }`}
    >
      <span
        className={`inline-block h-4.5 w-4.5 transform rounded-full bg-white shadow-sm transition-transform duration-300 ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export function Check({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1.5 py-1.5 text-sm text-fg-soft transition-colors hover:bg-surface-2">
      <span
        className={`flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-[6px] border transition-all duration-200 ${
          checked ? "border-brand bg-brand text-white" : "border-line-strong bg-surface"
        }`}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          className={`h-3 w-3 transition-transform duration-200 ${checked ? "scale-100" : "scale-0"}`}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only"
      />
      {label}
    </label>
  );
}

/* ------------------------------------------------------------------
   Badge
------------------------------------------------------------------ */
const BADGES: Record<string, string> = {
  slate: "bg-surface-3 text-muted ring-line",
  green: "bg-ok-soft text-ok-text ring-ok/25",
  red: "bg-danger-soft text-danger-text ring-danger/25",
  amber: "bg-warn-soft text-warn-text ring-warn/25",
  blue: "bg-info-soft text-info-text ring-info/25",
  indigo: "bg-brand-soft text-brand-text ring-brand/25",
  violet: "bg-violet-soft text-violet-text ring-violet/25",
};

export function Badge({
  children,
  color = "slate",
  dot = false,
  pulse = false,
}: {
  children: ReactNode;
  color?: string;
  /** Muestra un punto de estado antes del texto. */
  dot?: boolean;
  /** Anima el punto (para estados "en curso"). */
  pulse?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
        BADGES[color] ?? BADGES.slate
      }`}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5">
          {pulse && <span className="ping-ring absolute inset-0" />}
          <span className="relative h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {children}
    </span>
  );
}

export function StatusDot({ color = "ok", pulse = true }: { color?: string; pulse?: boolean }) {
  const tone = color === "ok" ? "text-ok" : color === "warn" ? "text-warn" : color === "danger" ? "text-danger" : "text-info";
  return (
    <span className={`relative flex h-2 w-2 ${tone}`}>
      {pulse && <span className="ping-ring absolute inset-0" />}
      <span className="relative h-2 w-2 rounded-full bg-current" />
    </span>
  );
}

/* ------------------------------------------------------------------
   Modal
------------------------------------------------------------------ */
const MODAL_SIZES = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  actions,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  /** Acciones extra en la cabecera, junto al botón de cerrar. */
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: keyof typeof MODAL_SIZES;
}) {
  // El modal se monta en <body> y no donde se declara. `position: fixed` se
  // mide contra la ventana solo si ningún ancestro tiene `transform`, y el
  // contenedor del layout lleva `animate-fade-up`, que deja uno aplicado:
  // eso convertía al contenedor en el marco de referencia y el modal
  // aparecía al final de la página (medido: 2181 px abajo, fuera de vista),
  // dejando solo el fondo borroso. Con el portal queda fuera de su alcance.
  const [montado, setMontado] = useState(false);
  useEffect(() => setMontado(true), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open || !montado) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="animate-fade-soft absolute inset-0 bg-slate-950/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className={`animate-pop relative flex max-h-[88vh] w-full flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-3)] ${MODAL_SIZES[size]}`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold tracking-tight text-fg">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {actions}
            <IconButton label="Cerrar" onClick={onClose} className="h-8 w-8">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </IconButton>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-line bg-surface-2 px-5 py-3.5">{footer}</div>
        )}
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------
   Estados: carga, error, vacío
------------------------------------------------------------------ */
export function Spinner({ size = "md" }: { size?: "sm" | "md" }) {
  const px = size === "sm" ? "h-5 w-5 border-2" : "h-8 w-8 border-[3px]";
  return (
    <div className="flex items-center justify-center py-12">
      <div className={`${px} animate-spin rounded-full border-brand/25 border-t-brand`} />
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} />;
}

/** Placeholder animado con la forma de la tabla que se está cargando. */
export function TableSkeleton({ cols = 5, rows = 4 }: { cols?: number; rows?: number }) {
  return (
    <div className="divide-y divide-line">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-5 py-4">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton
              key={c}
              className="h-4 flex-1"
              // Ancho variable para que no parezca una rejilla perfecta.
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function ErrorBanner({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="animate-fade-up flex items-start gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger-text">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mt-0.5 h-4 w-4 shrink-0">
        <circle cx="12" cy="12" r="9" />
        <path strokeLinecap="round" d="M12 8v5M12 16h.01" />
      </svg>
      <span className="flex-1">{message}</span>
      {onClose && (
        <button onClick={onClose} aria-label="Descartar" className="shrink-0 opacity-60 hover:opacity-100">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="animate-fade-up flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-soft to-info-soft text-brand-text shadow-[var(--shadow-1)] ring-1 ring-brand/15">
        {icon ?? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <path strokeLinecap="round" d="M3 10h18M8 15h8" />
          </svg>
        )}
      </div>
      <p className="text-sm font-medium text-fg-soft">{title}</p>
      {hint && <p className="max-w-md text-xs leading-relaxed text-faint">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------
   Tabla
------------------------------------------------------------------ */
export type Column = string | { label: string; align?: "left" | "right" | "center" };

export function Table({ head, children }: { head: Column[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line bg-gradient-to-b from-surface-2 to-surface-3/70 text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
            {head.map((c, i) => {
              const col = typeof c === "string" ? { label: c, align: "left" as const } : c;
              return (
                <th
                  key={i}
                  className={`px-5 py-3 ${col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : ""}`}
                >
                  {col.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Tr({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  return (
    <tr
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
      className="animate-fade-up border-b border-line/60 transition-colors last:border-0 hover:bg-brand-soft/40"
    >
      {children}
    </tr>
  );
}

export function Td({
  children,
  className = "",
  mono,
  strong,
  muted,
  align,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
  strong?: boolean;
  muted?: boolean;
  align?: "right" | "center";
}) {
  return (
    <td
      className={`px-5 py-3 ${mono ? "font-mono" : ""} ${
        strong ? "font-medium text-fg" : muted ? "text-muted" : "text-fg-soft"
      } ${align === "right" ? "text-right" : align === "center" ? "text-center" : ""} ${className}`}
    >
      {children}
    </td>
  );
}

/** Contenedor de acciones de fila: se revelan al pasar el mouse en escritorio. */
export function RowActions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-end gap-1.5">{children}</div>;
}

/* ------------------------------------------------------------------
   Métricas
------------------------------------------------------------------ */
const STAT_TONES: Record<string, { chip: string; bar: string }> = {
  sky: { chip: "bg-info-soft text-info-text", bar: "from-sky-400 to-cyan-400" },
  emerald: { chip: "bg-ok-soft text-ok-text", bar: "from-emerald-400 to-teal-400" },
  violet: { chip: "bg-violet-soft text-violet-text", bar: "from-orange-400 to-amber-400" },
  amber: { chip: "bg-warn-soft text-warn-text", bar: "from-amber-400 to-orange-400" },
  indigo: { chip: "bg-brand-soft text-brand-text", bar: "from-orange-400 to-amber-500" },
  rose: { chip: "bg-danger-soft text-danger-text", bar: "from-rose-400 to-pink-400" },
};

/** Número que cuenta hacia arriba al aparecer. Si el valor no es numérico se muestra tal cual. */
export function AnimatedNumber({ value, duration = 700 }: { value: ReactNode; duration?: number }) {
  const target = typeof value === "number" ? value : Number(value);
  const numeric = typeof value !== "object" && Number.isFinite(target);
  const [display, setDisplay] = useState(numeric ? 0 : null);
  const frame = useRef<number | null>(null);
  // Punto de partida de la animación: el valor que ya se estaba mostrando, para
  // que un refresco en vivo no rebote a cero antes de subir al nuevo total.
  const from = useRef(0);

  useEffect(() => {
    if (!numeric) return;
    const start = performance.now();
    const origin = from.current;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      // easeOutCubic: arranca rápido y frena al llegar al valor final
      const eased = 1 - Math.pow(1 - p, 3);
      const current = Math.round(origin + (target - origin) * eased);
      from.current = current;
      setDisplay(current);
      if (p < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [target, numeric, duration]);

  if (!numeric) return <>{value}</>;
  return <>{display ?? 0}</>;
}

export function StatCard({
  label,
  value,
  color = "sky",
  icon,
  hint,
  href,
  delay = 0,
}: {
  label: string;
  value: ReactNode;
  color?: keyof typeof STAT_TONES;
  icon?: ReactNode;
  hint?: string;
  href?: string;
  delay?: number;
}) {
  const tone = STAT_TONES[color] ?? STAT_TONES.sky;
  const body = (
    <Card hover delay={delay} className="group relative h-full overflow-hidden p-4">
      <span
        aria-hidden
        className={`absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r ${tone.bar} opacity-70 transition-opacity duration-300 group-hover:opacity-100`}
      />
      <div className="flex items-center gap-4">
        {icon && (
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 ${tone.chip}`}
          >
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <div className="text-2xl font-bold tracking-tight text-fg tabular-nums">
            <AnimatedNumber value={value} />
          </div>
          <div className="truncate text-xs text-muted">{label}</div>
          {hint && <div className="mt-0.5 truncate text-[11px] text-faint">{hint}</div>}
        </div>
      </div>
    </Card>
  );

  if (!href) return body;
  return (
    <Link href={href} className="block h-full focus-visible:outline-none">
      {body}
    </Link>
  );
}

/* ------------------------------------------------------------------
   Progreso
------------------------------------------------------------------ */
export function ProgressBar({
  value,
  className = "",
  tone = "brand",
}: {
  /** Porcentaje 0-100. */
  value: number;
  className?: string;
  tone?: "brand" | "ok" | "warn" | "danger";
}) {
  const bar =
    tone === "ok"
      ? "from-emerald-500 to-teal-400"
      : tone === "warn"
        ? "from-amber-500 to-orange-400"
        : tone === "danger"
          ? "from-rose-600 to-red-500"
          : "from-orange-500 to-amber-400";
  return (
    <div className={`h-1.5 overflow-hidden rounded-full bg-surface-3 ${className}`}>
      <div
        className={`h-full rounded-full bg-gradient-to-r ${bar} transition-[width] duration-700 ease-out`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------
   Segmented control (elegir entre 2-3 opciones)
------------------------------------------------------------------ */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; disabled?: boolean; title?: string }[];
}) {
  return (
    <div className="flex gap-1.5 rounded-xl border border-line bg-surface-2 p-1">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            disabled={o.disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40 ${
              active
                ? "bg-surface text-brand-text shadow-[var(--shadow-1)] ring-1 ring-line"
                : "text-muted hover:text-fg"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------
   Nota / aviso en línea
------------------------------------------------------------------ */
export function Note({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warn" | "brand" | "muted";
}) {
  const tones = {
    info: "border-info/25 bg-info-soft text-info-text",
    warn: "border-warn/25 bg-warn-soft text-warn-text",
    brand: "border-brand/25 bg-brand-soft text-brand-text",
    muted: "border-line bg-surface-2 text-muted",
  }[tone];
  return <div className={`rounded-xl border px-3.5 py-2.5 text-xs leading-relaxed ${tones}`}>{children}</div>;
}
