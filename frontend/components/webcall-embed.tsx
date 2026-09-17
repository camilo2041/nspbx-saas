"use client";

import { useMemo, useState } from "react";

import { Button, Card, CardBody, CardHeader, Input, Note, Select, Textarea, Toggle } from "@/components/ui";
import type { Queue, SystemSettings } from "@/lib/types";

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

function parseHorario(raw: string | null): Horario {
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

/**
 * Sección de Ajustes para el widget "hablar con un agente" embebible en
 * sitios web (ver app/api/webcall.py). Todo el estado vive en el `form`
 * de la página de Ajustes; acá solo se edita y se muestra el snippet.
 */
export function WebcallEmbed({
  value,
  onPatch,
  queues,
}: {
  value: SystemSettings;
  onPatch: (p: Partial<SystemSettings>) => void;
  queues: Queue[];
}) {
  const horario = useMemo(() => parseHorario(value.webcall_schedule), [value.webcall_schedule]);
  const [copiado, setCopiado] = useState(false);

  const setHorario = (h: Horario) => {
    const limpio = Object.keys(h).length ? JSON.stringify(h) : null;
    onPatch({ webcall_schedule: limpio });
  };

  const toggleDia = (key: string, on: boolean) => {
    const h = { ...horario };
    if (on) h[key] = h[key] ?? ["08:00", "18:00"];
    else delete h[key];
    setHorario(h);
  };

  const setHora = (key: string, idx: 0 | 1, hhmm: string) => {
    const h = { ...horario };
    const par = (h[key] ?? ["08:00", "18:00"]).slice() as [string, string];
    par[idx] = hhmm;
    h[key] = par;
    setHorario(h);
  };

  const origin = typeof window !== "undefined" ? window.location.origin : "https://TU-PBX";
  const snippet = `<script src="${origin}/webcall.js" data-host="${origin}" async></script>`;

  const copiar = () => {
    navigator.clipboard?.writeText(snippet).then(() => {
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    });
  };

  const queueOk = queues.some((q) => q.id === value.webcall_queue_id && q.enabled);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader
          title="Botón de llamada para tu sitio web"
          subtitle="Un visitante hace clic en una burbuja flotante y habla con un agente por el navegador (WebRTC). Obtiene una extensión temporal aislada que solo puede entrar a la cola que elijas."
        />
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between gap-4 rounded-xl border border-line bg-surface-2 p-3">
            <div>
              <div className="text-sm font-semibold text-fg">Activar el widget</div>
              <div className="text-[11px] text-muted">
                Mientras esté apagado, <span className="font-mono">/webcall</span> y el script no atienden a nadie.
              </div>
            </div>
            <Toggle checked={value.webcall_enabled} onChange={(v) => onPatch({ webcall_enabled: v })} />
          </div>

          <Select
            label="Cola que atiende las llamadas web"
            value={value.webcall_queue_id ? String(value.webcall_queue_id) : ""}
            onChange={(v) => onPatch({ webcall_queue_id: v ? Number(v) : null })}
            placeholder="— Elegí una cola —"
            options={queues.map((q) => ({
              value: String(q.id),
              label: `${q.name} (${q.extension})${q.enabled ? "" : " — deshabilitada"}`,
            }))}
            hint="Los agentes de esta cola reciben las llamadas del sitio como cualquier otra llamada entrante."
          />
          {value.webcall_enabled && !queueOk && (
            <Note tone="warn">Elegí una cola habilitada: sin eso el botón responde «servicio no disponible».</Note>
          )}

          <Input
            label="Máximo de llamadas web simultáneas"
            type="number"
            value={value.webcall_max_concurrent}
            onChange={(v) => onPatch({ webcall_max_concurrent: Math.max(1, Number(v) || 1) })}
            hint="Al alcanzarlo, el botón responde «todos los agentes están ocupados». Protege la central de un pico o un abuso."
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Anti-abuso (Cloudflare Turnstile)" subtitle="Captcha invisible antes de entregar la extensión temporal. Gratis; se crea el sitio en el panel de Cloudflare." />
        <CardBody className="space-y-4">
          <Input
            label="Site key"
            value={value.webcall_turnstile_site_key ?? ""}
            onChange={(v) => onPatch({ webcall_turnstile_site_key: v || null })}
            placeholder="0x4AAAAAAA..."
            mono
          />
          <Input
            label="Secret key"
            value={value.webcall_turnstile_secret ?? ""}
            onChange={(v) => onPatch({ webcall_turnstile_secret: v || null })}
            placeholder="0x4AAAAAAA..."
            mono
          />
          <Note tone="info">
            Si dejás estos campos vacíos, no se pide captcha (útil para probar). El rate-limit por IP sigue activo igual.
          </Note>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Horario de atención" subtitle="Fuera de estas franjas el widget muestra el mensaje de «fuera de horario» y no genera ninguna llamada. Sin ningún día marcado: atiende 24/7." />
        <CardBody className="space-y-2">
          {DIAS.map(({ key, label }) => {
            const activo = !!horario[key];
            return (
              <div key={key} className="flex items-center gap-3">
                <label className="flex w-28 items-center gap-2 text-sm text-fg">
                  <input
                    type="checkbox"
                    checked={activo}
                    onChange={(e) => toggleDia(key, e.target.checked)}
                  />
                  {label}
                </label>
                <input
                  type="time"
                  disabled={!activo}
                  value={horario[key]?.[0] ?? "08:00"}
                  onChange={(e) => setHora(key, 0, e.target.value)}
                  className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-40"
                />
                <span className="text-muted">a</span>
                <input
                  type="time"
                  disabled={!activo}
                  value={horario[key]?.[1] ?? "18:00"}
                  onChange={(e) => setHora(key, 1, e.target.value)}
                  className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-sm disabled:opacity-40"
                />
              </div>
            );
          })}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Textos que ve el visitante" />
        <CardBody className="space-y-4">
          <Input
            label="Invitación"
            value={value.webcall_greeting ?? ""}
            onChange={(v) => onPatch({ webcall_greeting: v || null })}
            placeholder="Presione para hablar con un agente"
          />
          <Input
            label="Texto del botón"
            value={value.webcall_button_text ?? ""}
            onChange={(v) => onPatch({ webcall_button_text: v || null })}
            placeholder="Hablar con un agente"
          />
          <Textarea
            label="Mensaje fuera de horario"
            value={value.webcall_offline_text ?? ""}
            onChange={(v) => onPatch({ webcall_offline_text: v || null })}
            placeholder="Estamos fuera de horario de atención"
          />
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="Instalar en un sitio web" subtitle="Pegá esta línea antes de </body> en cualquier página." />
        <CardBody className="space-y-3">
          <pre className="overflow-x-auto rounded-xl border border-line bg-surface-2 p-3 text-[12px] text-fg">
            {snippet}
          </pre>
          <div className="flex items-center gap-3">
            <Button variant="secondary" size="sm" onClick={copiar}>
              {copiado ? "Copiado" : "Copiar"}
            </Button>
            <a
              href="/webcall"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-semibold text-brand"
            >
              Previsualizar la página →
            </a>
          </div>
          <Note tone="info">
            Guardá los cambios antes de probar: el widget lee esta configuración del servidor.
          </Note>
        </CardBody>
      </Card>
    </div>
  );
}
