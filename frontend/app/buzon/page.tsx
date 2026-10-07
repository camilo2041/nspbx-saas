"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Input,
  PageHeader,
  Select,
  Table,
  TableSkeleton,
  Td,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSoftphone } from "@/lib/softphone-context";
import { MensajeBuzon, PERMISOS } from "@/lib/types";
import { tiempoCorto } from "@/lib/utils";

const avisarMenu = () => window.dispatchEvent(new Event("nspbx:buzon"));

function fecha(iso: string | null) {
  if (!iso) return "—";
  // El backend guarda UTC sin zona: se marca como UTC para mostrar la hora local.
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return d.toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}

/** Reproductor: trae el audio con la sesión (un <audio src> no manda el
 * token) y al reproducirlo lo marca como escuchado. */
function Reproductor({ mensaje, onEscuchado }: { mensaje: MensajeBuzon; onEscuchado: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const urlRef = useRef<string | null>(null);

  useEffect(() => () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  const cargar = async () => {
    setCargando(true);
    setError("");
    try {
      const blob = await api.getBlob(`/api/buzon/${mensaje.id}/audio`);
      urlRef.current = URL.createObjectURL(blob);
      setUrl(urlRef.current);
      if (!mensaje.escuchado) onEscuchado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el audio");
    } finally {
      setCargando(false);
    }
  };

  if (error) return <span className="text-xs text-danger-text">{error}</span>;
  if (url) return <audio controls autoPlay src={url} className="h-8 w-52" />;
  return (
    <Button size="sm" variant="secondary" onClick={cargar} loading={cargando}>
      ▶ Escuchar
    </Button>
  );
}

export default function BuzonPage() {
  const router = useRouter();
  const { puede } = useAuth();
  const { setDestination } = useSoftphone();
  const [mensajes, setMensajes] = useState<MensajeBuzon[] | null>(null);
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState<"todos" | "sin_escuchar">("todos");
  const [extension, setExtension] = useState("");
  const veTodas = puede(PERMISOS.llamadasTodas);

  const cargar = useCallback(async () => {
    try {
      const q = new URLSearchParams();
      if (filtro === "sin_escuchar") q.set("sin_escuchar", "true");
      if (extension) q.set("extension", extension);
      setMensajes(await api.get<MensajeBuzon[]>(`/api/buzon?${q}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los mensajes");
      setMensajes([]);
    }
  }, [filtro, extension]);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 30000);
    return () => clearInterval(t);
  }, [cargar]);

  const marcar = async (m: MensajeBuzon, escuchado: boolean) => {
    try {
      const nuevo = await api.put<MensajeBuzon>(`/api/buzon/${m.id}`, { escuchado });
      setMensajes((lista) => lista?.map((x) => (x.id === m.id ? nuevo : x)) ?? null);
      avisarMenu();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar");
    }
  };

  const borrar = async (m: MensajeBuzon) => {
    if (!confirm(`¿Borrar el mensaje de ${m.caller_name || m.caller_number || "número oculto"}? No se puede deshacer.`)) return;
    try {
      await api.del(`/api/buzon/${m.id}`);
      setMensajes((lista) => lista?.filter((x) => x.id !== m.id) ?? null);
      avisarMenu();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar");
    }
  };

  const devolver = (numero: string) => {
    setDestination(numero);
    router.push("/softphone");
  };

  const extensiones = Array.from(new Set((mensajes ?? []).map((m) => m.extension))).sort();
  const sinEscuchar = (mensajes ?? []).filter((m) => !m.escuchado).length;

  return (
    <div>
      <PageHeader
        title="Buzón de voz"
        subtitle="Los mensajes que dejaron quienes llamaron cuando nadie contestó. Si tu usuario tiene correo, cada mensaje te llega también por correo."
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <MiSaludo />
      <PinRemoto />

      <Card>
        <CardHeader
          title={sinEscuchar ? `${sinEscuchar} mensaje(s) sin escuchar` : "Mensajes"}
          subtitle="Se actualiza solo cada 30 s."
          actions={
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-44">
                <Select
                  label=""
                  value={filtro}
                  onChange={(v) => setFiltro(v as "todos" | "sin_escuchar")}
                  options={[
                    { value: "todos", label: "Todos" },
                    { value: "sin_escuchar", label: "Sin escuchar" },
                  ]}
                />
              </div>
              {veTodas && (
                <div className="w-44">
                  <Select
                    label=""
                    value={extension}
                    onChange={setExtension}
                    options={[
                      { value: "", label: "Todas las extensiones" },
                      ...Array.from(new Set([...extensiones, ...(extension ? [extension] : [])])).map((e) => ({
                        value: e,
                        label: `Extensión ${e}`,
                      })),
                    ]}
                  />
                </div>
              )}
            </div>
          }
        />
        {mensajes === null ? (
          <TableSkeleton cols={5} />
        ) : mensajes.length === 0 ? (
          <EmptyState
            title={filtro === "sin_escuchar" ? "No hay mensajes sin escuchar" : "Todavía no hay mensajes"}
            hint="Cuando alguien llame a una extensión con buzón y nadie conteste, el mensaje aparece aquí. Para probarlo, marca *99 y el número de tu extensión desde otro teléfono."
          />
        ) : (
          <Table head={["Fecha", "De", "Para", "Duración", "Mensaje", ""]}>
            {mensajes.map((m, i) => (
              <Tr key={m.id} delay={Math.min(i, 10) * 20}>
                <Td>
                  <span className="flex items-center gap-2">
                    {!m.escuchado && <span className="h-2 w-2 shrink-0 rounded-full bg-brand" aria-label="Sin escuchar" />}
                    <span className={m.escuchado ? "" : "font-semibold text-fg"}>{fecha(m.created_at)}</span>
                  </span>
                </Td>
                <Td strong={!m.escuchado}>
                  {m.caller_name && <span className="block">{m.caller_name}</span>}
                  <span className="font-mono text-xs text-muted">{m.caller_number || "Número oculto"}</span>
                </Td>
                <Td mono>{m.extension}</Td>
                <Td>{tiempoCorto(m.duracion)}</Td>
                <Td>
                  <Reproductor mensaje={m} onEscuchado={() => marcar(m, true)} />
                  {m.transcripcion && <p className="mt-1 max-w-md text-xs italic text-muted">«{m.transcripcion}»</p>}
                </Td>
                <Td align="right">
                  <div className="flex flex-wrap justify-end gap-1.5">
                    {m.caller_number && puede(PERMISOS.softphone) && (
                      <Button size="sm" variant="secondary" onClick={() => devolver(m.caller_number!)}>
                        Devolver llamada
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => marcar(m, !m.escuchado)}>
                      {m.escuchado ? "Marcar sin escuchar" : "Marcar escuchado"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => borrar(m)}>
                      Borrar
                    </Button>
                  </div>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
      <p className="mt-3 text-xs text-muted">
        El audio de los mensajes se borra solo, con la misma retención que las grabaciones de llamadas (Ajustes).
      </p>
    </div>
  );
}

/** El saludo que oye quien llama cuando nadie contesta (el propio o el general). */
function MiSaludo() {
  const [saludo, setSaludo] = useState<{ extension: string; propio: boolean; segundos: number | null } | null>(null);
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const entrada = useRef<HTMLInputElement | null>(null);

  const cargar = useCallback(() => {
    api.get<{ extension: string; propio: boolean; segundos: number | null }>("/api/buzon/saludo").then(setSaludo, () => setSaludo(null));
  }, []);
  useEffect(() => {
    cargar();
  }, [cargar]);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  if (!saludo) return null;

  const subir = async (archivo: File) => {
    setTrabajando(true);
    setError("");
    try {
      const datos = new FormData();
      datos.append("archivo", archivo);
      await api.form("/api/buzon/saludo", datos);
      cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo subir el saludo");
    } finally {
      setTrabajando(false);
    }
  };

  return (
    <Card className="mb-4" guia="buzon:saludo">
      <CardHeader
        title={`Mi saludo · extensión ${saludo.extension}`}
        subtitle={
          saludo.propio
            ? `Quien te llama oye tu saludo (${saludo.segundos ?? "?"} s) antes de dejar el mensaje.`
            : "Quien te llama oye el saludo general: «La persona que llamas no está disponible…»."
        }
      />
      <div className="flex flex-wrap items-center gap-2 px-5 pb-5">
        {saludo.propio && !url && (
          <Button
            size="sm"
            variant="secondary"
            onClick={async () => setUrl(URL.createObjectURL(await api.getBlob("/api/buzon/saludo/audio")))}
          >
            Escucharlo
          </Button>
        )}
        {url && <audio src={url} controls autoPlay className="h-9" />}
        <Button size="sm" variant="secondary" guia="buzon:subir-saludo" loading={trabajando} onClick={() => entrada.current?.click()}>
          {saludo.propio ? "Cambiarlo (WAV)" : "Subir mi saludo (WAV)"}
        </Button>
        {saludo.propio && (
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              await api.del("/api/buzon/saludo");
              setUrl(null);
              cargar();
            }}
          >
            Volver al general
          </Button>
        )}
        <input
          ref={entrada}
          type="file"
          accept="audio/wav,.wav"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) subir(f);
            e.target.value = "";
          }}
        />
        <p className="w-full text-xs text-muted">
          También desde tu teléfono: marca <b>*98</b> para grabar tu saludo y <b>*97</b> para escuchar tus mensajes nuevos.
        </p>
        {error && <p className="w-full text-xs text-danger-text">{error}</p>}
      </div>
    </Card>
  );
}

/** PIN para escuchar el buzón desde otro teléfono (*96 o un número entrante). */
function PinRemoto() {
  const [estado, setEstado] = useState<{ extension: string; tiene_pin: boolean; marcar: string } | null>(null);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState(false);

  const cargar = useCallback(() => {
    api.get<{ extension: string; tiene_pin: boolean; marcar: string }>("/api/buzon/pin").then(setEstado, () => setEstado(null));
  }, []);
  useEffect(() => {
    cargar();
  }, [cargar]);

  if (!estado) return null;

  const guardar = async () => {
    setTrabajando(true);
    setError("");
    try {
      setEstado(await api.put("/api/buzon/pin", { pin }));
      setPin("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar el PIN");
    } finally {
      setTrabajando(false);
    }
  };

  return (
    <Card className="mb-4" guia="buzon:pin">
      <CardHeader
        title="Escuchar desde otro teléfono"
        subtitle={
          estado.tiene_pin
            ? `Marca ${estado.marcar} desde cualquier extensión (o el número que te configuren), luego tu extensión y tu PIN.`
            : `Ponle un PIN a tu buzón para escucharlo marcando ${estado.marcar} desde otro teléfono. Sin PIN, solo desde el tuyo (*97) o aquí.`
        }
      />
      <div className="flex flex-wrap items-end gap-2 px-5 pb-5">
        <div className="w-44">
          <Input
            label={estado.tiene_pin ? "Nuevo PIN" : "PIN (4 a 8 números)"}
            type="password"
            value={pin}
            onChange={(v) => setPin(v.replace(/[^0-9]/g, "").slice(0, 8))}
            placeholder="••••••"
          />
        </div>
        <Button size="sm" onClick={guardar} loading={trabajando} disabled={pin.length < 4}>
          {estado.tiene_pin ? "Cambiar PIN" : "Guardar PIN"}
        </Button>
        {estado.tiene_pin && (
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              await api.del("/api/buzon/pin");
              cargar();
            }}
          >
            Quitar el PIN
          </Button>
        )}
        <p className="w-full text-xs text-muted">Evita PIN fáciles (1111, 1234 o tu extensión): no se aceptan.</p>
        {error && <p className="w-full text-xs text-danger-text">{error}</p>}
      </div>
    </Card>
  );
}
