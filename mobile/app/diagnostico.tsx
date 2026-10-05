import { useCallback, useEffect, useState } from "react";
import { AppState, Linking, PermissionsAndroid, Platform, Text, View } from "react-native";

import * as conexion from "@/modules/conexion-permanente";
import { ApiError, peticion } from "@/src/api/client";
import { Aviso, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { probarTimbre } from "@/src/timbre";
import { radios, useColores } from "@/src/tema";
import { Boton, CajaIcono, Segmentado, Tarjeta } from "@/src/ui";
import type { ModoConexion } from "@/src/softphone/conexionPermanente";
import type { NombreIcono } from "@/src/Icono";

type Estado = "ok" | "aviso" | "mal";

interface Chequeo {
  clave: string;
  estado: Estado;
  titulo: string;
  detalle: string;
}

const ICONO: Record<Estado, [NombreIcono, "ok" | "aviso" | "peligro"]> = {
  ok: ["ok", "ok"],
  aviso: ["alerta", "aviso"],
  mal: ["error", "peligro"],
};

async function permisoAndroid(permiso: string): Promise<boolean> {
  if (Platform.OS !== "android") return true;
  try {
    return await PermissionsAndroid.check(permiso as never);
  } catch {
    return false;
  }
}

/**
 * Explica por qué una llamada puede NO entrar o NO sonar, revisando lo que sí se
 * puede comprobar desde la app. Lo que no (modo silencio, ahorro de batería) se
 * explica con el paso exacto para revisarlo.
 */
export default function Diagnostico() {
  const col = useColores();
  const { connState, connError, entorno, pushListo, connect, conexionPermanente } = useSoftphone();
  const [bateriaLibre, setBateriaLibre] = useState(true);
  const [notif, setNotif] = useState<boolean | null>(null);
  const [mic, setMic] = useState<boolean | null>(null);
  const [probando, setProbando] = useState(false);
  const [pruebaPush, setPruebaPush] = useState<{ ok: boolean; texto: string } | null>(null);
  const [enviandoPush, setEnviandoPush] = useState(false);

  const revisar = useCallback(async () => {
    const versionNotif = Platform.OS === "android" && Number(Platform.Version) >= 33;
    setNotif(versionNotif ? await permisoAndroid("android.permission.POST_NOTIFICATIONS") : true);
    setMic(await permisoAndroid("android.permission.RECORD_AUDIO"));
    setBateriaLibre(conexion.sinRestriccionBateria());
  }, []);

  useEffect(() => {
    revisar();
    // Al volver del diálogo de batería del sistema.
    const sub = AppState.addEventListener("change", (e) => {
      if (e === "active") revisar();
    });
    return () => sub.remove();
  }, [revisar]);

  const permanente = conexionPermanente.disponible && conexionPermanente.modo !== "apagada";

  const registrado = connState === "registered";
  const chequeos: Chequeo[] = [
    {
      clave: "extension",
      estado: entorno?.extension ? (entorno.extension.enabled ? "ok" : "mal") : "mal",
      titulo: entorno?.extension ? `Extensión ${entorno.extension.number}` : "Sin extensión asignada",
      detalle: entorno?.extension
        ? entorno.extension.enabled
          ? "Tu usuario tiene una extensión activa."
          : "Tu extensión está desactivada: pídele a un administrador que la active."
        : "Sin extensión no se pueden recibir llamadas. Pídele a un administrador que te asigne una.",
    },
    {
      clave: "registro",
      estado: registrado ? "ok" : connState === "connecting" ? "aviso" : "mal",
      titulo: registrado ? "Conectado a la central" : connState === "connecting" ? "Conectando…" : "Sin conexión con la central",
      detalle: registrado
        ? "La central sabe dónde encontrarte: las llamadas llegan a este teléfono."
        : connError || "Mientras no diga «Conectado», ninguna llamada puede entrar. Revisa tu internet o toca «Reconectar».",
    },
    ...(permanente
      ? [
          {
            clave: "permanente",
            estado: (conexionPermanente.activa && bateriaLibre ? "ok" : "aviso") as Estado,
            titulo: conexionPermanente.activa ? "Conexión permanente: activa" : "Conexión permanente: esperando conexión",
            detalle: !bateriaLibre
              ? "Falta sacar la app del ahorro de batería (abajo): sin eso, con la pantalla apagada Android le corta internet y las llamadas dejan de entrar."
              : conexionPermanente.activa
                ? "La app sigue conectada con la pantalla apagada o en segundo plano (verás la notificación fija «Central conectada»)."
                : "Se activa sola en cuanto la extensión quede conectada a la central.",
          },
        ]
      : []),
    {
      clave: "push",
      estado: pushListo ? "ok" : permanente ? "aviso" : "mal",
      titulo: pushListo ? "Avisos para despertar la app: activos" : "Avisos para despertar la app: NO configurados",
      detalle: pushListo
        ? "Con el teléfono bloqueado o la app cerrada, la llamada despierta la app."
        : permanente
          ? "No configurados: si la app se detiene del todo («Forzar detención», reiniciar el teléfono o el ahorro de algunas marcas), no entra nada hasta que la vuelvas a abrir."
          : "Sin esto, las llamadas SOLO entran con la app abierta en pantalla. Con la app en segundo plano o el teléfono bloqueado no llega nada. Requiere configurar Firebase (Android) o Apple (iPhone) en la app y en el servidor: pídeselo a quien administra la central.",
    },
    {
      clave: "notificaciones",
      estado: notif === null ? "aviso" : notif ? "ok" : "mal",
      titulo: notif ? "Notificaciones permitidas" : "Notificaciones bloqueadas",
      detalle: notif
        ? "La llamada entrante puede mostrarse sobre la pantalla."
        : "Sin este permiso Android no muestra la llamada entrante. Actívalo en Ajustes → Aplicaciones → NSPBX → Notificaciones.",
    },
    {
      clave: "microfono",
      estado: mic === null ? "aviso" : mic ? "ok" : "mal",
      titulo: mic ? "Micrófono permitido" : "Micrófono sin permiso",
      detalle: mic ? "Podrás hablar en las llamadas." : "Sin micrófono la llamada conecta pero queda muda. Actívalo en Ajustes → Aplicaciones → NSPBX → Permisos.",
    },
  ];

  const abrirBateria = () => {
    if (Platform.OS === "android") {
      Linking.sendIntent("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS").catch(() => Linking.openSettings());
    } else Linking.openSettings();
  };

  const probar = async () => {
    setProbando(true);
    await probarTimbre(4);
    exito();
    setTimeout(() => setProbando(false), 4200);
  };

  // Pide al servidor una llamada de PRUEBA por push a este teléfono, a los 15 s: da tiempo a cerrar la
  // app y bloquear la pantalla, que es justo lo que hay que comprobar.
  const probarPush = async () => {
    setEnviandoPush(true);
    setPruebaPush(null);
    try {
      const r = await peticion<{ segundos: number }>("/api/auth/probar-push", { method: "POST", body: { segundos: 15 } });
      setPruebaPush({
        ok: true,
        texto: `Listo: en ${r.segundos} segundos te llamará «Prueba de NSPBX». Ahora cierra la app (deslízala fuera de recientes) y bloquea el teléfono. Si suena, las llamadas te van a entrar aunque no tengas la app abierta.`,
      });
    } catch (e) {
      setPruebaPush({ ok: false, texto: e instanceof ApiError ? e.message : "No se pudo pedir la prueba. Revisa tu conexión." });
    } finally {
      setEnviandoPush(false);
    }
  };

  return (
    <Pantalla>
      <Aviso
        tono="aviso"
        texto="Una llamada entra si (1) estás conectado a la central, (2) el teléfono puede avisarte y (3) el sonido no está silenciado. Aquí ves cada punto."
      />
      {chequeos.map((c) => (
        <Tarjeta key={c.clave} style={{ flexDirection: "row", gap: 12, padding: 14 }}>
          <CajaIcono icono={ICONO[c.estado][0]} tono={ICONO[c.estado][1]} tam={36} />
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={{ fontSize: 15, fontWeight: "700", color: col.texto }}>{c.titulo}</Text>
            <Text style={{ fontSize: 13, color: col.textoSecundario, lineHeight: 19 }}>{c.detalle}</Text>
          </View>
        </Tarjeta>
      ))}

      {conexionPermanente.disponible ? (
        <Tarjeta style={{ gap: 10 }}>
          <Text style={{ fontSize: 15, fontWeight: "700", color: col.texto }}>Recibir llamadas con la pantalla apagada</Text>
          <Text style={{ fontSize: 13, color: col.textoSecundario, lineHeight: 19 }}>
            Mantiene la app conectada a la central todo el tiempo, con una notificación fija. No necesita Firebase.
            «Máxima» no deja dormir al procesador: úsala solo si con «Normal» se pierden llamadas (gasta bastante más batería).
          </Text>
          <Segmentado<ModoConexion>
            opciones={[
              { valor: "apagada", etiqueta: "Apagada" },
              { valor: "normal", etiqueta: "Normal" },
              { valor: "maxima", etiqueta: "Máxima" },
            ]}
            valor={conexionPermanente.modo}
            onChange={(m) => conexionPermanente.cambiarModo(m)}
          />
          {permanente && !bateriaLibre ? (
            <>
              <Aviso tono="aviso" texto="Paso obligatorio: permite que la app funcione sin restricciones de batería." />
              <Boton titulo="Quitar restricción de batería" icono="ajustes" onPress={() => conexion.pedirSinRestriccionBateria()} />
            </>
          ) : null}
          {permanente ? (
            <>
              <Text style={{ fontSize: 12.5, color: col.textoSecundario, lineHeight: 18 }}>
                En Xiaomi, Huawei, Oppo, Vivo y Samsung hay además un ahorro propio de la marca: en los ajustes de la app, pon la batería en «Sin
                restricciones» y activa el «Inicio automático» si aparece. En algunas marcas cerrar la app deslizándola la detiene; y tras reiniciar el teléfono hay que abrirla una vez.
              </Text>
              <Boton titulo="Ajustes de la app" icono="ajustes" variante="suave" onPress={() => conexion.abrirAjustesApp()} />
            </>
          ) : null}
        </Tarjeta>
      ) : null}

      <Tarjeta style={{ gap: 10 }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: col.texto }}>Sonido y ahorro de batería</Text>
        <Text style={{ fontSize: 13, color: col.textoSecundario, lineHeight: 19 }}>
          Si en la barra de estado ves una campana tachada, el teléfono está en silencio o «No molestar»: el timbre del sistema no suena (el de la app sí,
          con la app abierta). Además, el ahorro de batería puede cerrar la app en segundo plano: ponla como «Sin restricciones».
        </Text>
        <Boton titulo={probando ? "Sonando…" : "Probar timbre (4 s)"} icono="altavoz" variante="suave" onPress={probar} deshabilitado={probando} />
        <Boton titulo="Ajustes de batería de la app" icono="ajustes" variante="suave" onPress={abrirBateria} />
      </Tarjeta>

      <Tarjeta style={{ gap: 10 }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: col.texto }}>Probar una llamada con la app cerrada</Text>
        <Text style={{ fontSize: 13, color: col.textoSecundario, lineHeight: 19 }}>
          Es la prueba que de verdad importa: el servidor te manda una llamada de prueba por push. No necesitas que nadie te llame.
        </Text>
        {pruebaPush ? <Aviso texto={pruebaPush.texto} tono={pruebaPush.ok ? "ok" : "peligro"} /> : null}
        <Boton titulo="Enviarme una llamada de prueba en 15 s" icono="notificaciones" onPress={probarPush} cargando={enviandoPush} />
      </Tarjeta>

      {!registrado ? <Boton titulo="Reconectar con la central" onPress={() => connect()} /> : null}
      <Boton titulo="Volver a revisar" icono="refrescar" variante="suave" onPress={revisar} style={{ borderRadius: radios.medio }} />
    </Pantalla>
  );
}
