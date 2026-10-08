"use client";

import { Button, Check, Input, Note, Select, Textarea } from "@/components/ui";
import { AgentesCampana } from "@/components/agentes-campana";
import { api } from "@/lib/api";
import { CampaignWithStats, MetodoCampana, Trunk, VoiceBot } from "@/lib/types";

/* Formulario de crear/editar campaña (el modal vive en page.tsx). */

export const FORM_CAMPANA_VACIO = {
  name: "",
  trunk_id: "",
  voicebot_id: "",
  max_concurrency: 5,
  retries: 0,
  max_calls_per_day: "",
  max_minutes_per_day: "",
  ai_intent: "",
  message_template: "",
  // Minutos de espera antes de volver a marcar, por resultado (vacío = ya).
  espera_busy: "",
  espera_noanswer: "",
  espera_failed: "",
  metodo: "voizbot" as MetodoCampana,
  grabacion: "todas" as "todas" | "ninguna",
  guion: "",
  // Proporcional y predictivo (ver services/predictivo.py).
  nivel_marcacion: "1",
  nivel_max: "3",
  abandono_objetivo: "3",
  temporizador_abandono: "2",
  mensaje_abandono: "",
  crm_url: "",
};

export type FormCampana = typeof FORM_CAMPANA_VACIO;

const METODOS_AGENTE: { value: MetodoCampana; label: string; detalle: string }[] = [
  {
    value: "predictivo",
    label: "Predictivo (recomendado para volumen)",
    detalle: "Marca varios números por agente libre y se ajusta solo para no dejar clientes esperando.",
  },
  { value: "progresivo", label: "Progresivo", detalle: "Una llamada por agente libre. Nunca deja a un cliente sin agente." },
  { value: "vista_previa", label: "Vista previa", detalle: "El agente ve los datos del cliente y decide cuándo marcar." },
  { value: "manual", label: "Manual", detalle: "El agente elige o escribe el número a llamar." },
  { value: "proporcional", label: "Proporcional (nivel fijo)", detalle: "Un número fijo de llamadas por agente. Solo si lo vas a vigilar." },
];

export const SOBREMARCA = new Set<MetodoCampana>(["proporcional", "predictivo"]);

const INTENCIONES = [
  { value: "confirmar", label: "Confirmar cita" },
  { value: "reagendar", label: "Reagendar cita" },
  { value: "cancelar", label: "Cancelar cita" },
  { value: "agendar", label: "Agendar cita nueva" },
  { value: "cobranza", label: "Cobranza de cartera" },
];

export function FormularioCampana({
  form,
  setForm,
  editing,
  trunks,
  bots,
  onError,
}: {
  form: FormCampana;
  setForm: (f: FormCampana) => void;
  editing: CampaignWithStats | null;
  trunks: Trunk[];
  bots: VoiceBot[];
  onError: (mensaje: string) => void;
}) {
  return (
    <div className="space-y-4">
      <Input guia="campana:nombre" label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />

      <div>
        <span className="mb-1.5 block text-xs font-medium text-fg-soft">¿Quién habla con los clientes?</span>
        <div className="grid grid-cols-2 gap-2">
          {[
            { conAgentes: false, titulo: "Un voizbot", detalle: "Llama y conversa solo, sin personas." },
            { conAgentes: true, titulo: "Mis agentes", detalle: "La central marca y pasa la llamada a un agente." },
          ].map((o) => {
            const activo = (form.metodo !== "voizbot") === o.conAgentes;
            return (
              <button
                key={o.titulo}
                type="button"
                data-guia={o.conAgentes ? "campana:con-agentes" : "campana:con-voizbot"}
                aria-pressed={activo}
                onClick={() =>
                  setForm({ ...form, metodo: o.conAgentes ? (form.metodo === "voizbot" ? "predictivo" : form.metodo) : "voizbot" })
                }
                className={`rounded-xl border p-3 text-left transition-colors ${
                  activo ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                }`}
              >
                <span className="block text-sm font-semibold text-fg">{o.titulo}</span>
                <span className="mt-0.5 block text-xs text-muted">{o.detalle}</span>
              </button>
            );
          })}
        </div>
      </div>

      {form.metodo !== "voizbot" && (
        <div>
          <span className="mb-1.5 block text-xs font-medium text-fg-soft">¿Cómo se marca?</span>
          <div className="space-y-1.5">
            {METODOS_AGENTE.map((m) => (
              <label
                key={m.value}
                data-guia={`campana:metodo-${m.value}`}
                className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-2.5 transition-colors ${
                  form.metodo === m.value ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                }`}
              >
                <input
                  type="radio"
                  name="metodo"
                  className="mt-1 accent-[var(--brand)]"
                  checked={form.metodo === m.value}
                  onChange={() => setForm({ ...form, metodo: m.value })}
                />
                <span>
                  <span className="block text-sm font-medium text-fg">{m.label}</span>
                  <span className="block text-xs text-muted">{m.detalle}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      <Select
        label="Troncal"
        value={form.trunk_id}
        onChange={(v) => setForm({ ...form, trunk_id: v })}
        placeholder="— Elige una troncal —"
        options={trunks.map((t) => ({ value: String(t.id), label: t.enabled ? t.name : `${t.name} (deshabilitada)` }))}
        hint="Por dónde salen las llamadas. Sin troncal la campaña no puede llamar."
      />
      {trunks.length === 0 && (
        <Note tone="warn">Todavía no conectas un proveedor de telefonía: hazlo en Central telefónica → Proveedor de telefonía.</Note>
      )}

      {form.metodo === "voizbot" ? (
        <>
          <Select
            label="Voizbot"
            value={form.voicebot_id}
            onChange={(v) => setForm({ ...form, voicebot_id: v })}
            placeholder="— Elige un voizbot —"
            options={bots.map((b) => ({ value: String(b.id), label: b.name }))}
          />
          <Select
            label="Qué gestiona el bot"
            value={form.ai_intent || "confirmar"}
            onChange={(v) => setForm({ ...form, ai_intent: v })}
            options={INTENCIONES}
            hint="Cobranza informa la deuda y registra promesas de pago; el resto trabaja sobre la agenda de citas."
          />
        <Textarea
          label="Mensaje de apertura personalizado (opcional)"
          value={form.message_template}
          onChange={(v) => setForm({ ...form, message_template: v })}
          rows={3}
          placeholder="Hola {cliente}, te recuerdo tu cita pendiente para el {fecha}. ¿La confirmas?"
          hint={
            form.ai_intent === "cobranza"
              ? "Con {variables} que se rellenan por número al cargarlos. El bot abre SIEMPRE confirmando identidad sin revelar la deuda (protección de datos): este mensaje no se usa como primera frase. Para cobranza, {cliente}, {monto}, {vencimiento} y {factura} cargan/actualizan la deuda en Cobranza."
              : "Con {variables} que se rellenan por número al cargarlos más abajo. El bot dice esto como primera frase y sigue la conversación normal (confirmar, cancelar o reagendar con disponibilidad real). Vacío = saludo genérico."
          }
          mono
        />

        </>
      ) : (
        <>
        {form.metodo === "predictivo" && (
          <div className="grid grid-cols-2 gap-2">
            <Input
              label="Abandono objetivo (%)"
              type="number"
              value={form.abandono_objetivo}
              onChange={(v) => setForm({ ...form, abandono_objetivo: v })}
              hint="Máximo de contestadas sin agente. 3 % es el estándar."
            />
            <Input
              label="Tope de llamadas por agente"
              type="number"
              value={form.nivel_max}
              onChange={(v) => setForm({ ...form, nivel_max: v })}
              hint="De 1 a 5. Nunca marca más que esto."
            />
          </div>
        )}

          <Textarea
            label="Guion para el agente (opcional)"
            value={form.guion}
            onChange={(v) => setForm({ ...form, guion: v })}
            rows={3}
            placeholder="Buenos días, {nombre}. Le habla {agente} de…"
            hint="Con {variables}: {nombre}, {telefono}, {agente}, los campos propios del contacto y las columnas cargadas con el número."
          />
          <Check
            checked={form.ai_intent === "cobranza"}
            onChange={(v) => setForm({ ...form, ai_intent: v ? "cobranza" : "" })}
            label="Es cobranza (respeta el horario de la ley para cobros)"
          />
        </>
      )}

      {form.metodo !== "voizbot" &&
        (editing ? (
          <div className="rounded-xl border border-line p-3">
            <AgentesCampana campaignId={editing.id} />
            <p className="text-xs text-muted">
              Se guardan al marcarlos. Las campañas no usan colas: la central le pasa cada llamada
              contestada al agente listo que más lleva esperando.
            </p>
          </div>
        ) : (
          <Note tone="muted">
            Al crearla, un asistente te guía: cargar tus clientes desde Excel, elegir los agentes e iniciar.
          </Note>
        ))}

      <details className="group rounded-xl border border-line">
        <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-medium text-fg-soft">
          Opciones avanzadas <span className="text-xs font-normal text-muted">(reintentos, topes, grabación, CRM…)</span>
        </summary>
        <div className="space-y-4 border-t border-line p-3">
          {form.metodo === "proporcional" && (
            <>
              <Input
                label="Llamadas por agente libre"
                type="number"
                value={form.nivel_marcacion}
                onChange={(v) => setForm({ ...form, nivel_marcacion: v })}
                hint="De 1 a 5. Con 1 es el progresivo."
              />
              {Number(form.nivel_marcacion) > 1.2 && (
                <Note tone="warn">
                  Un nivel fijo no mira el abandono: con poco contacto rinde y con mucho deja clientes colgados (en simulación, nivel 2 llegó a 22 % de abandono). Si no lo vas a vigilar, usa el predictivo.
                </Note>
              )}
            </>
          )}
          {SOBREMARCA.has(form.metodo) && (
            <>
              <Input
                label="Segundos de espera antes de abandonar"
                type="number"
                value={form.temporizador_abandono}
                onChange={(v) => setForm({ ...form, temporizador_abandono: v })}
                hint="Si el cliente contesta y no hay agente libre en este tiempo, escucha el mensaje y se le vuelve a llamar en 10 minutos. De 1 a 10."
              />
              <Textarea
                label="Mensaje si no hay agente (opcional)"
                value={form.mensaje_abandono}
                onChange={(v) => setForm({ ...form, mensaje_abandono: v })}
                rows={2}
                placeholder="Hola, le llamábamos de … En este momento todos nuestros asesores están ocupados; le volveremos a llamar en unos minutos."
                hint="Vacío = uno estándar con el nombre de la empresa. Se convierte en audio al guardar."
              />
              {editing && !editing.audio_abandono && (
                <Note tone="warn">Todavía no hay audio de abandono: si no hay agente, la llamada se cuelga sin mensaje. Guarda de nuevo para generarlo.</Note>
              )}
            </>
          )}
          {form.metodo !== "voizbot" && (
            <>
              <Select
                label="Grabación"
                value={form.grabacion}
                onChange={(v) => setForm({ ...form, grabacion: v as "todas" | "ninguna" })}
                options={[
                  { value: "todas", label: "Grabar todas las llamadas" },
                  { value: "ninguna", label: "No grabar" },
                ]}
              />
              <Input
                label="URL del CRM (opcional)"
                value={form.crm_url}
                mono
                onChange={(v) => setForm({ ...form, crm_url: v })}
                placeholder="https://micrm.com/clientes?tel={telefono}&doc={documento}"
                hint="La consola del agente muestra «Abrir en el CRM» con esta dirección. Variables: {telefono}, {nombre}, {documento}, {email}, {lead_id}, {contacto_id}, {agente_id}, {llamada_uuid} y las columnas del número. Va firmada (nspbx_ts y nspbx_firma)."
              />
              {editing && form.crm_url.trim() && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    try {
                      const r = await api.post<{ secreto: string }>(`/api/campaigns/${editing.id}/crm-secreto`, {});
                      prompt("Secreto para verificar la firma en tu CRM: HMAC-SHA256 de la URL sin «&nspbx_firma=…».", r.secreto);
                    } catch (e) {
                      onError(e instanceof Error ? e.message : "No se pudo obtener el secreto");
                    }
                  }}
                >
                  Ver secreto de la firma
                </Button>
              )}
            </>
          )}
          <Input
            label="Concurrencia máxima"
            type="number"
            value={form.max_concurrency}
            onChange={(v) => setForm({ ...form, max_concurrency: Number(v) })}
          />
          <Input
            label="Reintentos"
            type="number"
            value={form.retries}
            onChange={(v) => setForm({ ...form, retries: Number(v) })}
          />
          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">Esperar antes de reintentar (minutos)</span>
            <div className="grid grid-cols-3 gap-2">
              <Input label="Ocupado" type="number" value={form.espera_busy} onChange={(v) => setForm({ ...form, espera_busy: v })} />
              <Input label="No contesta" type="number" value={form.espera_noanswer} onChange={(v) => setForm({ ...form, espera_noanswer: v })} />
              <Input label="Falló" type="number" value={form.espera_failed} onChange={(v) => setForm({ ...form, espera_failed: v })} />
            </div>
            <span className="mt-1.5 block text-[11px] leading-snug text-faint">
              Cuántas veces sigue siendo «Reintentos». Vacío = en la vuelta siguiente. Hasta 7 días (10080).
            </span>
          </div>
          <Input
            label="Tope de llamadas por día"
            type="number"
            value={form.max_calls_per_day}
            onChange={(v) => setForm({ ...form, max_calls_per_day: v })}
            hint="Al llegar, la campaña espera al día siguiente (sin dar números por fallidos). Vacío = sin tope."
          />
          <Input
            label="Tope de minutos por día"
            type="number"
            value={form.max_minutes_per_day}
            onChange={(v) => setForm({ ...form, max_minutes_per_day: v })}
            hint="Minutos hablados por la troncal en el día. Vacío = sin tope."
          />
        </div>
      </details>
    </div>
  );
}
