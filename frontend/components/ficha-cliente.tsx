"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSoftphone } from "@/lib/softphone-context";
import { PERMISOS } from "@/lib/types";

interface Ficha {
  numero: string;
  contacto: {
    id: number;
    nombre: string;
    documento: string | null;
    email: string | null;
    ciudad: string | null;
    campos: { nombre: string; valor: unknown }[];
  } | null;
  no_llamar: boolean;
  notas: { texto: string; autor: string | null; created_at: string }[];
  llamadas: { started_at: string | null; direccion: string; estado: string; billsec: number; cola: string | null }[];
  puede_crm: boolean;
}

const ESTADO: Record<string, string> = {
  answered: "contestada",
  no_answer: "sin respuesta",
  busy: "ocupado",
  voicemail: "dejó mensaje",
  cancelled: "colgó",
  failed: "falló",
};

const fecha = (iso: string | null) =>
  iso
    ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" })
    : "—";

/**
 * Quién llama, mientras suena y durante la llamada: la ficha del CRM, sus
 * últimas notas y llamadas (backend: services/ficha.py). Solo para números
 * externos (7+ dígitos); se puede cerrar y vuelve con la próxima llamada.
 */
export function FichaCliente() {
  const { phase, remoteParty } = useSoftphone();
  const { puede } = useAuth();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [cerrada, setCerrada] = useState<string | null>(null);
  const activa = phase === "incoming" || phase === "in-call" || phase === "outgoing";
  const numero = (remoteParty || "").replace(/[^\d+]/g, "");
  const buscar = activa && numero.replace(/\D/g, "").length >= 7 && puede(PERMISOS.softphone);

  useEffect(() => {
    if (!buscar) return;
    let vivo = true;
    api
      .get<Ficha>(`/api/llamada/ficha?numero=${encodeURIComponent(numero)}`)
      .then((f) => vivo && setFicha(f))
      .catch(() => vivo && setFicha(null));
    return () => {
      vivo = false;
    };
  }, [buscar, numero]);

  if (!buscar || !ficha || ficha.numero !== numero || cerrada === numero) return null;
  const c = ficha.contacto;
  return (
    <aside
      aria-label="Ficha de quien llama"
      className="animate-pop fixed bottom-5 left-5 z-[95] w-80 max-w-[calc(100vw-2.5rem)] rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-3)] lg:left-[272px]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            {phase === "incoming" ? "Te está llamando" : "En llamada con"}
          </p>
          <p className="truncate text-base font-semibold text-fg">{c?.nombre || "Cliente nuevo"}</p>
          <p className="font-mono text-xs text-fg-soft">{numero}</p>
        </div>
        <button
          type="button"
          onClick={() => setCerrada(numero)}
          aria-label="Cerrar la ficha"
          className="rounded-lg px-2 py-1 text-muted hover:bg-surface-2 hover:text-fg"
        >
          ✕
        </button>
      </div>

      {ficha.no_llamar && (
        <p className="mt-2 rounded-lg bg-danger-soft px-2.5 py-1.5 text-xs text-danger-text">Pidió no ser llamado (lista «no llamar»).</p>
      )}

      {c && (
        <dl className="mt-3 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
          {c.documento && (
            <>
              <dt className="text-muted">Documento</dt>
              <dd className="text-fg-soft">{c.documento}</dd>
            </>
          )}
          {c.ciudad && (
            <>
              <dt className="text-muted">Ciudad</dt>
              <dd className="text-fg-soft">{c.ciudad}</dd>
            </>
          )}
          {c.email && (
            <>
              <dt className="text-muted">Correo</dt>
              <dd className="truncate text-fg-soft">{c.email}</dd>
            </>
          )}
          {c.campos.slice(0, 4).map((f) => (
            <div key={f.nombre} className="contents">
              <dt className="text-muted">{f.nombre}</dt>
              <dd className="truncate text-fg-soft">{String(f.valor)}</dd>
            </div>
          ))}
        </dl>
      )}

      {ficha.notas.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Últimas notas</p>
          <ul className="mt-1 space-y-1">
            {ficha.notas.map((n, i) => (
              <li key={i} className="rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs text-fg-soft">
                <span className="line-clamp-2">{n.texto}</span>
                <span className="block text-[10px] text-muted">
                  {n.autor ? `${n.autor} · ` : ""}
                  {fecha(n.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Llamadas anteriores</p>
        {ficha.llamadas.length === 0 ? (
          <p className="mt-1 text-xs text-muted">Es la primera vez que llama.</p>
        ) : (
          <ul className="mt-1 space-y-0.5 text-xs text-fg-soft">
            {ficha.llamadas.map((l, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span>
                  {fecha(l.started_at)} · {l.direccion === "inbound" ? "entrante" : "saliente"}
                  {l.cola ? ` · ${l.cola}` : ""}
                </span>
                <span className="text-muted">{ESTADO[l.estado] ?? l.estado}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {ficha.puede_crm && (
        <Link
          href={c ? `/crm?contacto=${c.id}` : `/crm?nuevo=${encodeURIComponent(numero)}`}
          className="mt-3 inline-block text-xs font-semibold text-brand-text underline"
        >
          {c ? "Abrir en Contactos" : "Guardar como contacto"}
        </Link>
      )}
    </aside>
  );
}
