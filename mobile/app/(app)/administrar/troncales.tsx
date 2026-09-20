import { useCallback, useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import {
  Aviso,
  AvisoSinConexion,
  CampoDef,
  EstadoVacio,
  Fila,
  Hoja,
  HojaFormulario,
  ListaEsqueleto,
  Pantalla,
} from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { colores, radios } from "@/src/tema";
import { Boton, Pildora } from "@/src/ui";

interface Troncal {
  id: number;
  name: string;
  gateway_host: string;
  gateway_port: number;
  username: string | null;
  password: string | null;
  from_domain: string | null;
  register_enabled: boolean;
  caller_id_number: string | null;
  transport: string;
  ping: number | null;
  codec_prefs: string | null;
  enabled: boolean;
}

interface EstadoTroncal {
  state: string | null;
  status: string | null;
  ping_ms: string | null;
  contact_ip: string | null;
}

type Tono = "ok" | "aviso" | "peligro" | "neutro";

/** Traduce el estado de FreeSWITCH a algo que un administrador entienda. */
function leerEstado(t: Troncal, e: EstadoTroncal | "error" | undefined): { texto: string; tono: Tono; detalle: string } {
  if (!t.enabled) return { texto: "Apagada", tono: "neutro", detalle: "La troncal está desactivada: no registra ni cursa llamadas." };
  if (e === undefined) return { texto: "Consultando…", tono: "neutro", detalle: "Preguntando a la central." };
  if (e === "error") return { texto: "Sin datos", tono: "aviso", detalle: "La central no respondió. Puede estar reiniciando." };
  if (!e.state) return { texto: "No cargada", tono: "peligro", detalle: "La central no conoce esta troncal todavía. Usa «Reescanear»." };
  switch (e.state) {
    case "REGED":
      return { texto: "Registrada", tono: "ok", detalle: "Registrada con el proveedor: puede hacer y recibir llamadas." };
    case "NOREG":
      return {
        texto: e.status === "UP" ? "Activa (sin registro)" : "Sin respuesta",
        tono: e.status === "UP" ? "ok" : "peligro",
        detalle: t.register_enabled
          ? "Debería registrarse pero no lo hace."
          : "Esta troncal no usa registro (autenticación por IP): se comprueba por ping.",
      };
    case "TRYING":
    case "REGISTER":
      return { texto: "Registrando…", tono: "aviso", detalle: "Intentando registrarse con el proveedor." };
    case "FAIL_WAIT":
    case "FAILED":
      return { texto: "Falló el registro", tono: "peligro", detalle: "El proveedor rechazó el registro. Revisa usuario, contraseña y host." };
    case "UNREGED":
      return { texto: "No registrada", tono: "peligro", detalle: "La troncal no está registrada con el proveedor." };
    default:
      return { texto: e.state, tono: "aviso", detalle: `Estado reportado por la central: ${e.state}.` };
  }
}

const CAMPOS: CampoDef[] = [
  { clave: "name", etiqueta: "Nombre", placeholder: "proveedor_principal", ayuda: "Letras, números, punto, guion o guion bajo; sin espacios." },
  { clave: "gateway_host", etiqueta: "Servidor del proveedor", placeholder: "sip.proveedor.com", ayuda: "Nombre o IP a la que se conecta la central." },
  { clave: "gateway_port", etiqueta: "Puerto", tipo: "numero", placeholder: "5060" },
  {
    clave: "transport",
    etiqueta: "Transporte",
    tipo: "opciones",
    opciones: [
      { valor: "udp", etiqueta: "UDP", detalle: "El más común." },
      { valor: "tcp", etiqueta: "TCP" },
      { valor: "tls", etiqueta: "TLS", detalle: "Cifrado; solo si tu proveedor lo ofrece." },
    ],
  },
  { clave: "register_enabled", etiqueta: "Registrarse con usuario y contraseña", tipo: "conmutador", ayuda: "Apágalo si el proveedor te autoriza por IP." },
  { clave: "username", etiqueta: "Usuario", visibleSi: (v) => !!v.register_enabled },
  { clave: "password", etiqueta: "Contraseña", tipo: "secreto", visibleSi: (v) => !!v.register_enabled },
  { clave: "from_domain", etiqueta: "Dominio (opcional)", placeholder: "sip.proveedor.com", ayuda: "Solo si el proveedor pide uno distinto del servidor." },
  { clave: "caller_id_number", etiqueta: "Número que ven al recibir tu llamada", tipo: "numero", placeholder: "6012345678" },
  { clave: "ping", etiqueta: "Ping de verificación (segundos)", tipo: "numero", placeholder: "30", ayuda: "Cada cuánto comprueba que el proveedor responde (5 a 300). Vacío = sin ping." },
  { clave: "codec_prefs", etiqueta: "Códecs (opcional)", placeholder: "PCMU,PCMA", ayuda: "Orden de preferencia separado por comas." },
  { clave: "enabled", etiqueta: "Activa", tipo: "conmutador" },
];

const VACIA = {
  name: "",
  gateway_host: "",
  gateway_port: "5060",
  transport: "udp",
  register_enabled: true,
  username: "",
  password: "",
  from_domain: "",
  caller_id_number: "",
  ping: "",
  codec_prefs: "",
  enabled: true,
};

function aCuerpo(v: Record<string, unknown>) {
  const t = (k: string) => String(v[k] ?? "").trim();
  const n = (k: string) => (t(k) ? Number(t(k)) : null);
  return {
    name: t("name"),
    gateway_host: t("gateway_host"),
    gateway_port: Number(t("gateway_port") || 5060),
    transport: t("transport") || "udp",
    register_enabled: !!v.register_enabled,
    username: t("username") || null,
    password: String(v.password ?? "") || null,
    from_domain: t("from_domain") || null,
    caller_id_number: t("caller_id_number") || null,
    ping: n("ping"),
    codec_prefs: t("codec_prefs") || null,
    enabled: !!v.enabled,
  };
}

export default function Troncales() {
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Troncal[]>("/api/trunks");
  const [estados, setEstados] = useState<Record<number, EstadoTroncal | "error">>({});
  const [detalle, setDetalle] = useState<Troncal | null>(null);
  const [editando, setEditando] = useState<Troncal | "nueva" | null>(null);
  const [trabajando, setTrabajando] = useState("");
  const [resultado, setResultado] = useState<{ ok: boolean; texto: string } | null>(null);

  const consultar = useCallback(async (t: Troncal) => {
    try {
      const e = await peticion<EstadoTroncal>(`/api/trunks/${t.id}/status`);
      setEstados((a) => ({ ...a, [t.id]: e }));
    } catch (err) {
      // 502 = FreeSWITCH no responde; no es un fallo de esta troncal en particular.
      setEstados((a) => ({ ...a, [t.id]: err instanceof ApiError ? "error" : "error" }));
    }
  }, []);

  // Estado real de cada troncal, refrescado cada 15 s mientras la pantalla está abierta.
  useEffect(() => {
    if (!datos?.length) return;
    let vivo = true;
    const todas = () => datos.forEach((t) => vivo && consultar(t));
    todas();
    const id = setInterval(todas, 15_000);
    return () => {
      vivo = false;
      clearInterval(id);
    };
  }, [datos, consultar]);

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo = aCuerpo(v);
    if (editando === "nueva") await peticion("/api/trunks", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/trunks/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/trunks");
    setEditando(null);
    setDetalle(null);
    recargar();
  };

  const verificar = async (t: Troncal) => {
    setResultado(null);
    setTrabajando("verificar");
    try {
      await consultar(t);
      const e = await peticion<EstadoTroncal>(`/api/trunks/${t.id}/status`);
      const l = leerEstado(t, e);
      setResultado({ ok: l.tono === "ok", texto: `${l.texto}. ${l.detalle}${e.ping_ms ? ` Ping: ${e.ping_ms} ms.` : ""}` });
      l.tono === "ok" ? exito() : fallo();
    } catch (err) {
      setResultado({ ok: false, texto: err instanceof Error ? err.message : "No se pudo consultar" });
      fallo();
    } finally {
      setTrabajando("");
    }
  };

  const reescanear = async (t: Troncal) => {
    setResultado(null);
    setTrabajando("reescanear");
    try {
      await peticion(`/api/trunks/${t.id}/rescan`, { method: "POST" });
      setResultado({ ok: true, texto: "Listo: la central volvió a cargar la troncal. Espera unos segundos y pulsa «Verificar estado»." });
      exito();
    } catch (err) {
      setResultado({ ok: false, texto: err instanceof Error ? err.message : "No se pudo reescanear" });
      fallo();
    } finally {
      setTrabajando("");
    }
  };

  const eliminar = (t: Troncal) => {
    Alert.alert("Eliminar troncal", `Se borrará «${t.name}». Las llamadas salientes que la usen dejarán de salir.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/trunks/${t.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/trunks");
            setDetalle(null);
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const lecturaDetalle = detalle ? leerEstado(detalle, estados[detalle.id]) : null;
  const estadoDetalle = detalle ? estados[detalle.id] : undefined;
  const ipPrivada =
    estadoDetalle && estadoDetalle !== "error" && estadoDetalle.contact_ip
      ? /^(10\.|127\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(estadoDetalle.contact_ip)
      : false;

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="+ Nueva troncal" onPress={() => setEditando("nueva")} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio
            icono="🔌"
            titulo="Aún no hay troncales"
            texto="Una troncal conecta tu central con el proveedor que te da los números y la salida a la red telefónica."
          />
        ) : null}
        {(datos ?? []).map((t) => {
          const l = leerEstado(t, estados[t.id]);
          return (
            <Fila
              key={t.id}
              titulo={t.name}
              subtitulo={`${t.gateway_host}:${t.gateway_port} · ${t.transport.toUpperCase()}`}
              izquierda={
                <View style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: colores.marcaSuave, alignItems: "center", justifyContent: "center" }}>
                  <Text style={{ fontSize: 20 }}>🔌</Text>
                </View>
              }
              derecha={<Pildora texto={l.texto} tono={l.tono} />}
              onPress={() => {
                setResultado(null);
                setDetalle(t);
              }}
            />
          );
        })}
      </Pantalla>

      <Hoja visible={!!detalle && editando === null} titulo={detalle?.name ?? ""} onCerrar={() => setDetalle(null)}>
        {detalle && lecturaDetalle ? (
          <View style={{ padding: 20, paddingTop: 4, gap: 14 }}>
            <View style={{ backgroundColor: colores.superficie2, borderRadius: radios.medio, padding: 14, gap: 8 }}>
              <Pildora texto={lecturaDetalle.texto} tono={lecturaDetalle.tono} />
              <Text style={{ fontSize: 13, color: colores.textoSuave, lineHeight: 19 }}>{lecturaDetalle.detalle}</Text>
              {estadoDetalle && estadoDetalle !== "error" && estadoDetalle.ping_ms ? (
                <Text style={{ fontSize: 12, color: colores.textoSecundario }}>Ping al proveedor: {estadoDetalle.ping_ms} ms</Text>
              ) : null}
              {estadoDetalle && estadoDetalle !== "error" && estadoDetalle.contact_ip ? (
                <Text style={{ fontSize: 12, color: colores.textoSecundario }}>IP que anuncia la central: {estadoDetalle.contact_ip}</Text>
              ) : null}
            </View>
            {ipPrivada ? (
              <Aviso
                tono="aviso"
                texto="La central anuncia una IP privada al proveedor: se verá «registrada», pero las llamadas entrantes no podrán llegar. Revisa la IP pública en la configuración del servidor."
              />
            ) : null}
            <Text style={{ fontSize: 12.5, color: colores.textoSecundario }}>
              {detalle.gateway_host}:{detalle.gateway_port} · {detalle.transport.toUpperCase()}
              {detalle.username ? ` · usuario ${detalle.username}` : ""}
            </Text>
            {resultado ? <Aviso texto={resultado.texto} tono={resultado.ok ? "ok" : "peligro"} /> : null}
            <Boton titulo="Verificar estado" onPress={() => verificar(detalle)} cargando={trabajando === "verificar"} />
            <Boton titulo="Reescanear en la central" variante="suave" onPress={() => reescanear(detalle)} cargando={trabajando === "reescanear"} />
            <Boton titulo="Editar" variante="suave" onPress={() => setEditando(detalle)} />
          </View>
        ) : null}
      </Hoja>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva troncal" : "Editar troncal"}
        campos={CAMPOS}
        inicial={
          editando && editando !== "nueva"
            ? {
                ...editando,
                gateway_port: String(editando.gateway_port),
                ping: editando.ping === null ? "" : String(editando.ping),
                username: editando.username ?? "",
                password: editando.password ?? "",
                from_domain: editando.from_domain ?? "",
                caller_id_number: editando.caller_id_number ?? "",
                codec_prefs: editando.codec_prefs ?? "",
              }
            : VACIA
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? () => eliminar(editando) : undefined}
      />
    </>
  );
}
