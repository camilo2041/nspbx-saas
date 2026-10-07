"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { API_URL, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ESTADOS, reloj } from "@/lib/supervision";
import { GruposEnVivo } from "@/components/grupos-en-vivo";
import { PERMISOS, ResumenWallboard } from "@/lib/types";

const CADA_MS = 3000;

/**
 * Wallboard para la sala de operaciones: pantalla completa, números grandes,
 * se actualiza sola. Dos formas de entrar:
 *  - con sesión y permiso supervision:ver;
 *  - en una TV sin usuario, con el enlace de «Pantallas» (/wallboard#<token>).
 *    El token va en el fragmento, que el navegador no manda al servidor, y
 *    viaja en una cabecera: no queda en ningún log de acceso.
 */
export default function WallboardPage() {
  const { usuario, puede, cargando } = useAuth();
  const [token, setToken] = useState<string | null>(null);
  const [datos, setDatos] = useState<ResumenWallboard | null>(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const recibidoRef = useRef(0);

  useEffect(() => {
    const t = window.location.hash.replace(/^#/, "");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(t || "");
  }, []);

  const conSesion = !!usuario && puede(PERMISOS.supervisionVer);

  const cargar = useCallback(async () => {
    try {
      let d: ResumenWallboard;
      if (token) {
        const res = await fetch(`${API_URL}/api/wallboard`, { headers: { "X-Wallboard-Token": token } });
        if (res.status === 401) throw new Error("Este enlace de pantalla venció o fue revocado. Pide uno nuevo al supervisor.");
        if (!res.ok) throw new Error("No se pudo actualizar");
        d = await res.json();
      } else {
        d = await api.get<ResumenWallboard>("/api/supervision/resumen");
      }
      setDatos(d);
      setError("");
      recibidoRef.current = Date.now();
      setTick(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar");
    }
  }, [token]);

  useEffect(() => {
    if (token === null || (!token && !conSesion)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
    const datosT = setInterval(cargar, CADA_MS);
    const relojT = setInterval(() => setTick(Math.floor((Date.now() - recibidoRef.current) / 1000)), 1000);
    return () => {
      clearInterval(datosT);
      clearInterval(relojT);
    };
  }, [token, conSesion, cargar]);

  if (token === null || (!token && cargando)) return <div className="min-h-screen bg-bg" />;
  if (!token && !conSesion) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg p-6 text-center">
        <div>
          <h1 className="text-2xl font-bold text-fg">Wallboard</h1>
          <p className="mt-2 text-muted">
            Entra con un usuario que pueda ver la supervisión, o abre el enlace de pantalla que se crea en Supervisión → Pantallas.
          </p>
          <a href="/login" className="mt-4 inline-block font-medium text-brand-text underline">
            Entrar
          </a>
        </div>
      </div>
    );
  }

  const pasadas = (datos?.campanas ?? []).filter((c) => c.hoy.abandono_pct != null && c.hoy.abandono_pct > c.abandono_objetivo);
  const abandonoPasado = pasadas.length > 0;

  return (
    <div className="min-h-screen bg-bg px-4 py-6 text-fg sm:p-6 lg:p-10">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">{datos?.empresa ?? "Operación"} · en vivo</h1>
          {datos && <p className="text-sm text-muted">Actualizado {new Date(datos.generado_at + "Z").toLocaleTimeString()}</p>}
        </div>
        {error && <p className="max-w-md text-right text-sm text-danger-text">{error}</p>}
      </div>

      {datos && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <Grande label="Agentes conectados" valor={datos.agentes.conectados} />
            <Grande label="Listos" valor={datos.agentes.listos} tono="text-ok-text" />
            <Grande label="En llamada" valor={datos.agentes.en_llamada} tono="text-info-text" />
            <Grande
              label="En pausa"
              valor={datos.agentes.en_pausa}
              tono={datos.agentes.pausas_excedidas ? "text-danger-text" : "text-warn-text"}
              detalle={datos.agentes.pausas_excedidas ? `${datos.agentes.pausas_excedidas} pasada(s) del máximo` : undefined}
            />
            <Grande
              label="Esperando agente"
              valor={datos.llamadas.en_espera}
              tono={datos.llamadas.en_espera ? "text-warn-text" : "text-fg"}
            />
            <Grande
              label="Abandono hoy"
              valor={datos.hoy.abandono_pct == null ? "—" : `${datos.hoy.abandono_pct} %`}
              tono={abandonoPasado ? "text-danger-text" : "text-ok-text"}
              detalle={
                abandonoPasado
                  ? `Sobre el objetivo: ${pasadas.map((c) => c.nombre).join(", ")}`
                  : `${datos.hoy.abandonadas} de ${datos.hoy.contestadas} contestadas`
              }
            />
          </div>

          {!!datos.grupos?.length && (
            <div className="mt-6">
              <GruposEnVivo grupos={datos.grupos} grande />
            </div>
          )}

          <div className="mt-6 grid gap-6 xl:grid-cols-[2fr_1fr]">
            <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5">
              <h2 className="mb-4 text-lg font-semibold">Campañas</h2>
              {datos.campanas.length === 0 ? (
                <p className="text-muted">Ninguna campaña con agentes en curso.</p>
              ) : (
                <div className="overflow-x-auto">
                <table className="w-full min-w-[28rem] text-left">
                  <thead className="text-sm text-muted">
                    <tr>
                      <th className="pb-2 font-medium">Campaña</th>
                      <th className="pb-2 text-right font-medium">Listos</th>
                      <th className="pb-2 text-right font-medium">En llamada</th>
                      <th className="pb-2 text-right font-medium">Contestadas</th>
                      <th className="pb-2 text-right font-medium">Abandono</th>
                    </tr>
                  </thead>
                  <tbody className="text-base tabular-nums lg:text-xl">
                    {datos.campanas.map((c) => {
                      const pasado = c.hoy.abandono_pct != null && c.hoy.abandono_pct > c.abandono_objetivo;
                      return (
                        <tr key={c.id} className="border-t border-line">
                          <td className="py-3 font-semibold">
                            {c.nombre}
                            {c.status !== "running" && <span className="ml-2 text-sm font-normal text-muted">(pausada)</span>}
                          </td>
                          <td className="py-3 text-right text-ok-text">{c.agentes.listo}</td>
                          <td className="py-3 text-right text-info-text">{c.agentes.en_llamada + c.agentes.timbrando}</td>
                          <td className="py-3 text-right">{c.hoy.contestadas}</td>
                          <td className={`py-3 text-right ${pasado ? "text-danger-text" : ""}`}>
                            {c.hoy.abandono_pct == null ? "—" : `${c.hoy.abandono_pct} %`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                </div>
              )}
            </div>

            <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5">
              <h2 className="mb-4 text-lg font-semibold">Agentes</h2>
              <ul className="space-y-2">
                {datos.agentes_lista.map((a, i) => {
                  const e = ESTADOS[a.estado];
                  return (
                    <li key={i} className="flex items-center justify-between gap-3 rounded-xl bg-surface-2 px-3 py-2">
                      <span className="truncate font-medium">{a.nombre}</span>
                      <span className={`whitespace-nowrap text-sm ${a.pausa_excedida ? "font-semibold text-danger-text" : "text-muted"}`}>
                        {e?.label ?? a.estado}
                        {a.pausa ? ` (${a.pausa})` : ""} · {reloj(a.en_estado_s == null ? null : a.en_estado_s + tick)}
                      </span>
                    </li>
                  );
                })}
                {datos.agentes_lista.length === 0 && <li className="text-muted">Nadie conectado.</li>}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Grande({ label, valor, tono = "text-fg", detalle }: { label: string; valor: React.ReactNode; tono?: string; detalle?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className={`text-4xl font-bold tabular-nums sm:text-5xl ${tono}`}>{valor}</div>
      <div className="mt-2 text-base text-muted">{label}</div>
      {detalle && <div className="mt-1 text-sm text-faint">{detalle}</div>}
    </div>
  );
}
