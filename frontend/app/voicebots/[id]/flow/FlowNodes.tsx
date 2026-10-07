"use client";

import { Handle, Position } from "@xyflow/react";
import { FlowNodeData } from "@/lib/types";

const DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

function NodeShell({
  color,
  icon,
  title,
  selected,
  children,
}: {
  color: string;
  icon: string;
  title: string;
  selected?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`w-64 overflow-hidden rounded-2xl border bg-surface shadow-[var(--shadow-2)] transition-all duration-200 ${
        selected
          ? "border-brand shadow-[var(--shadow-3)] ring-2 ring-brand/30"
          : "border-line hover:border-line-strong"
      }`}
    >
      <div className={`flex items-center gap-2 px-3 py-2 ${color}`}>
        <span className="text-sm">{icon}</span>
        <span className="truncate text-xs font-semibold text-white">{title}</span>
      </div>
      <div className="px-3 py-2.5 text-xs text-fg-soft">{children}</div>
    </div>
  );
}

export function MenuNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-marca"
      icon="🔊"
      title={data.label || "Menú de audio"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      {data.start && (
        <div className="mb-1.5 inline-block rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-text">
          Nodo inicial
        </div>
      )}
      <div className="mb-2 truncate">
        {data.audio_path
          ? "🎵 Audio propio cargado"
          : data.tts_text
            ? `🗣 "${data.tts_text.slice(0, 40)}"`
            : "Sin audio configurado"}
      </div>
      <div className="grid grid-cols-6 gap-1">
        {DIGITS.map((d) => (
          <div
            key={d}
            className="relative flex h-6 items-center justify-center rounded-md bg-surface-3 font-mono text-[10px] text-fg-soft"
          >
            {d}
            <Handle type="source" position={Position.Right} id={d} style={{ top: "50%", background: "#6366f1" }} />
          </div>
        ))}
      </div>
    </NodeShell>
  );
}

export function TransferNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-gradient-to-r from-emerald-600 to-teal-600"
      icon="📞"
      title={data.label || "Transferir"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      <div>
        {data.extension === "ai_agent" ? "Voizbot con IA" : DESTINO[data.destino_tipo || "extension"]}
        {data.extension !== "ai_agent" && <span className="ml-1 font-mono text-fg">{data.extension || "—"}</span>}
      </div>
      {(data.whisper_audio_path || data.whisper_text) && (
        <div className="mt-1 text-[11px] text-ok-text">🗨 Con aviso previo al agente</div>
      )}
    </NodeShell>
  );
}

const DESTINO: Record<string, string> = { extension: "Extensión", grupo: "Grupo", buzon: "Buzón de", numero: "Número" };

export function HorarioNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-gradient-to-r from-amber-500 to-orange-500"
      icon="🕘"
      title={data.label || "¿Estamos abiertos?"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      {data.start && (
        <div className="mb-1.5 inline-block rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-text">
          Nodo inicial
        </div>
      )}
      <div className="mb-2">{data.horario ? "Según el horario de atención" : "Sin horario: siempre abierto"}</div>
      {[
        { id: "abierto", texto: "Abierto", tono: "bg-ok-soft text-ok-text" },
        { id: "cerrado", texto: "Cerrado", tono: "bg-danger-soft text-danger-text" },
      ].map((s) => (
        <div key={s.id} className={`relative mb-1 rounded-md px-2 py-1 text-[11px] font-medium ${s.tono}`}>
          {s.texto}
          <Handle type="source" position={Position.Right} id={s.id} style={{ top: "50%", background: "#f59e0b" }} />
        </div>
      ))}
    </NodeShell>
  );
}

export function HangupNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-gradient-to-r from-rose-600 to-pink-600"
      icon="☎"
      title={data.label || "Colgar"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      <div className="truncate">
        {data.audio_path
          ? "🎵 Audio final propio"
          : data.tts_text
            ? `🗣 "${data.tts_text.slice(0, 40)}"`
            : "Cuelga sin mensaje"}
      </div>
    </NodeShell>
  );
}

/** Lo que React Flow le pasa a cada nodo (solo lo que usan las vistas). */
type PropsNodo = { data: FlowNodeData; selected?: boolean };

export const nodeTypes = {
  menu: (p: PropsNodo) => <MenuNodeView data={p.data} selected={p.selected} />,
  transfer: (p: PropsNodo) => <TransferNodeView data={p.data} selected={p.selected} />,
  hangup: (p: PropsNodo) => <HangupNodeView data={p.data} selected={p.selected} />,
  horario: (p: PropsNodo) => <HorarioNodeView data={p.data} selected={p.selected} />,
};
