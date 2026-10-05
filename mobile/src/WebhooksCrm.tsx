/**
 * Webhooks hacia el CRM de la empresa (lo mismo que en Seguridad del panel,
 * frontend/components/webhooks-crm.tsx). Ver backend/app/services/integraciones.py.
 */
import { useState } from "react";
import { Alert, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, CampoDef, Hoja, HojaFormulario } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Pildora, Seccion } from "@/src/ui";

interface Webhook {
  id: number;
  nombre: string;
  url: string;
  eventos: string[];
  activo: boolean;
  fallos_seguidos: number;
  ultimo_ok_at: string | null;
  pendientes: number;
  secreto?: string;
}

interface Entrega {
  id: number;
  evento: string;
  estado: "pendiente" | "ok" | "fallida";
  intentos: number;
  ultimo_codigo: number | null;
  ultimo_error: string | null;
  created_at: string;
}

const ESTADO = { pendiente: { texto: "Pendiente", tono: "aviso" }, ok: { texto: "Entregado", tono: "ok" }, fallida: { texto: "Fallida", tono: "peligro" } } as const;

function fecha(v: string) {
  return new Date(v + "Z").toLocaleString();
}

export function WebhooksCrm() {
  const c = useColores();
  const lista = useDatos<Webhook[]>("/api/integraciones/webhooks", { ttl: 30_000 });
  const eventos = useDatos<{ evento: string; descripcion: string }[]>("/api/integraciones/eventos", { ttl: 600_000 });
  const [editando, setEditando] = useState<Webhook | "nuevo" | null>(null);
  const [elegido, setElegido] = useState<Webhook | null>(null);
  const [entregas, setEntregas] = useState<Entrega[] | null>(null);
  const [secreto, setSecreto] = useState<string | null>(null);

  const refrescar = () => {
    invalidar("/api/integraciones");
    lista.recargar();
  };

  const campos: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "CRM de ventas" },
    { clave: "url", etiqueta: "URL", placeholder: "https://micrm.com/nspbx", ayuda: "https:// y accesible desde internet. Recibe un POST JSON por evento." },
    {
      clave: "eventos",
      etiqueta: "Eventos",
      tipo: "multiples",
      opciones: (eventos.datos ?? []).map((e) => ({ valor: e.evento, etiqueta: e.evento, detalle: e.descripcion })),
    },
  ];

  const hacer = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      exito();
      refrescar();
    } catch (e) {
      fallo();
      Alert.alert("No se pudo", e instanceof Error ? e.message : "Inténtalo de nuevo.");
    }
  };

  const abrir = async (w: Webhook) => {
    setElegido(w);
    setEntregas(null);
    try {
      setEntregas(await peticion<Entrega[]>(`/api/integraciones/webhooks/${w.id}/entregas?limite=30`));
    } catch {
      setEntregas([]);
    }
  };

  return (
    <>
      <Seccion
        titulo="Webhooks hacia tu CRM"
        accion={<Boton titulo="Nuevo" icono="agregar" variante="texto" chico onPress={() => setEditando("nuevo")} />}
      >
        {secreto ? (
          <View style={{ padding: 14, gap: 8 }}>
            <Aviso tono="info" texto="Secreto de firma: cópialo en tu CRM. No se vuelve a mostrar." />
            <Text selectable style={{ fontFamily: "monospace", fontSize: 12, color: c.texto }}>
              {secreto}
            </Text>
            <Boton titulo="Ya lo guardé" variante="suave" chico onPress={() => setSecreto(null)} />
          </View>
        ) : null}
        {(lista.datos ?? []).length === 0 ? (
          <View style={{ padding: 14 }}>
            <Text style={{ color: c.textoSecundario, fontSize: 13 }}>Sin webhooks. Con uno, tu CRM se entera al instante de lo que pasa en las llamadas.</Text>
          </View>
        ) : (
          (lista.datos ?? []).map((w, i) => (
            <FilaMenu
              key={w.id}
              titulo={w.nombre}
              detalle={`${w.eventos.join(", ")}${w.pendientes ? ` · ${w.pendientes} en cola` : ""}`}
              derecha={
                <Pildora
                  texto={!w.activo ? "Inactivo" : w.fallos_seguidos ? `${w.fallos_seguidos} fallo(s)` : w.ultimo_ok_at ? "Entregando" : "Sin envíos"}
                  tono={!w.activo ? "neutro" : w.fallos_seguidos ? "peligro" : w.ultimo_ok_at ? "ok" : "neutro"}
                />
              }
              onPress={() => abrir(w)}
              ultima={i === (lista.datos ?? []).length - 1}
            />
          ))
        )}
      </Seccion>

      <HojaFormulario
        key={editando === "nuevo" ? "nuevo" : editando?.id ?? "x"}
        visible={editando !== null}
        titulo={editando === "nuevo" ? "Nuevo webhook" : "Editar webhook"}
        campos={campos}
        inicial={
          editando && editando !== "nuevo"
            ? { nombre: editando.nombre, url: editando.url, eventos: editando.eventos.join(",") }
            : { nombre: "", url: "https://", eventos: (eventos.datos ?? []).map((e) => e.evento).join(",") }
        }
        onGuardar={async (v) => {
          const cuerpo = {
            nombre: String(v.nombre ?? "").trim(),
            url: String(v.url ?? "").trim(),
            eventos: String(v.eventos ?? "").split(",").filter(Boolean),
          };
          if (!cuerpo.nombre) throw new Error("Ponle un nombre.");
          if (!cuerpo.eventos.length) throw new Error("Elige al menos un evento.");
          if (editando === "nuevo") {
            const r = await peticion<Webhook>("/api/integraciones/webhooks", { method: "POST", body: cuerpo });
            setSecreto(r.secreto ?? null);
          } else if (editando) {
            await peticion(`/api/integraciones/webhooks/${editando.id}`, { method: "PUT", body: cuerpo });
          }
          setEditando(null);
          refrescar();
        }}
        onCerrar={() => setEditando(null)}
      />

      <Hoja visible={elegido !== null} titulo={elegido?.nombre ?? ""} onCerrar={() => setElegido(null)}>
        {elegido ? (
          <View style={{ gap: 10, padding: 20, paddingTop: 4 }}>
            <Text selectable style={{ fontSize: 12, color: c.textoSecundario }}>
              {elegido.url}
            </Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Boton
                titulo="Probar"
                variante="suave"
                chico
                style={{ flex: 1 }}
                onPress={() =>
                  hacer(async () => {
                    const e = await peticion<Entrega>(`/api/integraciones/webhooks/${elegido.id}/probar`, { method: "POST", body: {} });
                    if (e.estado !== "ok") throw new Error(`La prueba no llegó: ${e.ultimo_error ?? "sin respuesta"}`);
                    Alert.alert("Listo", "La prueba llegó a tu CRM.");
                  })
                }
              />
              <Boton
                titulo={elegido.activo ? "Desactivar" : "Activar"}
                variante="contorno"
                chico
                style={{ flex: 1 }}
                onPress={() =>
                  hacer(async () => {
                    await peticion(`/api/integraciones/webhooks/${elegido.id}`, { method: "PUT", body: { activo: !elegido.activo } });
                    setElegido(null);
                  })
                }
              />
            </View>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Boton titulo="Editar" variante="suave" chico style={{ flex: 1 }} onPress={() => { setEditando(elegido); setElegido(null); }} />
              <Boton
                titulo="Rotar secreto"
                variante="contorno"
                chico
                style={{ flex: 1 }}
                onPress={() =>
                  Alert.alert("Rotar secreto", "El de ahora deja de valer ya: actualízalo en tu CRM.", [
                    { text: "Cancelar", style: "cancel" },
                    {
                      text: "Rotar",
                      onPress: () =>
                        hacer(async () => {
                          const r = await peticion<{ secreto: string }>(`/api/integraciones/webhooks/${elegido.id}/rotar-secreto`, { method: "POST", body: {} });
                          setSecreto(r.secreto);
                          setElegido(null);
                        }),
                    },
                  ])
                }
              />
            </View>
            <Text style={{ fontSize: 14, fontWeight: "700", color: c.texto, marginTop: 6 }}>Últimos avisos</Text>
            {entregas === null ? null : entregas.length === 0 ? (
              <Text style={{ color: c.textoSecundario, fontSize: 13 }}>Todavía no hubo avisos.</Text>
            ) : (
              entregas.map((e) => (
                <View key={e.id} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: c.texto, fontSize: 13 }}>{e.evento}</Text>
                    <Text style={{ color: c.textoSecundario, fontSize: 12 }} numberOfLines={1}>
                      {fecha(e.created_at)} · {e.intentos} intento(s){e.ultimo_codigo ? ` · HTTP ${e.ultimo_codigo}` : ""}
                      {e.ultimo_error ? ` · ${e.ultimo_error}` : ""}
                    </Text>
                  </View>
                  {e.estado === "fallida" ? (
                    <Boton
                      titulo="Reintentar"
                      variante="texto"
                      chico
                      onPress={() => hacer(async () => { await peticion(`/api/integraciones/entregas/${e.id}/reintentar`, { method: "POST", body: {} }); await abrir(elegido); })}
                    />
                  ) : (
                    <Pildora texto={ESTADO[e.estado].texto} tono={ESTADO[e.estado].tono} />
                  )}
                </View>
              ))
            )}
            <Boton
              titulo="Borrar webhook"
              variante="peligro"
              onPress={() =>
                Alert.alert("Borrar", `¿Borrar «${elegido.nombre}»?`, [
                  { text: "Cancelar", style: "cancel" },
                  { text: "Borrar", style: "destructive", onPress: () => hacer(async () => { await peticion(`/api/integraciones/webhooks/${elegido.id}`, { method: "DELETE" }); setElegido(null); }) },
                ])
              }
            />
          </View>
        ) : null}
      </Hoja>
    </>
  );
}
