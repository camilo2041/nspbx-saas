import { useState } from "react";
import { Alert, ScrollView, Share, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, CampoDef, Esqueleto, FiltroChips, Hoja, HojaFormulario, Pantalla } from "@/src/gestion";
import { Auditoria } from "@/src/Auditoria";
import { exito, fallo } from "@/src/haptico";
import { radios, useColores } from "@/src/tema";
import { Boton, Campo, FilaMenu, Pildora, Seccion } from "@/src/ui";

interface Bloqueo {
  jail: string;
  ip: string;
  desde: number;
  hasta: number | null;
  segundos: number;
  veces: number;
}
interface Bans {
  disponible: boolean;
  vigentes: Bloqueo[];
  historico: Bloqueo[];
}
interface AlertaTrafico {
  id: number;
  tipo: string;
  detalle: string;
  cuando: string;
}
interface ClaveDebil {
  id: number;
  number: string;
  motivo: string;
}
interface ClaveApi {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
}

const TIPO_ALERTA: Record<string, string> = {
  pico: "Pico de salientes",
  madrugada: "Salientes de madrugada",
  destino_nuevo: "Destino internacional nuevo",
  cupo: "Cerca del cupo diario",
};
const JAILS: Record<string, string> = { "nspbx-freeswitch": "Central telefónica", sshd: "Acceso SSH" };
const NOMBRES_DATOS: Record<string, string> = {
  citas: "Citas",
  deudas: "Deudas",
  promesas_de_pago: "Promesas de pago",
  numeros_de_campana: "Números de campaña",
  llamadas: "Llamadas",
  conversaciones_voicebot: "Conversaciones con el voizbot",
};

const utc = (iso: string | null) => (iso ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`) : null);
const fecha = (iso: string | null) =>
  utc(iso)?.toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) ?? "—";
function duracion(seg: number) {
  if (seg <= 0) return "permanente";
  if (seg < 3600) return `${Math.round(seg / 60)} min`;
  if (seg < 86400) return `${Math.round(seg / 3600)} h`;
  return `${Math.round(seg / 86400)} días`;
}

/** Ley 1581: qué datos de un teléfono tiene la empresa, y borrarlos. */
function DatosDeUnaPersona() {
  const c = useColores();
  const [tel, setTel] = useState("");
  const [datos, setDatos] = useState<Record<string, Record<string, unknown>[]> | null>(null);
  const [confirma, setConfirma] = useState("");
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [hecho, setHecho] = useState("");

  const consultar = async () => {
    setError("");
    setHecho("");
    setConfirma("");
    setCargando(true);
    try {
      setDatos((await peticion<{ datos: Record<string, Record<string, unknown>[]> }>("/api/privacidad/titular/consultar", { method: "POST", body: { telefono: tel } })).datos);
    } catch (err) {
      setDatos(null);
      setError(err instanceof Error ? err.message : "No se pudo consultar");
    } finally {
      setCargando(false);
    }
  };

  const suprimir = () =>
    Alert.alert("Suprimir los datos", `Se borran citas, deudas, promesas, números de campaña y grabaciones de ${tel}. No se puede deshacer.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Suprimir",
        style: "destructive",
        onPress: async () => {
          setCargando(true);
          setError("");
          try {
            const r = await peticion<Record<string, number>>("/api/privacidad/titular/suprimir", { method: "POST", body: { telefono: tel, confirmacion: confirma } });
            exito();
            setDatos(null);
            setHecho(
              Object.entries(r)
                .filter(([, n]) => n > 0)
                .map(([k, n]) => `${k.replace(/_/g, " ")}: ${n}`)
                .join(" · ") || "No había nada que borrar."
            );
          } catch (err) {
            fallo();
            setError(err instanceof Error ? err.message : "No se pudo suprimir");
          } finally {
            setCargando(false);
          }
        },
      },
    ]);

  const total = datos ? Object.values(datos).reduce((n, f) => n + f.length, 0) : 0;

  return (
    <View style={{ padding: 14, gap: 12 }}>
      <Text style={{ fontSize: 12.5, color: c.textoSecundario, lineHeight: 17 }}>
        Cuando alguien pide saber qué datos suyos tiene la empresa, o que se borren. Se busca por teléfono.
      </Text>
      <Campo etiqueta="Teléfono" value={tel} onChangeText={setTel} keyboardType="phone-pad" placeholder="3001234567" />
      <Boton titulo="Consultar" icono="buscar" variante="suave" onPress={consultar} cargando={cargando && !datos} deshabilitado={!tel.trim()} />
      {error ? <Aviso texto={error} /> : null}
      {hecho ? <Aviso tono="ok" texto={`Listo: ${hecho}`} /> : null}
      {datos ? (
        total === 0 ? (
          <Aviso tono="info" texto="La empresa no tiene datos de ese teléfono." />
        ) : (
          <View style={{ gap: 10 }}>
            <Text style={{ fontSize: 13.5, color: c.texto, lineHeight: 20 }}>
              {Object.entries(datos)
                .filter(([, f]) => f.length)
                .map(([k, f]) => `${NOMBRES_DATOS[k] ?? k}: ${f.length}`)
                .join("\n")}
            </Text>
            <Boton
              titulo="Compartir (JSON)"
              icono="enviar"
              variante="contorno"
              onPress={() => Share.share({ title: `datos-${tel}.json`, message: JSON.stringify({ telefono: tel, datos }, null, 2) })}
            />
            <Text style={{ fontSize: 12, color: c.peligroTexto, lineHeight: 17 }}>
              Suprimir borra citas, deudas, promesas, números de campaña y grabaciones. Las llamadas quedan sin número, nombre ni
              resumen (se conservan para facturación). No se puede deshacer.
            </Text>
            <Campo etiqueta="Escribe el teléfono otra vez" value={confirma} onChangeText={setConfirma} keyboardType="phone-pad" />
            <Boton titulo="Suprimir" icono="eliminar" variante="peligro" onPress={suprimir} cargando={cargando} deshabilitado={!confirma.trim()} />
          </View>
        )
      ) : null}
    </View>
  );
}

export default function Seguridad() {
  const c = useColores();
  const bans = useDatos<Bans>("/api/security/bans", { ttl: 15_000 });
  const alertas = useDatos<AlertaTrafico[]>("/api/security/alertas", { ttl: 30_000 });
  const debiles = useDatos<ClaveDebil[]>("/api/security/claves-debiles", { ttl: 60_000 });
  const claves = useDatos<ClaveApi[]>("/api/claves-api", { ttl: 30_000 });
  const escopos = useDatos<Record<string, string>>("/api/claves-api/escopos", { ttl: 600_000 });

  const [verHistorico, setVerHistorico] = useState(false);
  const [creando, setCreando] = useState(false);
  const [nueva, setNueva] = useState<string | null>(null);

  const refrescar = () => {
    invalidar("/api/security");
    invalidar("/api/claves-api");
    bans.recargar();
    alertas.recargar();
    debiles.recargar();
    claves.recargar();
  };

  const camposClave: CampoDef[] = [
    { clave: "name", etiqueta: "Nombre", placeholder: "crm-ventas" },
    { clave: "dias", etiqueta: "Días de validez", tipo: "numero", ayuda: "Vacío = no vence. Conviene que venza y rotarla." },
    {
      clave: "scopes",
      etiqueta: "Qué puede hacer",
      tipo: "multiples",
      opciones: Object.entries(escopos.datos ?? {}).map(([valor, etiqueta]) => ({ valor, etiqueta })),
    },
  ];

  const crearClave = async (v: Record<string, unknown>) => {
    const nombre = String(v.name ?? "").trim();
    const scopes = String(v.scopes ?? "").split(",").filter(Boolean);
    if (nombre.length < 2) throw new Error("Ponle un nombre a la clave.");
    if (!scopes.length) throw new Error("Marca al menos un permiso.");
    const r = await peticion<{ clave: string }>("/api/claves-api", {
      method: "POST",
      body: { name: nombre, scopes, dias_validez: String(v.dias ?? "").trim() ? Number(v.dias) : null },
    });
    setCreando(false);
    setNueva(r.clave);
    invalidar("/api/claves-api");
    claves.recargar();
  };

  const revocar = (k: ClaveApi) =>
    Alert.alert("Revocar la clave", `Lo que use "${k.name}" deja de funcionar ya.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Revocar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/claves-api/${k.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/claves-api");
            claves.recargar();
          } catch (err) {
            Alert.alert("No se pudo revocar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  const b = bans.datos;
  const listaBans = verHistorico ? b?.historico ?? [] : b?.vigentes ?? [];

  return (
    <>
      <Pantalla refrescando={bans.refrescando} onRefrescar={refrescar}>
        {alertas.datos?.length ? (
          <Seccion titulo="Alertas de tráfico saliente">
            {alertas.datos.map((a, i) => (
              <FilaMenu
                key={a.id}
                titulo={TIPO_ALERTA[a.tipo] ?? a.tipo}
                detalle={`${a.detalle} · ${fecha(a.cuando)}`}
                icono="alerta"
                tono="aviso"
                ultima={i === alertas.datos!.length - 1}
              />
            ))}
          </Seccion>
        ) : null}
        {alertas.datos?.length ? (
          <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 17, marginTop: -4 }}>
            Avisan, no cortan. Si no reconoces el tráfico, pausa las salientes en Ajustes y revisa las extensiones.
          </Text>
        ) : null}

        {debiles.datos?.length ? (
          <Seccion titulo={`Contraseñas SIP débiles (${debiles.datos.length})`}>
            {debiles.datos.map((d, i) => (
              <FilaMenu key={d.id} titulo={`Extensión ${d.number}`} detalle={d.motivo} icono="llave" tono="peligro" ultima={i === debiles.datos!.length - 1} />
            ))}
          </Seccion>
        ) : null}

        <Seccion
          titulo="Bloqueos de fail2ban"
          accion={
            b?.disponible ? (
              <Pildora texto={`${b.vigentes.length} vigente(s)`} tono={b.vigentes.length ? "aviso" : "ok"} />
            ) : undefined
          }
        >
          {!b && bans.cargando ? <Esqueleto alto={90} /> : null}
          {bans.error && !b ? (
            <View style={{ padding: 14 }}>
              <Aviso texto={bans.error} />
            </View>
          ) : null}
          {b && !b.disponible ? (
            <View style={{ padding: 14 }}>
              <Aviso
                tono="aviso"
                texto="No se puede leer fail2ban: no está instalado en el servidor o falta montar su base en el contenedor (deploy/fail2ban/)."
              />
            </View>
          ) : null}
          {b?.disponible ? (
            <>
              <View style={{ padding: 12 }}>
                <FiltroChips
                  valor={verHistorico ? "h" : "v"}
                  onChange={(x) => setVerHistorico(x === "h")}
                  opciones={[
                    { valor: "v", etiqueta: "Vigentes" },
                    { valor: "h", etiqueta: "Histórico" },
                  ]}
                />
              </View>
              {listaBans.length === 0 ? (
                <FilaMenu
                  titulo={verHistorico ? "Sin registros" : "Nadie bloqueado ahora"}
                  detalle="6 intentos fallidos en 10 minutos activan un bloqueo de 24 horas."
                  icono="seguridad"
                  tono="ok"
                  ultima
                />
              ) : (
                listaBans.map((x, i) => (
                  <FilaMenu
                    key={`${x.jail}-${x.ip}-${x.desde}`}
                    titulo={x.ip}
                    detalle={`${JAILS[x.jail] ?? x.jail} · desde ${new Date(x.desde * 1000).toLocaleString("es-CO", {
                      day: "2-digit",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })} · ${verHistorico ? duracion(x.segundos) : x.hasta === null ? "permanente" : `queda ${duracion(x.hasta - Date.now() / 1000)}`}`}
                    icono="seguridad"
                    tono="peligro"
                    derecha={x.veces > 1 ? <Pildora texto={`${x.veces}ª vez`} tono="aviso" /> : undefined}
                    ultima={i === listaBans.length - 1}
                  />
                ))
              )}
            </>
          ) : null}
        </Seccion>
        <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 17, marginTop: -4 }}>
          Solo lectura a propósito: el control de fail2ban también permite reconfigurar el cortafuegos. Para desbloquear, en el servidor:
          fail2ban-client set &lt;jail&gt; unbanip &lt;ip&gt;
        </Text>

        <Seccion titulo="Datos de una persona (Ley 1581)">
          <DatosDeUnaPersona />
        </Seccion>

        <Seccion titulo="Claves de la API" accion={<Boton titulo="Nueva" icono="agregar" variante="texto" chico onPress={() => setCreando(true)} />}>
          {(claves.datos ?? []).length === 0 ? (
            <FilaMenu titulo="Sin claves" detalle="Para conectar otros sistemas (CRM, agenda, ERP) por /api/v1." icono="llave" ultima />
          ) : (
            (claves.datos ?? []).map((k, i) => {
              const vencida = !!k.expires_at && (utc(k.expires_at)?.getTime() ?? 0) < Date.now();
              return (
                <FilaMenu
                  key={k.id}
                  titulo={`${k.name} · ${k.prefix}`}
                  detalle={`${k.scopes.join(", ")} · último uso ${fecha(k.last_used_at)}${k.expires_at ? ` · vence ${fecha(k.expires_at)}` : ""}`}
                  icono="llave"
                  tono={k.revoked_at ? "neutro" : "marca"}
                  derecha={
                    k.revoked_at ? (
                      <Pildora texto="Revocada" tono="peligro" />
                    ) : vencida ? (
                      <Pildora texto="Vencida" tono="aviso" />
                    ) : (
                      <Pildora texto="Activa" tono="ok" />
                    )
                  }
                  onPress={k.revoked_at ? undefined : () => revocar(k)}
                  ultima={i === (claves.datos ?? []).length - 1}
                />
              );
            })
          )}
        </Seccion>
        {(claves.datos ?? []).some((k) => !k.revoked_at) ? (
          <Text style={{ fontSize: 12, color: c.textoSecundario, marginTop: -4 }}>Toca una clave activa para revocarla.</Text>
        ) : null}

        <Auditoria endpoint="/api/security/auditoria" titulo="Registro de auditoría" />
      </Pantalla>

      <HojaFormulario
        visible={creando}
        titulo="Nueva clave de API"
        campos={camposClave}
        inicial={{ name: "", dias: "365", scopes: "" }}
        textoGuardar="Crear clave"
        onGuardar={crearClave}
        onCerrar={() => setCreando(false)}
      />

      <Hoja visible={!!nueva} titulo="Clave creada" onCerrar={() => setNueva(null)}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 14 }}>
          <Aviso tono="aviso" texto="Cópiala ahora: no se vuelve a mostrar. Si se pierde, revócala y crea otra." />
          <Text selectable style={{ fontFamily: "monospace", fontSize: 14, color: c.texto, backgroundColor: c.superficie2, padding: 12, borderRadius: radios.medio }}>
            {nueva}
          </Text>
          <Boton titulo="Compartir" icono="enviar" variante="contorno" onPress={() => nueva && Share.share({ message: nueva })} />
          <Boton titulo="Ya la guardé" onPress={() => setNueva(null)} />
        </ScrollView>
      </Hoja>

    </>
  );
}
