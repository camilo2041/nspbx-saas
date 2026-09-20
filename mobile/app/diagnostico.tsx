import { useCallback, useEffect, useState } from "react";
import { Linking, PermissionsAndroid, Platform, Text, View } from "react-native";

import { Aviso, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { probarTimbre } from "@/src/timbre";
import { colores, radios } from "@/src/tema";
import { Boton, Tarjeta } from "@/src/ui";

type Estado = "ok" | "aviso" | "mal";

interface Chequeo {
  clave: string;
  estado: Estado;
  titulo: string;
  detalle: string;
}

const ICONO: Record<Estado, string> = { ok: "✅", aviso: "⚠️", mal: "❌" };

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
  const { connState, connError, entorno, pushListo, connect } = useSoftphone();
  const [notif, setNotif] = useState<boolean | null>(null);
  const [mic, setMic] = useState<boolean | null>(null);
  const [probando, setProbando] = useState(false);

  const revisar = useCallback(async () => {
    const versionNotif = Platform.OS === "android" && Number(Platform.Version) >= 33;
    setNotif(versionNotif ? await permisoAndroid("android.permission.POST_NOTIFICATIONS") : true);
    setMic(await permisoAndroid("android.permission.RECORD_AUDIO"));
  }, []);

  useEffect(() => {
    revisar();
  }, [revisar]);

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
    {
      clave: "push",
      estado: pushListo ? "ok" : "mal",
      titulo: pushListo ? "Avisos para despertar la app: activos" : "Avisos para despertar la app: NO configurados",
      detalle: pushListo
        ? "Con el teléfono bloqueado o la app cerrada, la llamada despierta la app."
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

  return (
    <Pantalla>
      <Aviso
        tono="aviso"
        texto="Una llamada entra si (1) estás conectado a la central, (2) el teléfono puede avisarte y (3) el sonido no está silenciado. Aquí ves cada punto."
      />
      {chequeos.map((c) => (
        <Tarjeta key={c.clave} style={{ flexDirection: "row", gap: 12, padding: 14 }}>
          <Text style={{ fontSize: 22 }}>{ICONO[c.estado]}</Text>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={{ fontSize: 15, fontWeight: "700", color: colores.texto }}>{c.titulo}</Text>
            <Text style={{ fontSize: 13, color: colores.textoSecundario, lineHeight: 19 }}>{c.detalle}</Text>
          </View>
        </Tarjeta>
      ))}

      <Tarjeta style={{ gap: 10 }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: colores.texto }}>Sonido y ahorro de batería</Text>
        <Text style={{ fontSize: 13, color: colores.textoSecundario, lineHeight: 19 }}>
          Si en la barra de estado ves una campana tachada, el teléfono está en silencio o «No molestar»: el timbre del sistema no suena (el de la app sí,
          con la app abierta). Además, el ahorro de batería puede cerrar la app en segundo plano: ponla como «Sin restricciones».
        </Text>
        <Boton titulo={probando ? "Sonando…" : "Probar timbre (4 s)"} variante="suave" onPress={probar} deshabilitado={probando} />
        <Boton titulo="Ajustes de batería de la app" variante="suave" onPress={abrirBateria} />
      </Tarjeta>

      {!registrado ? <Boton titulo="Reconectar con la central" onPress={() => connect()} /> : null}
      <Boton titulo="Volver a revisar" variante="suave" onPress={revisar} style={{ borderRadius: radios.medio }} />
    </Pantalla>
  );
}
