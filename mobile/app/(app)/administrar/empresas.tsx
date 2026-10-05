import { useState } from "react";
import { Alert, ScrollView, Share, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { Auditoria, fechaUtc } from "@/src/Auditoria";
import { ConsumoMensual } from "@/src/ConsumoMensual";
import { MoverEmpresa, ServidoresFreeswitch, nombreServidor, useNodos } from "@/src/ServidoresFreeswitch";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, Avatar, CampoDef, EstadoVacio, Fila, Hoja, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { radios, useColores } from "@/src/tema";
import { Boton, FilaMenu, Pildora, Seccion, Tono } from "@/src/ui";

interface Licencia {
  plan: string;
  status: string;
  estado: string;
  expires_at: string | null;
  max_outbound_minutes_day: number | null;
  max_outbound_cps: number | null;
}

interface Empresa {
  id: number;
  name: string;
  slug: string;
  sip_domain: string;
  subdomain: string | null;
  business_type: string;
  modules: string[];
  enabled: boolean;
  outbound_blocked: boolean;
  /** Servidor FreeSWITCH donde vive (null = el principal). */
  nodo_id: number | null;
  users_count: number;
  extensions_count: number;
  licencia: Licencia | null;
}

interface Creada extends Empresa {
  admin_username: string;
  admin_password: string;
}

const TIPOS = [
  { valor: "general", etiqueta: "General / PBX" },
  { valor: "clinica", etiqueta: "Consultorio / Salud (citas)" },
  { valor: "cobranza", etiqueta: "Cobranza / Cartera" },
];
const PLANES = [
  { valor: "trial", etiqueta: "Prueba (15 días)" },
  { valor: "free", etiqueta: "Gratis" },
  { valor: "pro", etiqueta: "Pro" },
  { valor: "enterprise", etiqueta: "Enterprise (sin límites)" },
  { valor: "custom", etiqueta: "Personalizado" },
];
const ESTADO_LIC: Record<string, { texto: string; tono: Tono }> = {
  ok: { texto: "Licencia activa", tono: "ok" },
  vencida: { texto: "Vencida", tono: "peligro" },
  suspendida: { texto: "Suspendida", tono: "aviso" },
};

const camposEmpresa = (nueva: boolean): CampoDef[] => [
  { clave: "name", etiqueta: "Nombre", placeholder: "Consultorio Andino" },
  { clave: "business_type", etiqueta: "Tipo de empresa", tipo: "opciones", opciones: TIPOS },
  {
    clave: "modules",
    etiqueta: "Módulos contratados",
    tipo: "multiples",
    opciones: [
      { valor: "voicebot", etiqueta: "Voicebot IA", detalle: "Voizbots, campañas, cobranza y consumo de IA" },
      { valor: "pbx", etiqueta: "Telefonía / Call", detalle: "Extensiones, troncales, softphone, llamadas y colas" },
    ],
  },
  ...(nueva
    ? [
        {
          clave: "slug",
          etiqueta: "Identificador interno (slug)",
          placeholder: "consultorio-andino",
          ayuda: "Minúsculas y guiones. De él salen el contexto del dialplan y el prefijo de las troncales. No se cambia después.",
        },
      ]
    : []),
  { clave: "sip_domain", etiqueta: "Dominio SIP", placeholder: "consultorio-andino.pbx.local", ayuda: "Distinto al de las demás empresas." },
  {
    clave: "subdomain",
    etiqueta: "Subdominio del panel",
    placeholder: "consultorio-andino",
    ayuda: "La etiqueta antes del dominio base. Vacío al crear = el slug. El acceso desde ese subdominio queda atado a esta empresa.",
  },
];

const CAMPOS_LICENCIA: CampoDef[] = [
  { clave: "plan", etiqueta: "Plan", tipo: "opciones", opciones: PLANES, ayuda: "Al cambiar de plan se aplican sus límites." },
  {
    clave: "status",
    etiqueta: "Estado",
    tipo: "opciones",
    opciones: [
      { valor: "trial", etiqueta: "Prueba" },
      { valor: "active", etiqueta: "Activa" },
      { valor: "suspended", etiqueta: "Suspendida" },
    ],
  },
  { clave: "expires_at", etiqueta: "Vence el", tipo: "fecha", opcional: true, ayuda: "Vacío = sin vencimiento." },
  {
    clave: "minutos",
    etiqueta: "Minutos salientes por día",
    tipo: "numero",
    placeholder: "El del plan",
    ayuda: "Al llegar se cortan las salientes hasta medianoche. Vacío = el del plan.",
  },
  {
    clave: "cps",
    etiqueta: "Llamadas salientes por segundo",
    tipo: "numero",
    placeholder: "El del plan",
    ayuda: "Freno de fraude: más que esto por segundo se rechaza. Vacío = el del plan.",
  },
];

export default function Empresas() {
  const c = useColores();
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Empresa[]>("/api/tenants");
  const global = useDatos<{ outbound_blocked: boolean }>("/api/plataforma/salientes", { ttl: 10_000 });
  const alertas = useDatos<{ id: number; empresa?: string; detalle: string; cuando: string }[]>("/api/plataforma/alertas", { ttl: 30_000 });
  const csp = useDatos<{ directiva: string; origen: string; pagina: string; veces: number; ultima: string }[]>("/api/plataforma/csp", {
    ttl: 60_000,
  });

  const [abierta, setAbierta] = useState<Empresa | null>(null);
  const [editando, setEditando] = useState<Empresa | "nueva" | null>(null);
  const [licencia, setLicencia] = useState<Empresa | null>(null);
  const [creada, setCreada] = useState<Creada | null>(null);
  const [cambiando, setCambiando] = useState(false);
  const [aviso, setAviso] = useState("");
  const bloqueados = useDatos<{ prefijos: string; fijos: string[] }>("/api/plataforma/destinos-bloqueados", { ttl: 30_000 });
  const [editandoBloqueados, setEditandoBloqueados] = useState(false);
  const nodos = useNodos();
  const [moviendo, setMoviendo] = useState<Empresa | null>(null);

  const todo = () => {
    invalidar("/api/tenants");
    invalidar("/api/plataforma");
    recargar();
    global.recargar();
    alertas.recargar();
    nodos.recargar();
  };

  const guardar = async (v: Record<string, unknown>) => {
    const modulos = String(v.modules ?? "").split(",").filter(Boolean);
    const cuerpo = {
      name: String(v.name ?? "").trim(),
      sip_domain: String(v.sip_domain ?? "").trim(),
      subdomain: String(v.subdomain ?? "").trim() || null,
      business_type: v.business_type || "general",
      // Nunca una empresa sin ningún módulo.
      modules: modulos.length ? modulos : ["voicebot"],
    };
    if (editando === "nueva") {
      const r = await peticion<Creada>("/api/tenants", { method: "POST", body: { ...cuerpo, slug: String(v.slug ?? "").trim().toLowerCase() } });
      setCreada(r);
    } else if (editando) {
      await peticion(`/api/tenants/${editando.id}`, { method: "PUT", body: cuerpo });
    }
    setEditando(null);
    setAbierta(null);
    todo();
  };

  const guardarLicencia = async (v: Record<string, unknown>) => {
    if (!licencia) return;
    const lic = licencia.licencia;
    const cuerpo: Record<string, unknown> = {
      plan: v.plan,
      status: v.status,
      expires_at: v.expires_at ? `${String(v.expires_at).slice(0, 10)}T23:59:59` : null,
    };
    // Los topes solo se envían si se cambiaron: reenviar el efectivo lo
    // dejaría fijo aunque después se cambie de plan.
    const minutos = String(v.minutos ?? "").trim();
    if (minutos !== (lic?.max_outbound_minutes_day != null ? String(lic.max_outbound_minutes_day) : "")) {
      cuerpo.max_outbound_minutes_day = minutos ? Number(minutos) : null;
    }
    const cps = String(v.cps ?? "").trim();
    if (cps !== (lic?.max_outbound_cps != null ? String(lic.max_outbound_cps) : "")) {
      cuerpo.max_outbound_cps = cps ? Number(cps) : null;
    }
    await peticion(`/api/tenants/${licencia.id}/licencia`, { method: "PUT", body: cuerpo });
    setLicencia(null);
    setAbierta(null);
    todo();
  };

  // Al cortar, se ofrece colgar también lo que está hablando ahora: en un
  // fraude son justo las llamadas que se están facturando.
  const colgarEnCurso = (ruta: string, quien: string) =>
    Alert.alert("Salientes cortadas", `¿Colgar también las llamadas salientes de ${quien} que están en curso?`, [
      { text: "No", style: "cancel" },
      {
        text: "Colgar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(ruta, { method: "POST" });
            exito();
          } catch (err) {
            Alert.alert("No se pudieron colgar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const salientesEmpresa = (e: Empresa) => {
    const cortar = !e.outbound_blocked;
    const aplicar = async () => {
      setCambiando(true);
      try {
        await peticion(`/api/tenants/${e.id}`, { method: "PUT", body: { outbound_blocked: cortar } });
        exito();
        setAbierta(null);
        todo();
        if (cortar) colgarEnCurso(`/api/tenants/${e.id}/salientes/colgar`, e.name);
      } catch (err) {
        fallo();
        Alert.alert("No se pudo cambiar", err instanceof Error ? err.message : "Error");
      } finally {
        setCambiando(false);
      }
    };
    if (!cortar) return aplicar();
    Alert.alert("Cortar salientes", `${e.name} no podrá llamar afuera ni reactivarlo por su cuenta.`, [
      { text: "Cancelar", style: "cancel" },
      { text: "Cortar", style: "destructive", onPress: aplicar },
    ]);
  };

  const salientesGlobal = () => {
    const cortar = !global.datos?.outbound_blocked;
    const aplicar = async () => {
      setCambiando(true);
      try {
        await peticion("/api/plataforma/salientes", { method: "PUT", body: { outbound_blocked: cortar } });
        exito();
        todo();
        if (cortar) colgarEnCurso("/api/plataforma/salientes/colgar", "todas las empresas");
        else setAviso("Salientes de la plataforma reactivadas.");
      } catch (err) {
        fallo();
        Alert.alert("No se pudo cambiar", err instanceof Error ? err.message : "Error");
      } finally {
        setCambiando(false);
      }
    };
    if (!cortar) return aplicar();
    Alert.alert("Cortar TODAS las salientes", "Ninguna empresa podrá llamar afuera hasta que lo reactives. Úsalo ante un fraude en curso o un problema con el proveedor.", [
      { text: "Cancelar", style: "cancel" },
      { text: "Cortar todo", style: "destructive", onPress: aplicar },
    ]);
  };

  const eliminar = (e: Empresa) =>
    Alert.alert("Eliminar empresa", `Se borran ${e.name} y TODOS sus datos. No se puede deshacer.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/tenants/${e.id}`, { method: "DELETE" });
            exito();
            setAbierta(null);
            todo();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const cortadoGlobal = !!global.datos?.outbound_blocked;

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={todo}>
        {aviso ? <Aviso tono="ok" texto={aviso} /> : null}
        <View
          style={{
            gap: 10,
            padding: 14,
            borderRadius: radios.grande,
            borderWidth: 1,
            borderColor: cortadoGlobal ? c.peligro : c.borde,
            backgroundColor: cortadoGlobal ? c.peligroSuave : c.superficie,
          }}
        >
          <Text style={{ fontSize: 15, fontWeight: "700", color: cortadoGlobal ? c.peligroTexto : c.texto }}>
            {cortadoGlobal ? "Salientes cortadas en toda la plataforma" : "Salientes de la plataforma"}
          </Text>
          <Text style={{ fontSize: 12.5, color: c.textoSecundario, lineHeight: 17 }}>
            Interruptor de emergencia: corta toda llamada saliente nueva de todas las empresas.
          </Text>
          <Boton
            titulo={cortadoGlobal ? "Reactivar salientes" : "Cortar todas las salientes"}
            icono={cortadoGlobal ? "reproducir" : "emergencia"}
            variante={cortadoGlobal ? "suave" : "peligro"}
            cargando={cambiando}
            onPress={salientesGlobal}
          />
        </View>

        {bloqueados.datos ? (
          <Seccion titulo="Destinos bloqueados">
            <FilaMenu
              titulo="Bloqueados para todas las empresas"
              detalle={
                bloqueados.datos.prefijos
                  ? bloqueados.datos.prefijos.split(",").map((p) => `+${p}`).join(", ")
                  : "Ninguno además de los fijos (satelitales y tarifas premium)"
              }
              icono="mundo"
              tono="peligro"
              onPress={() => setEditandoBloqueados(true)}
              ultima
            />
          </Seccion>
        ) : null}

        {alertas.datos?.length ? (
          <Seccion titulo="Alertas de tráfico saliente">
            {alertas.datos.slice(0, 20).map((a, i, arr) => (
              <FilaMenu
                key={a.id}
                titulo={a.empresa ?? "—"}
                detalle={`${a.detalle} · ${fechaUtc(a.cuando)}`}
                icono="alerta"
                tono="aviso"
                ultima={i === arr.length - 1}
              />
            ))}
          </Seccion>
        ) : null}

        <ServidoresFreeswitch onCambio={todo} />

        <Boton titulo="Nueva empresa" icono="agregar" onPress={() => setEditando("nueva")} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto /> : null}
        {datos && datos.length === 0 ? <EstadoVacio icono="servidor" titulo="No hay empresas" texto="Crea la primera para empezar a operar." /> : null}
        {(datos ?? []).map((e) => {
          const est = ESTADO_LIC[e.licencia?.estado ?? "ok"] ?? ESTADO_LIC.ok;
          return (
            <Fila
              key={e.id}
              titulo={e.name}
              subtitulo={`${e.subdomain ?? e.slug} · ${e.users_count} usuario(s) · ${e.modules.map((m) => (m === "pbx" ? "Call" : "Voicebot")).join(" + ")}`}
              izquierda={<Avatar nombre={e.name} />}
              derecha={
                !e.enabled ? (
                  <Pildora texto="Inactiva" tono="peligro" />
                ) : e.outbound_blocked ? (
                  <Pildora texto="Salientes cortadas" tono="peligro" />
                ) : (
                  <Pildora texto={est.texto} tono={est.tono} />
                )
              }
              onPress={() => setAbierta(e)}
            />
          );
        })}

        <ConsumoMensual plataforma />

        {csp.datos ? (
          <Seccion titulo="Política de contenido (CSP)">
            {csp.datos.length === 0 ? (
              <FilaMenu titulo="Sin avisos" detalle="Ningún navegador reportó algo que la política completa bloquearía." icono="seguridad" tono="ok" ultima />
            ) : (
              csp.datos.map((a, i) => (
                <FilaMenu
                  key={`${a.directiva}|${a.origen}|${a.pagina}`}
                  titulo={`${a.directiva}: ${a.origen}`}
                  detalle={`${a.pagina} · ${a.veces} vez/veces · última ${fechaUtc(a.ultima)}`}
                  icono="seguridad"
                  tono="aviso"
                  ultima={i === csp.datos!.length - 1}
                />
              ))
            )}
          </Seccion>
        ) : null}

        <Auditoria endpoint="/api/plataforma/auditoria" titulo="Auditoría de la plataforma" />
      </Pantalla>

      <MoverEmpresa
        empresa={moviendo}
        onCerrar={() => {
          setMoviendo(null);
          setAbierta(null);
        }}
        onCambio={todo}
      />

      <Hoja visible={!!abierta && !editando && !licencia && !moviendo} titulo={abierta?.name ?? ""} onCerrar={() => setAbierta(null)}>
        {abierta ? (
          <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 14 }}>
            <Seccion>
              <FilaMenu titulo="Tipo" icono="ajustes" valor={TIPOS.find((t) => t.valor === abierta.business_type)?.etiqueta ?? abierta.business_type} />
              <FilaMenu titulo="Dominio SIP" icono="servidor" valor={abierta.sip_domain} />
              <FilaMenu titulo="Subdominio" icono="mundo" valor={abierta.subdomain ?? "—"} />
              <FilaMenu
                titulo="Servidor FreeSWITCH"
                icono="servidor"
                valor={nombreServidor(nodos.datos, abierta.nodo_id)}
                onPress={() => setMoviendo(abierta)}
              />
              <FilaMenu titulo="Usuarios / extensiones" icono="usuarios" valor={`${abierta.users_count} / ${abierta.extensions_count}`} />
              <FilaMenu
                titulo="Licencia"
                icono="llave"
                tono="marca"
                detalle={`${PLANES.find((p) => p.valor === abierta.licencia?.plan)?.etiqueta ?? abierta.licencia?.plan ?? "Sin licencia"}${
                  abierta.licencia?.expires_at ? ` · vence ${abierta.licencia.expires_at.slice(0, 10)}` : ""
                }`}
                derecha={<Pildora texto={(ESTADO_LIC[abierta.licencia?.estado ?? "ok"] ?? ESTADO_LIC.ok).texto} tono={(ESTADO_LIC[abierta.licencia?.estado ?? "ok"] ?? ESTADO_LIC.ok).tono} />}
                onPress={() => setLicencia(abierta)}
                ultima
              />
            </Seccion>
            <Boton
              titulo={abierta.outbound_blocked ? "Reactivar salientes" : "Cortar salientes"}
              icono={abierta.outbound_blocked ? "reproducir" : "emergencia"}
              variante={abierta.outbound_blocked ? "suave" : "peligro"}
              cargando={cambiando}
              onPress={() => salientesEmpresa(abierta)}
            />
            <Boton
              titulo="Cerrar las sesiones de sus usuarios"
              icono="salir"
              variante="contorno"
              onPress={() =>
                Alert.alert(
                  "Cerrar sesiones",
                  `Todos los usuarios de ${abierta.name} salen de todos sus equipos. Pueden volver a entrar con su contraseña; para impedirlo, desactiva la empresa.`,
                  [
                    { text: "Cancelar", style: "cancel" },
                    {
                      text: "Cerrar sesiones",
                      style: "destructive",
                      onPress: async () => {
                        try {
                          const r = await peticion<{ usuarios: number }>(`/api/tenants/${abierta.id}/cerrar-sesiones`, { method: "POST" });
                          exito();
                          setAviso(`Sesiones cerradas: ${r.usuarios} usuario(s) de ${abierta.name}.`);
                          setAbierta(null);
                        } catch (err) {
                          Alert.alert("No se pudo", err instanceof Error ? err.message : "Error");
                        }
                      },
                    },
                  ]
                )
              }
            />
            <Boton titulo="Editar" icono="editar" variante="suave" onPress={() => setEditando(abierta)} />
            <Boton titulo="Eliminar empresa" icono="eliminar" variante="texto" onPress={() => eliminar(abierta)} />
          </ScrollView>
        ) : null}
      </Hoja>

      <HojaFormulario
        visible={editandoBloqueados}
        titulo="Destinos bloqueados"
        campos={[
          {
            clave: "prefijos",
            etiqueta: "Códigos de país o prefijos (sin el +)",
            tipo: "telefono",
            placeholder: "53, 7, 2346",
            ayuda: `Ninguna empresa los puede marcar, aunque los tenga entre sus países permitidos. Siempre bloqueados, además: +${(
              bloqueados.datos?.fijos ?? []
            ).join(", +")}.`,
          },
        ]}
        inicial={{ prefijos: (bloqueados.datos?.prefijos ?? "").split(",").filter(Boolean).join(", ") }}
        onGuardar={async (v) => {
          await peticion("/api/plataforma/destinos-bloqueados", { method: "PUT", body: { prefijos: String(v.prefijos ?? "") } });
          setEditandoBloqueados(false);
          invalidar("/api/plataforma");
          bloqueados.recargar();
          setAviso("Destinos bloqueados guardados: aplican desde la próxima llamada.");
        }}
        onCerrar={() => setEditandoBloqueados(false)}
      />

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva empresa" : editando ? `Editar ${editando.name}` : ""}
        campos={camposEmpresa(editando === "nueva")}
        inicial={
          editando && editando !== "nueva"
            ? { ...editando, subdomain: editando.subdomain ?? "", modules: (editando.modules.length ? editando.modules : ["voicebot", "pbx"]).join(",") }
            : { name: "", business_type: "general", modules: "voicebot,pbx", slug: "", sip_domain: "", subdomain: "" }
        }
        textoGuardar={editando === "nueva" ? "Crear empresa" : "Guardar"}
        extra={() =>
          editando === "nueva" ? <Aviso tono="info" texto="Se crea también su administrador; verás sus credenciales una sola vez." /> : null
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
      />

      <HojaFormulario
        visible={!!licencia}
        titulo={`Licencia · ${licencia?.name ?? ""}`}
        campos={CAMPOS_LICENCIA}
        inicial={{
          plan: licencia?.licencia?.plan ?? "trial",
          status: licencia?.licencia?.status ?? "trial",
          expires_at: licencia?.licencia?.expires_at?.slice(0, 10) ?? "",
          minutos: licencia?.licencia?.max_outbound_minutes_day ?? "",
          cps: licencia?.licencia?.max_outbound_cps ?? "",
        }}
        onGuardar={guardarLicencia}
        onCerrar={() => setLicencia(null)}
      />

      <Hoja visible={!!creada} titulo="Empresa creada" onCerrar={() => setCreada(null)}>
        {creada ? (
          <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 14 }}>
            <Aviso tono="aviso" texto="Estas credenciales solo se muestran una vez. Con ellas entra el administrador de la empresa en su subdominio." />
            <Text
              selectable
              style={{ fontFamily: "monospace", fontSize: 14, lineHeight: 22, color: c.texto, backgroundColor: c.superficie2, padding: 12, borderRadius: radios.medio }}
            >
              {`Usuario: ${creada.admin_username}\nContraseña: ${creada.admin_password}`}
            </Text>
            <Boton
              titulo="Compartir"
              icono="enviar"
              variante="contorno"
              onPress={() =>
                Share.share({ message: `${creada.name}\nUsuario: ${creada.admin_username}\nContraseña: ${creada.admin_password}` })
              }
            />
            <Boton titulo="Entendido" onPress={() => setCreada(null)} />
          </ScrollView>
        ) : null}
      </Hoja>
    </>
  );
}
