"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  Note,
  PageHeader,
  RowActions,
  Segmented,
  Select,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { esperarMonitoreo, useSoftphone } from "@/lib/softphone-context";
import {
  AgenteEnVivo,
  CampanaEnVivo,
  CodigoPausa,
  MiMonitoreo,
  ModoMonitoreo,
  PERMISOS,
  TokenWallboard,
} from "@/lib/types";
import { ESTADOS, reloj } from "@/lib/supervision";

const CADA_MS = 2000;

const MODOS: { value: ModoMonitoreo; label: string; title: string }[] = [
  { value: "escuchar", label: "Escuchar", title: "Oyes al agente y al cliente; nadie te oye" },
  { value: "susurrar", label: "Susurrar", title: "El agente te oye; el cliente no" },
  { value: "intervenir", label: "Intervenir", title: "Hablas con los dos" },
];

const METODOS: Record<string, string> = {
  manual: "Manual",
  vista_previa: "Vista previa",
  progresivo: "Progresivo",
  proporcional: "Proporcional",
  predictivo: "Predictivo",
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${v} %`);

/**
 * Supervisor: agentes y campañas en vivo (se refresca cada 2 s) y, con
 * supervision:intervenir, escuchar, susurrar, intervenir, forzar pausa o
 * salida, nivel en caliente y pausar la campaña. Todo queda en la auditoría.
 */
export default function SupervisionPage() {
  const { puede } = useAuth();
  const { connState } = useSoftphone();
  const interviene = puede(PERMISOS.supervisionIntervenir);
  const [agentes, setAgentes] = useState<AgenteEnVivo[] | null>(null);
  const [campanas, setCampanas] = useState<CampanaEnVivo[] | null>(null);
  const [monitor, setMonitor] = useState<MiMonitoreo | null>(null);
  const [error, setError] = useState("");
  const [filtroCampana, setFiltroCampana] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");
  // Segundos desde la última foto: el cronómetro avanza entre una y otra.
  const [tick, setTick] = useState(0);
  const recibidoRef = useRef(0);
  const [pausaPara, setPausaPara] = useState<AgenteEnVivo | null>(null);
  const [nivelPara, setNivelPara] = useState<CampanaEnVivo | null>(null);
  const [tokens, setTokens] = useState(false);
  const [trabajando, setTrabajando] = useState("");

  const cargar = useCallback(async () => {
    try {
      const [a, c, m] = await Promise.all([
        api.get<AgenteEnVivo[]>("/api/supervision/agentes"),
        api.get<CampanaEnVivo[]>("/api/supervision/campanas"),
        interviene ? api.get<MiMonitoreo | null>("/api/supervision/monitoreo") : Promise.resolve(null),
      ]);
      setAgentes(a);
      setCampanas(c);
      setMonitor(m);
      esperarMonitoreo(m?.token ?? null);
      recibidoRef.current = Date.now();
      setTick(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la supervisión");
    }
  }, [interviene]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
    const datos = setInterval(cargar, CADA_MS);
    const cronometro = setInterval(() => setTick(Math.floor((Date.now() - recibidoRef.current) / 1000)), 1000);
    return () => {
      clearInterval(datos);
      clearInterval(cronometro);
    };
  }, [cargar]);

  const accion = async (clave: string, fn: () => Promise<unknown>) => {
    setTrabajando(clave);
    try {
      await fn();
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar la acción");
    } finally {
      setTrabajando("");
    }
  };

  const monitorear = (a: AgenteEnVivo, modo: ModoMonitoreo) =>
    accion(`mon-${a.user_id}`, async () => {
      const m = await api.post<MiMonitoreo>(`/api/supervision/agentes/${a.user_id}/monitorear`, { modo });
      // Antes de que llegue la llamada: el softphone la contesta sola.
      esperarMonitoreo(m.token);
    });

  const sacar = (a: AgenteEnVivo) => {
    const enLlamada = a.estado === "EN_LLAMADA" || a.estado === "TIMBRANDO";
    const texto = enLlamada
      ? `${a.nombre} está en una llamada. ¿Cortarla y sacarlo de la sesión?`
      : `¿Sacar a ${a.nombre} de la sesión de agente?`;
    if (!confirm(texto)) return;
    accion(`sacar-${a.user_id}`, () => api.post(`/api/supervision/agentes/${a.user_id}/sacar`, { cortar_llamada: enLlamada }));
  };

  const visibles = useMemo(
    () =>
      (agentes ?? []).filter(
        (a) =>
          (!filtroCampana || a.campanas.some((c) => String(c.id) === filtroCampana)) && (!filtroEstado || a.estado === filtroEstado)
      ),
    [agentes, filtroCampana, filtroEstado]
  );
  const monitoreado = monitor ? agentes?.find((a) => a.user_id === monitor.agente_id) : undefined;

  return (
    <div>
      <PageHeader
        title="Supervisión"
        subtitle="Agentes y campañas en vivo. Se actualiza cada 2 segundos."
        actions={
          <div className="flex gap-2">
            {interviene && (
              <Button variant="secondary" onClick={() => setTokens(true)}>
                Pantallas
              </Button>
            )}
            <Link href="/wallboard" target="_blank">
              <Button>Abrir wallboard</Button>
            </Link>
          </div>
        }
      />
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {monitor && (
        <Card className="mb-4">
          <div className="flex flex-wrap items-center gap-3 p-4">
            <Badge color="red" dot pulse>
              {monitor.contestado ? "En la sala" : "Llamándote…"}
            </Badge>
            <span className="text-sm text-fg">
              Monitoreando a <strong>{monitoreado?.nombre ?? `#${monitor.agente_id}`}</strong>
            </span>
            <Segmented
              value={monitor.modo}
              onChange={(v) => accion("modo", () => api.post("/api/supervision/monitoreo/modo", { modo: v }))}
              options={MODOS}
            />
            <Button
              variant="danger"
              size="sm"
              loading={trabajando === "colgar"}
              onClick={() =>
                accion("colgar", async () => {
                  await api.post("/api/supervision/monitoreo/colgar", {});
                  esperarMonitoreo(null);
                })
              }
            >
              Dejar de monitorear
            </Button>
          </div>
          {!monitor.contestado && connState !== "registered" && (
            <div className="px-4 pb-4">
              <Note tone="warn">
                Tu softphone del panel no está conectado: la llamada de monitoreo te timbra donde tengas registrada tu extensión.
              </Note>
            </div>
          )}
        </Card>
      )}

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        {!campanas ? (
          <Card>
            <TableSkeleton cols={3} rows={2} />
          </Card>
        ) : campanas.length === 0 ? (
          <Card className="lg:col-span-2">
            <EmptyState title="Ninguna campaña con agentes en curso" hint="Aparecen al iniciar una campaña con agentes o cuando alguien entra a trabajar en ella." />
          </Card>
        ) : (
          campanas.map((c) => (
            <TarjetaCampana
              key={c.id}
              c={c}
              interviene={interviene}
              trabajando={trabajando}
              onNivel={() => setNivelPara(c)}
              onEstado={(pausar) =>
                accion(`camp-${c.id}`, () => api.post(`/api/supervision/campanas/${c.id}/${pausar ? "pausar" : "reanudar"}`, {}))
              }
            />
          ))
        )}
      </div>

      <Card>
        <CardHeader
          title="Agentes"
          subtitle={agentes ? `${agentes.length} conectado(s)` : undefined}
          actions={
            <div className="flex gap-2">
              <Select
                label="Campaña"
                value={filtroCampana}
                onChange={setFiltroCampana}
                placeholder="Todas las campañas"
                options={(campanas ?? []).map((c) => ({ value: String(c.id), label: c.nombre }))}
              />
              <Select
                label="Estado"
                value={filtroEstado}
                onChange={setFiltroEstado}
                placeholder="Todos los estados"
                options={Object.entries(ESTADOS).map(([value, e]) => ({ value, label: e.label }))}
              />
            </div>
          }
        />
        {!agentes ? (
          <TableSkeleton cols={5} />
        ) : visibles.length === 0 ? (
          <EmptyState title="Sin agentes conectados" hint="Los agentes aparecen al entrar desde la consola de agente." />
        ) : (
          <Table head={["Agente", "Estado", "Llamada", "Campañas", ""]}>
            {visibles.map((a) => {
              const e = ESTADOS[a.estado];
              const enEstado = a.en_estado_s == null ? null : a.en_estado_s + tick;
              return (
                <Tr key={a.user_id}>
                  <Td strong>
                    {a.nombre}
                    <div className="text-xs font-normal text-faint">
                      Ext. {a.extension ?? "—"}
                      {!a.audio && <span className="ml-2 text-danger-text">· sin audio</span>}
                    </div>
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Badge color={a.pausa_excedida ? "red" : e?.color ?? "slate"} dot pulse={a.estado === "EN_LLAMADA"}>
                        {e?.label ?? a.estado}
                        {a.pausa ? `: ${a.pausa.nombre}` : ""}
                      </Badge>
                      <span className={`font-mono text-xs tabular-nums ${a.pausa_excedida ? "text-danger-text" : "text-muted"}`}>
                        {reloj(enEstado)}
                      </span>
                    </div>
                    {a.pausa_excedida && a.pausa?.max_minutos && (
                      <div className="mt-1 text-xs text-danger-text">Pasó el máximo de {a.pausa.max_minutos} min</div>
                    )}
                    {a.pausa_pendiente && <div className="mt-1 text-xs text-muted">Pausa al terminar la llamada</div>}
                    {a.monitoreo && (
                      <div className="mt-1 text-xs text-muted">
                        Monitoreado ({MODOS.find((m) => m.value === a.monitoreo?.modo)?.label.toLowerCase()})
                      </div>
                    )}
                  </Td>
                  <Td muted>
                    {a.telefono ? (
                      <>
                        <span className="font-mono">{a.telefono}</span>
                        {a.campana && <div className="text-xs">{a.campana}</div>}
                        {a.hablado_s != null && <div className="text-xs">Hablando {reloj(a.hablado_s + tick)}</div>}
                      </>
                    ) : (
                      "—"
                    )}
                  </Td>
                  <Td muted>{a.campanas.map((c) => c.nombre).join(", ")}</Td>
                  <Td>
                    {interviene && (
                      <RowActions>
                        {MODOS.map((m) => (
                          <Button
                            key={m.value}
                            size="sm"
                            variant={monitor?.agente_id === a.user_id && monitor.modo === m.value ? "primary" : "ghost"}
                            disabled={!a.audio || (!!a.monitoreo && monitor?.agente_id !== a.user_id)}
                            title={a.audio ? m.title : "El agente no tiene el audio conectado"}
                            loading={trabajando === `mon-${a.user_id}`}
                            onClick={() => monitorear(a, m.value)}
                          >
                            {m.label}
                          </Button>
                        ))}
                        {a.estado !== "PAUSA" && !a.pausa_pendiente && (
                          <Button size="sm" variant="ghost" onClick={() => setPausaPara(a)}>
                            Pausar
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" loading={trabajando === `sacar-${a.user_id}`} onClick={() => sacar(a)}>
                          Sacar
                        </Button>
                      </RowActions>
                    )}
                  </Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </Card>

      <ModalPausa
        agente={pausaPara}
        onClose={() => setPausaPara(null)}
        onPausar={(codigo) =>
          pausaPara &&
          accion(`pausa-${pausaPara.user_id}`, async () => {
            await api.post(`/api/supervision/agentes/${pausaPara.user_id}/pausa`, { codigo_pausa_id: codigo });
            setPausaPara(null);
          })
        }
      />
      <ModalNivel
        campana={nivelPara}
        onClose={() => setNivelPara(null)}
        onGuardar={(cuerpo) =>
          nivelPara &&
          accion(`nivel-${nivelPara.id}`, async () => {
            await api.put(`/api/supervision/campanas/${nivelPara.id}/nivel`, cuerpo);
            setNivelPara(null);
          })
        }
      />
      {tokens && <ModalPantallas onClose={() => setTokens(false)} />}
    </div>
  );
}

function Cifra({ label, value, tone = "text-fg" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3">
      <div className={`text-xl font-bold tabular-nums ${tone}`}>{value}</div>
      <div className="mt-0.5 text-xs text-muted">{label}</div>
    </div>
  );
}

function TarjetaCampana({
  c,
  interviene,
  trabajando,
  onNivel,
  onEstado,
}: {
  c: CampanaEnVivo;
  interviene: boolean;
  trabajando: string;
  onNivel: () => void;
  onEstado: (pausar: boolean) => void;
}) {
  const automatica = c.metodo !== "manual" && c.metodo !== "vista_previa";
  const sobremarca = c.metodo === "proporcional" || c.metodo === "predictivo";
  const pasado = c.hoy.abandono_pct != null && c.hoy.abandono_pct > c.abandono_objetivo;
  return (
    <Card>
      <CardHeader
        title={c.nombre}
        subtitle={`${METODOS[c.metodo] ?? c.metodo}${c.metodo === "predictivo" && c.nivel_actual != null ? ` · marcando ${c.nivel_actual} por agente libre` : ""}${c.metodo === "proporcional" ? ` · nivel ${c.nivel_marcacion}` : ""}`}
        actions={
          <div className="flex items-center gap-2">
            <Badge color={c.status === "running" ? "green" : "slate"} dot pulse={c.status === "running"}>
              {c.status === "running" ? "En curso" : c.status === "paused" ? "Pausada" : "Detenida"}
            </Badge>
            {interviene && sobremarca && (
              <Button size="sm" variant="ghost" onClick={onNivel}>
                Nivel
              </Button>
            )}
            {interviene && automatica && (
              <Button size="sm" variant="secondary" loading={trabajando === `camp-${c.id}`} onClick={() => onEstado(c.status === "running")}>
                {c.status === "running" ? "Pausar" : "Reanudar"}
              </Button>
            )}
          </div>
        }
      />
      <div className="space-y-3 p-4 pt-0">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Cifra label="Conectados" value={c.agentes.conectados} />
          <Cifra label="Listos" value={c.agentes.listo} tone="text-ok-text" />
          <Cifra label="En llamada" value={c.agentes.en_llamada + c.agentes.timbrando} tone="text-info-text" />
          <Cifra label="En pausa" value={c.agentes.pausa} tone="text-warn-text" />
        </div>
        {sobremarca && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Cifra label="Timbrando" value={c.llamadas?.timbrando ?? 0} />
            <Cifra label="Esperando agente" value={c.llamadas?.en_espera ?? 0} tone={(c.llamadas?.en_espera ?? 0) > 0 ? "text-warn-text" : "text-fg"} />
            <Cifra label="Contestadas hoy" value={c.hoy.contestadas} tone="text-ok-text" />
            <Cifra label={`Abandono hoy (obj. ${c.abandono_objetivo} %)`} value={pct(c.hoy.abandono_pct)} tone={pasado ? "text-danger-text" : "text-ok-text"} />
          </div>
        )}
        <p className="text-xs text-muted">
          {c.hopper} lead(s) listos para marcar
          {c.ultimos_15 &&
            ` · Últimos 15 min: contacto ${pct(c.ultimos_15.contacto_pct)}, abandono ${pct(c.ultimos_15.abandono_pct)}, ring ${c.ultimos_15.ring_s ?? "—"} s, conversación ${reloj(c.ultimos_15.aht_s)}`}
        </p>
        {pasado && <Note tone="warn">El abandono de hoy pasó el objetivo. El predictivo ya se está frenando; si persiste, baja el tope o pausa la campaña.</Note>}
      </div>
    </Card>
  );
}

function ModalPausa({
  agente,
  onClose,
  onPausar,
}: {
  agente: AgenteEnVivo | null;
  onClose: () => void;
  onPausar: (codigo: number | null) => void;
}) {
  const [codigos, setCodigos] = useState<CodigoPausa[]>([]);
  const [codigo, setCodigo] = useState("");
  useEffect(() => {
    if (!agente) return;
    api
      .get<CodigoPausa[]>("/api/contact-center/pausas")
      .then((p) => setCodigos(p.filter((x) => x.activo)))
      .catch(() => setCodigos([]));
  }, [agente]);
  const enLlamada = agente && (agente.estado === "EN_LLAMADA" || agente.estado === "TIMBRANDO" || agente.estado === "DISPO");
  return (
    <Modal
      open={agente !== null}
      onClose={onClose}
      title={`Pausar a ${agente?.nombre ?? ""}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={() => onPausar(codigo ? Number(codigo) : null)}>Pausar</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select
          label="Código de pausa"
          value={codigo}
          onChange={setCodigo}
          placeholder="Sin código"
          options={codigos.map((c) => ({ value: String(c.id), label: c.nombre }))}
        />
        {enLlamada && <Note tone="info">Está en una llamada: no se corta. Pasa a pausa al terminar y disponer.</Note>}
      </div>
    </Modal>
  );
}

function ModalNivel({
  campana,
  onClose,
  onGuardar,
}: {
  campana: CampanaEnVivo | null;
  onClose: () => void;
  onGuardar: (cuerpo: Record<string, number>) => void;
}) {
  const [valores, setValores] = useState({ nivel_marcacion: "", nivel_max: "", abandono_objetivo: "" });
  useEffect(() => {
    if (campana)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setValores({
        nivel_marcacion: String(campana.nivel_marcacion),
        nivel_max: String(campana.nivel_max),
        abandono_objetivo: String(campana.abandono_objetivo),
      });
  }, [campana]);
  const predictivo = campana?.metodo === "predictivo";
  return (
    <Modal
      open={campana !== null}
      onClose={onClose}
      title={`Nivel de ${campana?.nombre ?? ""}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            onClick={() =>
              onGuardar(
                predictivo
                  ? { nivel_max: Number(valores.nivel_max), abandono_objetivo: Number(valores.abandono_objetivo) }
                  : { nivel_marcacion: Number(valores.nivel_marcacion) }
              )
            }
          >
            Aplicar ya
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {predictivo ? (
          <>
            <Input
              label="Abandono objetivo (%)"
              type="number"
              value={valores.abandono_objetivo}
              onChange={(v) => setValores({ ...valores, abandono_objetivo: v })}
              hint="De 0,5 a 10. Más bajo: marca con más prudencia."
            />
            <Input
              label="Tope de llamadas por agente"
              type="number"
              value={valores.nivel_max}
              onChange={(v) => setValores({ ...valores, nivel_max: v })}
              hint="De 1 a 5."
            />
          </>
        ) : (
          <Input
            label="Llamadas por agente libre"
            type="number"
            value={valores.nivel_marcacion}
            onChange={(v) => setValores({ ...valores, nivel_marcacion: v })}
            hint="De 1 a 5 (1 = progresivo). Se aplica en la próxima vuelta del marcador."
          />
        )}
      </div>
    </Modal>
  );
}

function ModalPantallas({ onClose }: { onClose: () => void }) {
  const [lista, setLista] = useState<TokenWallboard[] | null>(null);
  const [nombre, setNombre] = useState("");
  const [dias, setDias] = useState("30");
  const [nuevo, setNuevo] = useState<string | null>(null);
  const [error, setError] = useState("");

  const cargar = useCallback(async () => {
    try {
      setLista(await api.get<TokenWallboard[]>("/api/supervision/wallboard/tokens"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las pantallas");
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const crear = async () => {
    try {
      const t = await api.post<TokenWallboard>("/api/supervision/wallboard/tokens", { nombre: nombre.trim(), dias: Number(dias) || 30 });
      // El token va en el fragmento (#): el navegador no lo manda al servidor ni queda en logs.
      setNuevo(`${window.location.origin}/wallboard#${t.token}`);
      setNombre("");
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear");
    }
  };

  const revocar = async (t: TokenWallboard) => {
    if (!confirm(`¿Revocar el acceso de «${t.nombre}»? Esa pantalla deja de mostrar datos.`)) return;
    try {
      await api.del(`/api/supervision/wallboard/tokens/${t.id}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo revocar");
    }
  };

  return (
    <Modal open onClose={onClose} title="Pantallas del wallboard" footer={<Button onClick={onClose}>Cerrar</Button>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">
          Para una TV de la sala sin sesión de usuario: un enlace de solo lectura que vence. Muestra cifras y nombres de agentes, no teléfonos.
        </p>
        {error && <ErrorBanner message={error} onClose={() => setError("")} />}
        {nuevo && (
          <Note tone="brand">
            <div className="space-y-2">
              <div>Ábrelo en la pantalla. Cópialo ahora: no se vuelve a mostrar.</div>
              <code className="block break-all rounded bg-surface-2 p-2 text-xs">{nuevo}</code>
              <Button size="sm" variant="secondary" onClick={() => navigator.clipboard?.writeText(nuevo)}>
                Copiar enlace
              </Button>
            </div>
          </Note>
        )}
        <div className="grid grid-cols-[1fr_7rem_auto] items-end gap-2">
          <Input label="Nombre" value={nombre} onChange={setNombre} placeholder="TV sala de cobranza" />
          <Input label="Días" type="number" value={dias} onChange={setDias} />
          <Button disabled={!nombre.trim()} onClick={crear}>
            Crear
          </Button>
        </div>
        {lista && lista.length > 0 && (
          <Table head={["Pantalla", "Vence", "Último uso", ""]}>
            {lista.map((t) => (
              <Tr key={t.id}>
                <Td strong>
                  {t.nombre}
                  {!t.vigente && (
                    <span className="ml-2">
                      <Badge color="slate">{t.revocado_at ? "Revocada" : "Vencida"}</Badge>
                    </span>
                  )}
                </Td>
                <Td muted>{new Date(t.vence + "Z").toLocaleDateString()}</Td>
                <Td muted>{t.ultimo_uso_at ? new Date(t.ultimo_uso_at + "Z").toLocaleString() : "—"}</Td>
                <Td>
                  {t.vigente && (
                    <Button size="sm" variant="ghost" onClick={() => revocar(t)}>
                      Revocar
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </div>
    </Modal>
  );
}
