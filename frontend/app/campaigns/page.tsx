"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Check,
  EmptyState,
  ErrorBanner,
  fieldClass,
  Input,
  Modal,
  Note,
  PageHeader,
  Pagination,
  ProgressBar,
  RowActions,
  SearchInput,
  Select,
  Table,
  TableSkeleton,
  Td,
  Textarea,
  Tr,
} from "@/components/ui";
import { AvisoHorarioCampanas } from "@/components/aviso-horario-campanas";
import { api } from "@/lib/api";
import {
  CampaignNumber,
  CampaignNumbersUploadResult,
  CampaignStats,
  CampaignWithStats,
  Trunk,
  MetodoCampana,
  VoiceBot,
} from "@/lib/types";
import { AgentesCampana } from "@/components/agentes-campana";
import { AsistenteCampana } from "@/components/asistente-campana";
import { CargarClientes } from "@/components/cargar-clientes";
import { DiagnosticoCampana } from "@/components/diagnostico-campana";
import { ListasCampana } from "@/components/listas-campana";
import { statusBadge } from "@/lib/utils";

const empty = {
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

const SOBREMARCA = new Set<MetodoCampana>(["proporcional", "predictivo"]);

const INTENCIONES = [
  { value: "confirmar", label: "Confirmar cita" },
  { value: "reagendar", label: "Reagendar cita" },
  { value: "cancelar", label: "Cancelar cita" },
  { value: "agendar", label: "Agendar cita nueva" },
  { value: "cobranza", label: "Cobranza de cartera" },
];

const POR_PAGINA = 50;

function reglasDe(f: typeof empty) {
  const reglas: Record<string, number> = {};
  for (const [resultado, valor] of [
    ["busy", f.espera_busy],
    ["noanswer", f.espera_noanswer],
    ["failed", f.espera_failed],
  ] as const) {
    const n = Number(valor);
    if (valor.trim() && n > 0) reglas[resultado] = Math.round(n);
  }
  return Object.keys(reglas).length ? reglas : null;
}

export default function CampaignsPage() {
  const [items, setItems] = useState<CampaignWithStats[]>([]);
  const [trunks, setTrunks] = useState<Trunk[]>([]);
  const [bots, setBots] = useState<VoiceBot[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<CampaignWithStats | null>(null);
  const [form, setForm] = useState(empty);
  const [selected, setSelected] = useState<CampaignWithStats | null>(null);
  // Asistente que sigue a «Crear»: clientes (Excel) → agentes → iniciar.
  const [asistente, setAsistente] = useState<CampaignWithStats | null>(null);
  const [cargarExcel, setCargarExcel] = useState(false);
  const [numbers, setNumbers] = useState<CampaignNumber[]>([]);
  const [buscarNumero, setBuscarNumero] = useState("");
  const [estadoNumero, setEstadoNumero] = useState("");
  const [offsetNumeros, setOffsetNumeros] = useState(0);
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [bulk, setBulk] = useState("");
  const [uploadResult, setUploadResult] = useState<CampaignNumbersUploadResult | null>(null);
  // Aparte de `error`: ese banner vive fuera del modal de detalle, así
  // que con el modal abierto queda tapado y nunca se llega a ver — un
  // error invisible es lo mismo que no tener validación.
  const [errorNumeros, setErrorNumeros] = useState("");
  const errorNumerosRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [editingNumberId, setEditingNumberId] = useState<number | null>(null);
  const archivoRef = useRef<HTMLInputElement>(null);
  const [editingNumberValue, setEditingNumberValue] = useState("");

  // El modal es alto y el aviso vive arriba de todo — con la vista
  // scrolleada hacia el cuadro de pegar (donde está la atención en ese
  // momento), el error quedaba fuera de pantalla y parecía que el botón
  // "Agregar números" no hacía nada.
  useEffect(() => {
    if (errorNumeros) errorNumerosRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [errorNumeros]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cs, ts, bs] = await Promise.all([
        api.get<CampaignWithStats[]>("/api/campaigns/list/detail"),
        api.get<Trunk[]>("/api/trunks"),
        api.get<VoiceBot[]>("/api/voicebots"),
      ]);
      setItems(cs);
      setTrunks(ts);
      setBots(bs);
      setError("");
      // El detalle abierto muestra el estado al día (p. ej. tras «Iniciar»).
      setSelected((sel) => (sel ? (cs.find((c) => c.id === sel.id) ?? sel) : sel));
      return cs;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    // Con una sola troncal (lo normal) ya queda elegida.
    const troncal = trunks.find((t) => t.enabled);
    setForm({ ...empty, trunk_id: troncal ? String(troncal.id) : "" });
    setModal(true);
  };

  const openEdit = (c: CampaignWithStats) => {
    setEditing(c);
    setForm({
      name: c.name,
      trunk_id: c.trunk_id ? String(c.trunk_id) : "",
      voicebot_id: c.voicebot_id ? String(c.voicebot_id) : "",
      max_concurrency: c.max_concurrency,
      retries: c.retries,
      max_calls_per_day: c.max_calls_per_day != null ? String(c.max_calls_per_day) : "",
      max_minutes_per_day: c.max_minutes_per_day != null ? String(c.max_minutes_per_day) : "",
      ai_intent: c.ai_intent ?? "",
      message_template: c.message_template ?? "",
      espera_busy: c.reglas_reciclaje?.busy != null ? String(c.reglas_reciclaje.busy) : "",
      espera_noanswer: c.reglas_reciclaje?.noanswer != null ? String(c.reglas_reciclaje.noanswer) : "",
      espera_failed: c.reglas_reciclaje?.failed != null ? String(c.reglas_reciclaje.failed) : "",
      metodo: c.metodo ?? "voizbot",
      grabacion: c.grabacion ?? "todas",
      guion: c.guion ?? "",
      nivel_marcacion: String(c.nivel_marcacion ?? 1),
      nivel_max: String(c.nivel_max ?? 3),
      abandono_objetivo: String(c.abandono_objetivo ?? 3),
      temporizador_abandono: String(c.temporizador_abandono ?? 2),
      mensaje_abandono: c.mensaje_abandono ?? "",
      crm_url: c.crm_url ?? "",
    });
    setModal(true);
  };

  // Ver el mismo caso en queues/inbound-routes: sin `saving`, un doble
  // clic creaba la campaña dos veces (y el backend responde 400 por
  // nombre duplicado, así que quedaba un error confuso encima).
  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        trunk_id: form.trunk_id ? Number(form.trunk_id) : null,
        voicebot_id: form.voicebot_id ? Number(form.voicebot_id) : null,
        max_concurrency: Number(form.max_concurrency),
        retries: Number(form.retries),
        max_calls_per_day: form.max_calls_per_day.trim() ? Number(form.max_calls_per_day) : null,
        max_minutes_per_day: form.max_minutes_per_day.trim() ? Number(form.max_minutes_per_day) : null,
        ai_intent: form.ai_intent || null,
        message_template: form.message_template.trim() || null,
        reglas_reciclaje: reglasDe(form),
        metodo: form.metodo,
        grabacion: form.grabacion,
        guion: form.guion.trim() || null,
        ...(form.metodo !== "voizbot" && { crm_url: form.crm_url.trim() }),
        ...(SOBREMARCA.has(form.metodo) && {
          nivel_marcacion: Number(form.nivel_marcacion) || 1,
          nivel_max: Number(form.nivel_max) || 3,
          abandono_objetivo: Number(form.abandono_objetivo) || 3,
          temporizador_abandono: Number(form.temporizador_abandono) || 2,
          mensaje_abandono: form.mensaje_abandono.trim() || null,
        }),
      };
      if (editing) {
        await api.put(`/api/campaigns/${editing.id}`, payload);
        setModal(false);
        await load();
      } else {
        const creada = await api.post<CampaignWithStats>("/api/campaigns", payload);
        setModal(false);
        // Lo siguiente es cargar números y agentes: se abre el detalle de una.
        const lista = await load();
        const nueva = lista?.find((c) => c.id === creada.id);
        if (nueva) setAsistente(nueva);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (c: CampaignWithStats) => {
    if (!confirm(`¿Eliminar la campaña ${c.name}?`)) return;
    try {
      await api.del(`/api/campaigns/${c.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  // Evita que la respuesta de un "Ver" viejo (si alguien hace doble clic
  // y cambia de campaña antes de que la primera termine de cargar) pise
  // los números/stats de la campaña que quedó realmente abierta.
  const detailRequestRef = useRef(0);

  /** URL de números con los filtros y la página vigentes. Centralizada
   *  porque la misma consulta se dispara desde seis lugares distintos
   *  (abrir, agregar, editar, borrar, vaciar, iniciar): armarla a mano en
   *  cada uno hacía que al recargar se perdieran el filtro y la página. */
  const urlNumeros = useCallback(
    (campaignId: number) => {
      const qs = new URLSearchParams({ limit: String(POR_PAGINA), offset: String(offsetNumeros) });
      if (buscarNumero.trim()) qs.set("search", buscarNumero.trim());
      if (estadoNumero) qs.set("estado", estadoNumero);
      return `/api/campaigns/${campaignId}/numbers?${qs.toString()}`;
    },
    [offsetNumeros, buscarNumero, estadoNumero]
  );

  const recargarNumeros = useCallback(
    async (campaignId: number) => {
      setNumbers(await api.get<CampaignNumber[]>(urlNumeros(campaignId)));
    },
    [urlNumeros]
  );

  const openDetail = async (c: CampaignWithStats) => {
    const miPedido = ++detailRequestRef.current;
    setSelected(c);
    setUploadResult(null);
    setErrorNumeros("");
    // El cuadro de números y cualquier edición en curso son de la
    // campaña anterior — sin esto, texto pegado para una campaña podía
    // terminar agregándose por accidente a otra al cambiar de "Ver" sin
    // haber confirmado antes.
    setBulk("");
    cancelEditNumber();
    // Los filtros también se reinician: abrir otra campaña con el
    // buscador de la anterior puesto mostraba "sin números" y parecía
    // que la campaña estaba vacía.
    setBuscarNumero("");
    setEstadoNumero("");
    setOffsetNumeros(0);
    const [nums, st] = await Promise.all([
      api.get<CampaignNumber[]>(`/api/campaigns/${c.id}/numbers?limit=${POR_PAGINA}&offset=0`),
      api.get<CampaignStats>(`/api/campaigns/${c.id}/stats`),
    ]);
    if (detailRequestRef.current !== miPedido) return; // se abrió otra campaña mientras tanto
    setNumbers(nums);
    setStats(st);
  };

  // Buscar/filtrar/paginar dentro del detalle vuelve a pedirle la lista
  // al backend (los números pueden ser miles: filtrarlos en el navegador
  // exigiría traerlos todos, que es justo lo que se quiere evitar).
  useEffect(() => {
    if (!selected) return;
    recargarNumeros(selected.id).catch(() => {});
  }, [selected, recargarNumeros]);

  useEffect(() => {
    setOffsetNumeros(0);
  }, [buscarNumero, estadoNumero]);

  const closeDetail = async () => {
    setSelected(null);
    await load();
  };

  // Las variables salen directo del mensaje de apertura ({cliente},
  // {fecha}, ...) — no hace falta declararlas aparte. Pedirlas dos veces
  // (una al escribir el mensaje, otra en un campo separado antes de
  // pegar los números) era el propio origen de los bugs anteriores: se
  // olvidaba llenar ese segundo campo y los datos se perdían en
  // silencio. Ahora hay una sola fuente de verdad.
  const nombresColumnas = Array.from(
    new Set(Array.from((selected?.message_template ?? "").matchAll(/\{(\w+)\}/g), (m) => m[1]))
  );

  // Un valor de ejemplo por columna según su nombre — se usa tanto para
  // la plantilla descargable como para el placeholder del pegado de
  // abajo. Antes ese placeholder era un string fijo ("...; Camilo
  // Barragán; 2026-08-21 09:00") sin importar qué {variables} usara en
  // realidad el mensaje de apertura: en una campaña de cobranza (que
  // pide cliente/monto/vencimiento/factura, no fecha) mostraba un
  // ejemplo que no correspondía a ninguna de esas columnas.
  const ejemploPara = (nombre: string) => {
    switch (nombre.toLowerCase()) {
      case "fecha":
        return "2026-08-21 09:00";
      case "monto":
        return "250000";
      case "vencimiento":
        return "2026-09-15";
      case "factura":
        return "F-001234";
      default:
        return "Camilo Barragán";
    }
  };

  // Plantilla descargable: encabezado + una fila de ejemplo, con las
  // variables que usa el mensaje de apertura (o cliente/fecha de
  // ejemplo si la campaña todavía no tiene mensaje). Se abre bien en
  // Excel en español, donde ";" es el separador de listas por defecto —
  // el mismo que ya usa el pegado de abajo, así que lo que se descarga
  // y lo que se pega son lo mismo.
  const descargarPlantilla = () => {
    const cols = nombresColumnas.length > 0 ? nombresColumnas : ["cliente", "fecha"];
    const encabezado = ["telefono", ...cols].join(";");
    const ejemplo = ["3011234567", ...cols.map(ejemploPara)].join(";");
    const contenido = `${encabezado}\n${ejemplo}\n`;
    const blob = new Blob(["﻿" + contenido], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "plantilla_numeros.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  // El archivo que se sube es el mismo formato que se pega a mano: se
  // vuelca tal cual en el cuadro de texto para que la persona vea qué
  // va a cargar antes de confirmar, en vez de subirlo a ciegas. Se
  // descarta la primera línea si es el encabezado de la plantilla.
  const cargarArchivo = async (file: File) => {
    const texto = await file.text();
    const lineas = texto.split(/\r?\n/).filter((l) => l.trim());
    if (lineas[0]?.trim().toLowerCase().startsWith("telefono")) lineas.shift();
    setBulk(lineas.join("\n"));
  };

  const addNumbers = async () => {
    const lineas = bulk
      .split("\n")
      .map((linea) => linea.trim())
      .filter(Boolean);
    const parseadas = lineas.map((linea) => {
      // Excel exporta con "," o ";" según el idioma/región de quien lo
      // abrió — se acepta cualquiera de los dos en vez de obligar a
      // reformatear todo a mano.
      const partes = linea.split(linea.includes(";") ? ";" : ",").map((p) => p.trim());
      const [phone, ...valores] = partes;
      return { linea, phone, valores };
    });

    // Si alguna línea trae más datos que {variables} tiene el mensaje de
    // apertura, esos datos de más se perderían en silencio. Se frena acá
    // y se avisa exactamente qué línea sobra, en vez de descartar
    // información sin que nadie lo note.
    const conDatosDeMas = parseadas.filter((p) => p.valores.length > nombresColumnas.length);
    if (conDatosDeMas.length > 0) {
      setErrorNumeros(
        nombresColumnas.length === 0
          ? `${conDatosDeMas.length} línea(s) traen datos además del teléfono, pero el mensaje de apertura de esta campaña no tiene ninguna {variable} — esos datos se perderían. Editá la campaña y agregá algo como {cliente} o {fecha} al mensaje antes de cargarlos.`
          : `${conDatosDeMas.length} línea(s) traen más datos de los que usa el mensaje de apertura (${nombresColumnas.join(", ")}) — revisalas, o agregá la {variable} que falta al mensaje editando la campaña.`
      );
      return;
    }
    setErrorNumeros("");

    const filas = parseadas
      .map(({ phone, valores }) => {
        const vars: Record<string, string> = {};
        nombresColumnas.forEach((nombre, i) => {
          if (valores[i]) vars[nombre] = valores[i];
        });
        return { phone, vars };
      })
      .filter((f) => f.phone);
    if (!selected || filas.length === 0) return;

    try {
      const resultado = await api.post<CampaignNumbersUploadResult>(`/api/campaigns/${selected.id}/numbers`, {
        numbers: filas,
      });
      setUploadResult(resultado);
      // El cuadro de texto NO se vacía solo: que la data que acabás de
      // pegar desaparezca de golpe se leía como que se había borrado en
      // vez de guardado. Se deja a la vista — "Limpiar" es una acción
      // aparte, a propósito, para cuando quieras vaciarlo vos mismo.
      const st = await api.get<CampaignStats>(`/api/campaigns/${selected.id}/stats`);
      setStats(st);
      await recargarNumeros(selected.id);
    } catch (e) {
      setErrorNumeros(e instanceof Error ? e.message : "Error al agregar números");
    }
  };

  const startEditNumber = (n: CampaignNumber) => {
    setEditingNumberId(n.id);
    setEditingNumberValue(n.phone);
  };

  const cancelEditNumber = () => {
    setEditingNumberId(null);
    setEditingNumberValue("");
  };

  const saveEditNumber = async () => {
    if (!selected || editingNumberId === null || !editingNumberValue.trim()) return;
    try {
      await api.put(`/api/campaigns/${selected.id}/numbers/${editingNumberId}`, { phone: editingNumberValue.trim() });
      await recargarNumeros(selected.id);
      cancelEditNumber();
    } catch (e) {
      setErrorNumeros(e instanceof Error ? e.message : "Error al editar el número");
    }
  };

  const removeNumber = async (n: CampaignNumber) => {
    if (!selected) return;
    if (!confirm(`¿Eliminar el número ${n.phone}?`)) return;
    try {
      await api.del(`/api/campaigns/${selected.id}/numbers/${n.id}`);
      await recargarNumeros(selected.id);
      setStats(await api.get<CampaignStats>(`/api/campaigns/${selected.id}/stats`));
    } catch (e) {
      setErrorNumeros(e instanceof Error ? e.message : "Error al eliminar el número");
    }
  };

  // Vacía los YA cargados (no toca el cuadro de arriba, ni las citas que
  // se hayan sincronizado en la Agenda a partir de ellos).
  const clearNumbers = async () => {
    if (!selected || numbers.length === 0) return;
    if (!confirm(`¿Vaciar los ${numbers.length} número(s) cargados en esta campaña? Las citas que ya se sincronizaron en la Agenda no se tocan.`)) return;
    try {
      await api.del(`/api/campaigns/${selected.id}/numbers`);
      await recargarNumeros(selected.id);
      setStats(await api.get<CampaignStats>(`/api/campaigns/${selected.id}/stats`));
      setUploadResult(null);
    } catch (e) {
      setErrorNumeros(e instanceof Error ? e.message : "Error al vaciar los números");
    }
  };

  const start = async (c: CampaignWithStats) => {
    setBusy(true);
    try {
      await api.post(`/api/campaigns/${c.id}/start`);
      await load();
      if (selected) {
        const st = await api.get<CampaignStats>(`/api/campaigns/${c.id}/stats`);
        setStats(st);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al iniciar");
    } finally {
      setBusy(false);
    }
  };

  const stop = async (c: CampaignWithStats) => {
    setBusy(true);
    try {
      await api.post(`/api/campaigns/${c.id}/stop`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al detener");
    } finally {
      setBusy(false);
    }
  };

  const retry = async (c: CampaignWithStats) => {
    setBusy(true);
    try {
      await api.post(`/api/campaigns/${c.id}/retry`);
      await load();
      if (selected?.id === c.id) {
        setStats(await api.get<CampaignStats>(`/api/campaigns/${c.id}/stats`));
        await recargarNumeros(c.id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al reintentar");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Campañas"
        subtitle="Marcación masiva con autodialer"
        actions={<Button onClick={openCreate}>+ Nueva campaña</Button>}
      />
      <AvisoHorarioCampanas />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Lista de campañas" subtitle={`${items.length} registrada(s)`} />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay campañas"
            hint="Crea la primera para lanzar una marcación masiva."
            action={<Button onClick={openCreate}>+ Nueva campaña</Button>}
          />
        ) : (
          <Table head={["Nombre", "Troncal", "Voizbot", "Estado", "Avance", { label: "Acciones", align: "right" }]}>
            {items.map((c, i) => {
              const sb = statusBadge(c.status);
              const total = c.stats.total;
              const progress = total ? Math.round(((total - c.stats.pending - c.stats.dialing) / total) * 100) : 0;
              const running = c.status === "running";
              return (
                <Tr key={c.id} delay={i * 35}>
                  <Td strong>{c.name}</Td>
                  <Td>{c.trunk_name ?? "—"}</Td>
                  <Td>{c.voicebot_name ?? "—"}</Td>
                  <Td>
                    <Badge color={sb.color} dot pulse={running}>
                      {sb.label}
                    </Badge>
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <ProgressBar value={progress} tone={running ? "ok" : "brand"} className="w-24" />
                      <span className="text-xs tabular-nums text-muted">{progress}%</span>
                    </div>
                  </Td>
                  <Td align="right">
                    <RowActions>
                      <Button size="sm" variant="secondary" onClick={() => openDetail(c)}>
                        Ver
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => openEdit(c)}>
                        Editar
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => remove(c)}>
                        Eliminar
                      </Button>
                      {running ? (
                        <Button size="sm" variant="danger" onClick={() => stop(c)} disabled={busy}>
                          Detener
                        </Button>
                      ) : (
                        <>
                          {(c.stats.done > 0 || c.stats.failed > 0) && (
                            <Button size="sm" variant="secondary" onClick={() => retry(c)} disabled={busy}>
                              Reintentar
                            </Button>
                          )}
                          <Button size="sm" variant="success" onClick={() => start(c)} disabled={busy}>
                            Iniciar
                          </Button>
                        </>
                      )}
                    </RowActions>
                  </Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar campaña ${editing.name}` : "Nueva campaña"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save} loading={saving}>
              {editing ? "Guardar" : "Crear"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />

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
                          setError(e instanceof Error ? e.message : "No se pudo obtener el secreto");
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
      </Modal>

      <AsistenteCampana
        key={asistente?.id ?? 0}
        campana={asistente}
        onCerrar={async () => {
          const c = asistente;
          setAsistente(null);
          const lista = await load();
          const actual = lista?.find((x) => x.id === c?.id);
          if (actual) await openDetail(actual);
        }}
      />

      <Modal
        open={cargarExcel && !!selected}
        onClose={() => setCargarExcel(false)}
        size="xl"
        title={`Cargar clientes en ${selected?.name ?? ""}`}
        subtitle="Excel (.xlsx) o CSV. Entran como una lista nueva de la campaña y quedan también en Contactos."
      >
        {selected && (
          <CargarClientes
            campaignId={selected.id}
            variablesMensaje={nombresColumnas}
            onCargado={async () => {
              setStats(await api.get<CampaignStats>(`/api/campaigns/${selected.id}/stats`));
              await recargarNumeros(selected.id);
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!selected}
        onClose={closeDetail}
        size="xl"
        title={selected?.name ?? "Campaña"}
        subtitle={`Troncal: ${selected?.trunk_name ?? "—"} · Voizbot: ${selected?.voicebot_name ?? "—"}`}
        actions={
          selected ? (
            <>
              {selected.status !== "running" && (stats?.done ?? 0) + (stats?.failed ?? 0) > 0 && (
                <Button size="sm" variant="secondary" onClick={() => retry(selected)} disabled={busy}>
                  Reintentar
                </Button>
              )}
              {selected.status === "running" ? (
                <Button size="sm" variant="danger" onClick={() => stop(selected)} disabled={busy}>
                  Detener
                </Button>
              ) : (
                selected.metodo !== "manual" && (
                  <Button size="sm" variant="success" onClick={() => start(selected)} disabled={busy}>
                    Iniciar
                  </Button>
                )
              )}
            </>
          ) : undefined
        }
      >
        {selected && (
          <>
            <DiagnosticoCampana campaignId={selected.id} version={`${selected.status}-${stats?.total ?? 0}`} />
            {errorNumeros && (
              <div ref={errorNumerosRef} className="mb-4">
                <ErrorBanner message={errorNumeros} onClose={() => setErrorNumeros("")} />
              </div>
            )}
            {stats?.tope_alcanzado && (
              <div className="mb-4">
                <Note tone="warn">{stats.tope_alcanzado}</Note>
              </div>
            )}
            {stats && (selected.max_calls_per_day || selected.max_minutes_per_day) && (
              <p className="mb-3 text-xs text-muted">
                Hoy: {stats.llamadas_hoy ?? 0}
                {selected.max_calls_per_day ? ` de ${selected.max_calls_per_day}` : ""} llamadas ·{" "}
                {stats.minutos_hoy ?? 0}
                {selected.max_minutes_per_day ? ` de ${selected.max_minutes_per_day}` : ""} min
              </p>
            )}
            {stats && ((stats.en_espera ?? 0) > 0 || (stats.no_llamar ?? 0) > 0) && (
              <p className="mb-3 text-xs text-muted">
                {(stats.en_espera ?? 0) > 0 && `${stats.en_espera} pendiente(s) esperando su próximo intento o con la lista en pausa`}
                {(stats.en_espera ?? 0) > 0 && (stats.no_llamar ?? 0) > 0 && " · "}
                {(stats.no_llamar ?? 0) > 0 && `${stats.no_llamar} en la lista de no llamar (no se marcan)`}
              </p>
            )}
            {stats && (
              <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Pendientes", value: stats.pending, tone: "text-warn-text" },
                  { label: "Marcando", value: stats.dialing, tone: "text-info-text" },
                  { label: "Completados", value: stats.done, tone: "text-ok-text" },
                  { label: "Fallidos", value: stats.failed, tone: "text-danger-text" },
                ].map((s, i) => (
                  <div
                    key={s.label}
                    style={{ animationDelay: `${i * 50}ms` }}
                    className="animate-fade-up rounded-xl border border-line bg-surface-2 p-3"
                  >
                    <div className={`text-xl font-bold tabular-nums ${s.tone}`}>{s.value}</div>
                    <div className="mt-0.5 text-xs text-muted">{s.label}</div>
                  </div>
                ))}
              </div>
            )}

            {stats?.predictivo && (
              <div className="mb-5">
                <p className="mb-2 text-xs font-medium text-fg-soft">
                  Marcador de hoy
                  {stats.predictivo.nivel != null && ` · marcando ${stats.predictivo.nivel} llamadas por agente libre`}
                </p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: "Intentos", value: stats.predictivo.intentos, tone: "text-fg" },
                    { label: "Contestadas", value: stats.predictivo.contestadas, tone: "text-ok-text" },
                    { label: "Con agente", value: stats.predictivo.asignadas, tone: "text-info-text" },
                    {
                      label: "Abandono",
                      value: stats.predictivo.abandono_pct == null ? "—" : `${stats.predictivo.abandono_pct} %`,
                      tone:
                        stats.predictivo.abandono_pct != null && stats.predictivo.abandono_pct > (selected.abandono_objetivo ?? 3)
                          ? "text-danger-text"
                          : "text-ok-text",
                    },
                  ].map((s) => (
                    <div key={s.label} className="rounded-xl border border-line bg-surface-2 p-3">
                      <div className={`text-xl font-bold tabular-nums ${s.tone}`}>{s.value}</div>
                      <div className="mt-0.5 text-xs text-muted">{s.label}</div>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted">
                  Ahora: {stats.predictivo.timbrando} timbrando · {stats.predictivo.en_espera} esperando agente ·{" "}
                  {stats.predictivo.abandonadas} abandonada(s) hoy
                </p>
              </div>
            )}

            {selected.metodo && selected.metodo !== "voizbot" && <AgentesCampana campaignId={selected.id} />}

            <ListasCampana
              campaignId={selected.id}
              version={stats?.total ?? 0}
              onCambio={async () => setStats(await api.get<CampaignStats>(`/api/campaigns/${selected.id}/stats`))}
            />

            <div className="mb-5">
              {nombresColumnas.length > 0 ? (
                <Note tone="brand">
                  Esta campaña espera <span className="font-mono">{nombresColumnas.join(", ")}</span> — lo que
                  usa su mensaje de apertura. Cada línea de abajo: teléfono; {nombresColumnas.join("; ")}.
                  {selected?.ai_intent === "cobranza" ? (
                    <> "cliente", "monto", "vencimiento" y "factura" además cargan/actualizan la deuda en Cobranza.</>
                  ) : (
                    <> "cliente" y "fecha" (AAAA-MM-DD HH:MM) además cargan/actualizan la cita en la Agenda.</>
                  )}
                </Note>
              ) : (
                <Note tone="muted">
                  Esta campaña no tiene mensaje de apertura con {"{variables}"}, así que cada línea de abajo es
                  solo un teléfono. Si querés un saludo personalizado, editá la campaña y escribí algo como
                  "Hola {"{cliente}"}..." — las variables para cargar los números salen de ahí solas.
                </Note>
              )}
              <div className="mt-2 flex items-center gap-2">
                <Button size="sm" variant="secondary" onClick={descargarPlantilla}>
                  Descargar plantilla
                </Button>
                <Button size="sm" onClick={() => setCargarExcel(true)}>
                  Cargar clientes desde Excel
                </Button>
                <Button size="sm" variant="secondary" onClick={() => archivoRef.current?.click()}>
                  Pegar desde CSV
                </Button>
                <input
                  ref={archivoRef}
                  type="file"
                  accept=".csv,.txt"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) cargarArchivo(file);
                    e.target.value = "";
                  }}
                />
              </div>
              <div className="mt-3">
                <Textarea
                  label="Agregar números (uno por línea)"
                  value={bulk}
                  onChange={setBulk}
                  rows={4}
                  placeholder={
                    nombresColumnas.length > 0
                      ? ["3011234567", ...nombresColumnas.map(ejemploPara)].join("; ")
                      : "5551001\n5551002\n5551003"
                  }
                  hint={
                    nombresColumnas.length > 0
                      ? `Cada línea: teléfono; ${nombresColumnas.join("; ")} — con "," también sirve, como lo exporte Excel. Fecha en cualquier orden día/mes o mes/día, con año de 2 o 4 dígitos.`
                      : undefined
                  }
                  mono
                />
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Button variant="secondary" onClick={addNumbers} disabled={!bulk.trim()}>
                  Agregar números
                </Button>
                {bulk.trim() && (
                  <Button variant="ghost" onClick={() => setBulk("")}>
                    Limpiar
                  </Button>
                )}
              </div>
              {uploadResult && (
                <div className="mt-3 rounded-xl border border-line bg-surface-2 px-3.5 py-3 text-xs">
                  <p className="text-fg-soft">
                    {uploadResult.added} número(s) agregado(s)
                    {uploadResult.updated > 0 && ` · ${uploadResult.updated} actualizado(s) (ya estaban cargados)`}
                    {uploadResult.agenda_creadas > 0 && ` · ${uploadResult.agenda_creadas} cita(s) cargada(s) en la Agenda`}
                  </p>
                  {(uploadResult.bloqueados?.length ?? 0) > 0 && (
                    <>
                      <p className="mt-1.5 text-danger-text">
                        {uploadResult.bloqueados!.length} número(s) no cargado(s): la política de salientes no los deja marcar.
                      </p>
                      <ul className="mt-1 space-y-0.5 text-danger-text">
                        {uploadResult.bloqueados!.map((o) => (
                          <li key={`b-${o.phone}`}>
                            {o.phone}: {o.motivo}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {uploadResult.agenda_omitidas.length > 0 && (
                    <ul className="mt-1.5 space-y-0.5 text-danger-text">
                      {uploadResult.agenda_omitidas.map((o) => (
                        <li key={o.phone}>
                          {o.phone}: {o.motivo}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-line">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
                {/* El total sale de stats (conteo real en la base) y no de
                    numbers.length, que ahora es solo la página visible. */}
                <span className="text-xs font-medium text-fg-soft">Números ({stats?.total ?? numbers.length})</span>
                <div className="flex flex-wrap items-center gap-2">
                  <SearchInput
                    value={buscarNumero}
                    onChange={setBuscarNumero}
                    placeholder="Buscar teléfono o dato…"
                    className="w-52"
                  />
                  <div className="w-40">
                    <Select
                      label=""
                      value={estadoNumero}
                      onChange={setEstadoNumero}
                      placeholder="Cualquier estado"
                      options={[
                        { value: "pending", label: "Pendiente" },
                        { value: "dialing", label: "Marcando" },
                        { value: "done", label: "Completada" },
                        { value: "failed", label: "Fallida" },
                        { value: "busy", label: "Ocupado" },
                        { value: "noanswer", label: "Sin respuesta" },
                      ]}
                    />
                  </div>
                  {(stats?.total ?? 0) > 0 && (
                    <Button size="sm" variant="ghost" onClick={clearNumbers} disabled={selected.status === "running"}>
                      Vaciar lista
                    </Button>
                  )}
                </div>
              </div>
              {numbers.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-muted">
                  {buscarNumero || estadoNumero
                    ? "Ningún número coincide con el filtro."
                    : "Sin números cargados."}
                </p>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-surface-2">
                      <tr className="border-b border-line text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
                        <th className="px-4 py-2.5">Teléfono</th>
                        <th className="px-4 py-2.5">Variables</th>
                        <th className="px-4 py-2.5">Estado</th>
                        <th className="px-4 py-2.5">Intentos</th>
                        <th className="px-4 py-2.5">Error</th>
                        <th className="px-4 py-2.5 text-right">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* Antes acá había un .slice(0, 100) que recortaba
                          en silencio: la lista decía "Números (3500)" y
                          mostraba 100 sin ninguna señal de que faltaba el
                          resto. Ahora la página la decide el backend. */}
                      {numbers.map((n) => {
                        const sb = statusBadge(n.status);
                        const isEditing = editingNumberId === n.id;
                        return (
                          <tr key={n.id} className="border-b border-line/60 transition-colors last:border-0 hover:bg-surface-2">
                            <td className="px-4 py-2 font-mono text-fg-soft">
                              {isEditing ? (
                                <input
                                  className={`${fieldClass} w-32 px-2 py-1 text-xs`}
                                  value={editingNumberValue}
                                  onChange={(e) => setEditingNumberValue(e.target.value)}
                                  autoFocus
                                />
                              ) : (
                                n.phone
                              )}
                            </td>
                            <td className="max-w-[220px] truncate px-4 py-2 text-xs text-faint">
                              {Object.keys(n.vars).length > 0
                                ? Object.entries(n.vars)
                                    .map(([k, v]) => `${k}: ${v}`)
                                    .join(" · ")
                                : "—"}
                            </td>
                            <td className="px-4 py-2">
                              <Badge color={sb.color}>{sb.label}</Badge>
                            </td>
                            <td className="px-4 py-2 text-muted">{n.attempts}</td>
                            <td className="max-w-[180px] truncate px-4 py-2 text-xs text-danger-text">
                              {n.last_error ?? "—"}
                            </td>
                            <td className="whitespace-nowrap px-4 py-2 text-right">
                              <div className="flex justify-end gap-1.5">
                                {isEditing ? (
                                  <>
                                    <Button size="sm" variant="success" onClick={saveEditNumber}>
                                      Guardar
                                    </Button>
                                    <Button size="sm" variant="secondary" onClick={cancelEditNumber}>
                                      Cancelar
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    <Button size="sm" variant="secondary" onClick={() => startEditNumber(n)}>
                                      Editar
                                    </Button>
                                    <Button size="sm" variant="danger" onClick={() => removeNumber(n)}>
                                      Eliminar
                                    </Button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <Pagination
                offset={offsetNumeros}
                limit={POR_PAGINA}
                recibidos={numbers.length}
                onChange={setOffsetNumeros}
              />
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
