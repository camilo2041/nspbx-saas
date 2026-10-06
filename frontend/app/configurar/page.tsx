"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { EditorHorario } from "@/components/editor-horario";
import { Button, Card, Check, ErrorBanner, Input, Note, PageHeader, Select, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Extension, Trunk } from "@/lib/types";

/**
 * Asistente de configuración: deja la central armada en pocos pasos, como
 * las plantillas de inicio de Aircall o Talkdesk. Elige el tipo de empresa,
 * conecta el proveedor, crea al equipo y dice a dónde van las llamadas;
 * al final crea todo con las mismas API (y validaciones) que cada pantalla.
 */

type Tipo = "recepcion" | "ventas" | "cobranza";

const TIPOS: { value: Tipo; titulo: string; detalle: string; grupo: string; campana: boolean }[] = [
  {
    value: "recepcion",
    titulo: "Recepción / atención al cliente",
    detalle: "Te llaman y tu equipo contesta. Las llamadas suenan en todos a la vez.",
    grupo: "atencion",
    campana: false,
  },
  {
    value: "ventas",
    titulo: "Call center de ventas",
    detalle: "Recibes llamadas y además tus agentes llaman a listas de clientes (predictivo).",
    grupo: "ventas",
    campana: true,
  },
  {
    value: "cobranza",
    titulo: "Cobranza",
    detalle: "Tus agentes llaman a cartera respetando el horario legal de cobro.",
    grupo: "cobranza",
    campana: true,
  },
];

const HORARIO_OFICINA = JSON.stringify(
  Object.fromEntries(["mon", "tue", "wed", "thu", "fri"].map((d) => [d, ["08:00", "18:00"]]))
);

interface Persona {
  nombre: string;
}

interface Paso {
  texto: string;
  estado: "pendiente" | "ok" | "error";
  detalle?: string;
}

interface Credencial {
  nombre: string;
  usuario: string;
  clave: string;
  extension: string | null;
}

function clave(): string {
  const letras = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint32Array(14);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => letras[b % letras.length]).join("");
}

function usuarioDe(nombre: string, usados: Set<string>): string {
  const base =
    nombre
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9 ]/g, "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .join(".") || "persona";
  let u = base.length >= 3 ? base : `${base}.nspbx`;
  for (let i = 2; usados.has(u); i++) u = `${base}${i}`;
  usados.add(u);
  return u;
}

export default function ConfigurarPage() {
  const { tieneModulo } = useAuth();
  const [paso, setPaso] = useState(1);
  const [tipo, setTipo] = useState<Tipo>("recepcion");
  const [troncales, setTroncales] = useState<Trunk[] | null>(null);
  const [extensiones, setExtensiones] = useState<Extension[]>([]);
  const [proveedor, setProveedor] = useState({ nombre: "", servidor: "", usuario: "", clave: "" });
  const [personas, setPersonas] = useState<Persona[]>([{ nombre: "" }, { nombre: "" }]);
  const [conHorario, setConHorario] = useState(true);
  const [horario, setHorario] = useState<string | null>(HORARIO_OFICINA);
  const [numero, setNumero] = useState("");
  const [reglasColombia, setReglasColombia] = useState(false);
  const [progreso, setProgreso] = useState<Paso[] | null>(null);
  const [credenciales, setCredenciales] = useState<Credencial[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.get<Trunk[]>("/api/trunks"), api.get<Extension[]>("/api/extensions")])
      .then(([ts, es]) => {
        setTroncales(ts);
        setExtensiones(es);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo cargar"));
  }, []);

  const elegido = TIPOS.find((t) => t.value === tipo)!;
  const yaHayProveedor = (troncales ?? []).some((t) => t.enabled);
  const nombres = personas.map((p) => p.nombre.trim()).filter(Boolean);

  const crearTodo = async () => {
    const pasos: Paso[] = [];
    const marcar = (texto: string, estado: Paso["estado"], detalle?: string) => {
      const i = pasos.findIndex((p) => p.texto === texto);
      if (i >= 0) pasos[i] = { texto, estado, detalle };
      else pasos.push({ texto, estado, detalle });
      setProgreso([...pasos]);
    };
    const intentar = async (texto: string, accion: () => Promise<string | void>) => {
      marcar(texto, "pendiente");
      try {
        const detalle = await accion();
        marcar(texto, "ok", detalle || undefined);
        return true;
      } catch (e) {
        marcar(texto, "error", e instanceof Error ? e.message : "No se pudo");
        return false;
      }
    };

    // 1. Proveedor
    if (!yaHayProveedor && proveedor.servidor.trim()) {
      await intentar("Conectar el proveedor de telefonía", async () => {
        const nombre =
          proveedor.nombre
            .trim()
            .toLowerCase()
            .normalize("NFD")
            .replace(/[̀-ͯ]/g, "")
            .replace(/[^a-z0-9.-]+/g, "-")
            .replace(/^-+|-+$/g, "") || "proveedor";
        await api.post("/api/trunks", {
          name: nombre,
          gateway_host: proveedor.servidor.trim(),
          gateway_port: 5060,
          username: proveedor.usuario.trim(),
          password: proveedor.clave,
          from_domain: "",
          register_enabled: !!proveedor.usuario.trim(),
          caller_id_number: null,
          transport: "udp",
          ping: null,
          codec_prefs: null,
          enabled: true,
        });
        return `«${nombre}» creado. Revisa en Proveedor de telefonía que diga «Conectado».`;
      });
    }

    // 2. Equipo
    const usados = new Set<string>();
    const nuevasExt: string[] = [];
    const creds: Credencial[] = [];
    for (const nombre of nombres) {
      const usuario = usuarioDe(nombre, usados);
      const pass = clave();
      await intentar(`Agregar a ${nombre}`, async () => {
        const u = await api.post<{ extension_number: string | null }>("/api/users", {
          username: usuario,
          full_name: nombre,
          email: null,
          role: "asesor",
          extension_id: null,
          enabled: true,
          password: pass,
          crear_extension: true,
        });
        if (u.extension_number) nuevasExt.push(u.extension_number);
        creds.push({ nombre, usuario, clave: pass, extension: u.extension_number });
        return `Usuario ${usuario}${u.extension_number ? `, extensión ${u.extension_number}` : ""}.`;
      });
    }
    setCredenciales(creds);

    // 3. Grupo de atención con todo el equipo
    const agentes = [...new Set([...extensiones.map((e) => e.number), ...nuevasExt])];
    let numeroGrupo = "";
    if (agentes.length) {
      await intentar(`Crear el grupo de atención «${elegido.grupo}»`, async () => {
        let ultimo: unknown = null;
        for (let n = 8000; n < 8020; n++) {
          try {
            await api.post("/api/queues", { name: elegido.grupo, extension: String(n), strategy: "ring-all", agents: agentes });
            numeroGrupo = String(n);
            return `Número interno ${n}, con ${agentes.length} persona(s).`;
          } catch (e) {
            ultimo = e;
            // Número ocupado: se prueba el siguiente. Otro error: se corta.
            if (!(e instanceof Error) || !/ya lo usa|ya existe|409/.test(e.message)) throw e;
          }
        }
        throw ultimo instanceof Error ? ultimo : new Error("No se encontró un número libre para el grupo");
      });
    }

    // 4. Llamadas entrantes al grupo
    if (numeroGrupo) {
      await intentar("Enviar las llamadas entrantes al grupo", async () => {
        await api.post("/api/inbound-routes", {
          name: "principal",
          did_pattern: numero.trim() || "any",
          destination_type: "queue",
          destination_value: numeroGrupo,
          priority: numero.trim() ? 10 : 100,
          enabled: true,
          horario: conHorario ? horario : null,
          fuera_horario_tipo: conHorario ? "hangup" : null,
          fuera_horario_valor: null,
        });
        return numero.trim() ? `Las llamadas al ${numero.trim()} suenan en el grupo.` : "Toda llamada que entre suena en el grupo.";
      });
    }

    // 5. Reglas de salida
    if (reglasColombia) {
      const plantillas = [
        ["Celulares Colombia", "3XXXXXXXXX"],
        ["Fijos Colombia", "60XXXXXXXX"],
        ["Líneas 01 8000", "018000XXXXXX"],
      ];
      await intentar("Crear reglas de salida para Colombia", async () => {
        for (const [i, [name, pattern]] of plantillas.entries()) {
          await api.post("/api/outbound-routes", {
            name, pattern, strip_digits: 0, prepend: null, trunk_ids: "", allow_international: false, priority: 10 + i, enabled: true,
          });
        }
      });
    }
    setPaso(5);
  };

  const pasosTitulos = ["Tu empresa", "Proveedor", "Tu equipo", "Llamadas que entran", "Listo"];

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Configuración guiada"
        subtitle="Deja tu central funcionando en unos minutos. Puedes cambiar todo después en cada pantalla."
      />
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <ol className="mb-4 flex flex-wrap gap-2 text-xs">
        {pasosTitulos.map((t, i) => (
          <li
            key={t}
            className={`rounded-full px-3 py-1 ${
              paso === i + 1 ? "bg-brand text-white" : paso > i + 1 ? "bg-ok-soft text-ok-text" : "bg-surface-2 text-muted"
            }`}
          >
            {paso > i + 1 ? "✓ " : `${i + 1}. `}
            {t}
          </li>
        ))}
      </ol>

      <Card className="p-5">
        {paso === 1 && (
          <div className="space-y-3">
            <h2 className="text-base font-semibold text-fg">¿Cómo vas a usar la central?</h2>
            {TIPOS.filter((t) => !t.campana || tieneModulo("voicebot")).map((t) => (
              <label
                key={t.value}
                className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${
                  tipo === t.value ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"
                }`}
              >
                <input type="radio" name="tipo" className="mt-1" checked={tipo === t.value} onChange={() => setTipo(t.value)} />
                <span>
                  <span className="block text-sm font-semibold text-fg">{t.titulo}</span>
                  <span className="block text-xs text-muted">{t.detalle}</span>
                </span>
              </label>
            ))}
            <div className="flex justify-end">
              <Button onClick={() => setPaso(2)}>Siguiente</Button>
            </div>
          </div>
        )}

        {paso === 2 && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-fg">Tu proveedor de telefonía</h2>
            {troncales === null ? (
              <p className="text-sm text-muted">Cargando…</p>
            ) : yaHayProveedor ? (
              <Note tone="brand">
                Ya tienes un proveedor conectado ({troncales.filter((t) => t.enabled).map((t) => t.name).join(", ")}). Seguimos con él.
              </Note>
            ) : (
              <>
                <p className="text-sm text-fg-soft">
                  Es la línea por la que entran y salen tus llamadas. Pídele a tu proveedor (Claro, Tigo, ETB, Movistar…) el
                  servidor, el usuario y la clave de tu línea SIP. Si todavía no los tienes, puedes saltar este paso.
                </p>
                <Input label="Nombre" value={proveedor.nombre} onChange={(v) => setProveedor({ ...proveedor, nombre: v })} placeholder="claro" />
                <Input
                  label="Servidor del proveedor"
                  value={proveedor.servidor}
                  onChange={(v) => setProveedor({ ...proveedor, servidor: v })}
                  placeholder="sip.proveedor.com"
                  mono
                />
                <div className="grid grid-cols-2 gap-2">
                  <Input label="Usuario" value={proveedor.usuario} onChange={(v) => setProveedor({ ...proveedor, usuario: v })} mono />
                  <Input label="Clave" value={proveedor.clave} onChange={(v) => setProveedor({ ...proveedor, clave: v })} />
                </div>
              </>
            )}
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setPaso(1)}>
                Atrás
              </Button>
              <Button onClick={() => setPaso(3)}>{yaHayProveedor || proveedor.servidor.trim() ? "Siguiente" : "Saltar por ahora"}</Button>
            </div>
          </div>
        )}

        {paso === 3 && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-fg">¿Quiénes atienden?</h2>
            <p className="text-sm text-fg-soft">
              Escribe el nombre de cada persona. A cada una se le crea su usuario, su contraseña y su extensión para llamar.
              {extensiones.length > 0 && ` Las ${extensiones.length} extensión(es) que ya tienes también entran al grupo.`}
            </p>
            {personas.map((p, i) => (
              <div key={i} className="flex items-end gap-2">
                <div className="flex-1">
                  <Input
                    label={`Persona ${i + 1}`}
                    value={p.nombre}
                    onChange={(v) => setPersonas(personas.map((x, j) => (j === i ? { nombre: v } : x)))}
                    placeholder="Nombre y apellido"
                  />
                </div>
                {personas.length > 1 && (
                  <Button variant="ghost" onClick={() => setPersonas(personas.filter((_, j) => j !== i))}>
                    Quitar
                  </Button>
                )}
              </div>
            ))}
            <Button variant="secondary" size="sm" onClick={() => setPersonas([...personas, { nombre: "" }])}>
              + Otra persona
            </Button>
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setPaso(2)}>
                Atrás
              </Button>
              <Button onClick={() => setPaso(4)} disabled={nombres.length === 0 && extensiones.length === 0}>
                Siguiente
              </Button>
            </div>
          </div>
        )}

        {paso === 4 && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-fg">Las llamadas que entran</h2>
            <p className="text-sm text-fg-soft">
              Creamos el grupo «{elegido.grupo}» con tu equipo: cuando te llamen, suena en todos a la vez y contesta quien
              esté libre.
            </p>
            <Input
              label="Tu número (opcional)"
              value={numero}
              onChange={setNumero}
              placeholder="Vacío = cualquier número que entre"
              hint="Solo si tienes varios números y quieres que este vaya al grupo."
              mono
            />
            <div className="rounded-xl border border-line p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-fg-soft">Solo en horario de atención (fuera de él, se cuelga)</span>
                <Toggle checked={conHorario} onChange={setConHorario} />
              </div>
              {conHorario && (
                <div className="mt-3">
                  <EditorHorario value={horario} onChange={setHorario} />
                </div>
              )}
            </div>
            <Check
              checked={reglasColombia}
              onChange={setReglasColombia}
              label="Limitar las llamadas salientes a Colombia (celulares, fijos y 01 8000)"
            />
            <Note tone="muted">
              Se va a crear: {!yaHayProveedor && proveedor.servidor.trim() ? "el proveedor, " : ""}
              {nombres.length ? `${nombres.length} persona(s) con su extensión, ` : ""}el grupo «{elegido.grupo}» y la regla
              para las llamadas que entran{reglasColombia ? ", más las reglas de salida de Colombia" : ""}.
            </Note>
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setPaso(3)}>
                Atrás
              </Button>
              <Button onClick={crearTodo} loading={!!progreso && paso === 4}>
                Crear todo
              </Button>
            </div>
            {progreso && <Progreso pasos={progreso} />}
          </div>
        )}

        {paso === 5 && progreso && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-fg">
              {progreso.every((p) => p.estado === "ok") ? "¡Tu central quedó configurada!" : "Casi listo: revisa lo que falló"}
            </h2>
            <Progreso pasos={progreso} />
            {credenciales.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-medium text-fg">Datos para entregar a cada persona (cópialos ahora):</p>
                <div className="overflow-x-auto rounded-xl border border-line">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-2 text-left text-xs text-muted">
                      <tr>
                        <th className="px-3 py-2">Persona</th>
                        <th className="px-3 py-2">Usuario</th>
                        <th className="px-3 py-2">Contraseña</th>
                        <th className="px-3 py-2">Extensión</th>
                      </tr>
                    </thead>
                    <tbody>
                      {credenciales.map((c) => (
                        <tr key={c.usuario} className="border-t border-line">
                          <td className="px-3 py-2">{c.nombre}</td>
                          <td className="px-3 py-2 font-mono">{c.usuario}</td>
                          <td className="px-3 py-2 font-mono">{c.clave}</td>
                          <td className="px-3 py-2 font-mono">{c.extension ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-1 text-xs text-muted">Cada persona entra al panel o a la app con su usuario y contraseña; puede cambiarla luego.</p>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Link href="/" className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white">
                Ver la puesta en marcha
              </Link>
              <Link href="/softphone" className="rounded-xl border border-line px-4 py-2 text-sm font-medium text-fg-soft">
                Hacer una llamada de prueba
              </Link>
              {elegido.campana && (
                <Link href="/campaigns" className="rounded-xl border border-line px-4 py-2 text-sm font-medium text-fg-soft">
                  Crear la primera campaña
                </Link>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function Progreso({ pasos }: { pasos: Paso[] }) {
  return (
    <ul className="space-y-2" aria-live="polite">
      {pasos.map((p) => (
        <li key={p.texto} className="flex items-start gap-2 text-sm">
          <span
            aria-hidden
            className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${
              p.estado === "ok" ? "bg-ok" : p.estado === "error" ? "bg-danger" : "bg-muted"
            }`}
          >
            {p.estado === "ok" ? "✓" : p.estado === "error" ? "!" : "…"}
          </span>
          <span>
            <span className="font-medium text-fg">{p.texto}</span>
            {p.detalle && <span className={`block text-xs ${p.estado === "error" ? "text-danger-text" : "text-fg-soft"}`}>{p.detalle}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
