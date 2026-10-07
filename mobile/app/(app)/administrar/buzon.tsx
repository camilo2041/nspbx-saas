import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Text, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, Avatar, EstadoVacio, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito, fallo, toque } from "@/src/haptico";
import { AudioDeApi, mmss } from "@/src/Reproductor";
import { useSoftphone } from "@/src/softphone/SoftphoneContext";
import { useColores } from "@/src/tema";
import { Boton, Campo, Pildora, Tarjeta } from "@/src/ui";

interface Mensaje {
  id: number;
  extension: string;
  caller_number: string | null;
  caller_name: string | null;
  duracion: number;
  escuchado: boolean;
  created_at: string | null;
}

/** El servidor guarda en UTC sin zona. */
function cuando(s: string | null): string {
  if (!s) return "";
  const d = new Date(s.endsWith("Z") ? s : `${s}Z`);
  const hoy = new Date();
  const hora = d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === hoy.toDateString()) return `Hoy · ${hora}`;
  return `${d.toLocaleDateString("es-CO", { day: "numeric", month: "short" })} · ${hora}`;
}

/**
 * Buzón de voz: los mensajes que dejaron quienes llamaron y nadie contestó
 * (el mismo de la pantalla Buzón del panel). Al abrir uno se marca como
 * escuchado; desde acá se devuelve la llamada.
 */
export default function Buzon() {
  const c = useColores();
  const router = useRouter();
  const { call } = useSoftphone();
  const { datos, cargando, refrescando, error, sinConexion, recargar, mutar } = useDatos<Mensaje[]>("/api/buzon");
  const [abierto, setAbierto] = useState<number | null>(null);
  const [errorAccion, setErrorAccion] = useState("");

  const marcar = async (m: Mensaje, escuchado: boolean) => {
    mutar((xs) => (xs ?? []).map((x) => (x.id === m.id ? { ...x, escuchado } : x)));
    try {
      await peticion(`/api/buzon/${m.id}`, { method: "PUT", body: { escuchado } });
    } catch {
      recargar();
    }
  };

  const abrir = (m: Mensaje) => {
    toque();
    setErrorAccion("");
    setAbierto(abierto === m.id ? null : m.id);
    if (!m.escuchado) marcar(m, true);
  };

  const borrar = (m: Mensaje) =>
    Alert.alert("Borrar mensaje", "El audio se elimina del servidor.", [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Borrar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/buzon/${m.id}`, { method: "DELETE" });
            mutar((xs) => (xs ?? []).filter((x) => x.id !== m.id));
            exito();
          } catch (e) {
            fallo();
            setErrorAccion(e instanceof ApiError ? e.message : "No se pudo borrar");
          }
        },
      },
    ]);

  const devolver = (numero: string) => {
    call(numero.replace(/[^0-9+*#]/g, ""));
    router.navigate("/");
  };

  const lista = datos ?? [];
  const sinEscuchar = lista.filter((m) => !m.escuchado).length;

  return (
    <Pantalla refrescando={refrescando} onRefrescar={recargar}>
      {sinConexion ? <AvisoSinConexion /> : null}
      {error && !datos ? <Aviso texto={error} /> : null}
      {errorAccion ? <Aviso texto={errorAccion} /> : null}
      {cargando ? <ListaEsqueleto /> : null}
      {!cargando && datos && lista.length === 0 ? (
        <EstadoVacio
          icono="buzon"
          titulo="Sin mensajes"
          texto="Cuando alguien te llame, no contestes y deje un mensaje, aparece acá."
        />
      ) : null}
      {sinEscuchar > 0 ? (
        <Text style={{ fontSize: 13, color: c.textoSecundario }}>
          {sinEscuchar === 1 ? "1 mensaje sin escuchar" : `${sinEscuchar} mensajes sin escuchar`}
        </Text>
      ) : null}
      {lista.map((m) => {
        const quien = m.caller_name || m.caller_number || "Número oculto";
        return (
          <Tarjeta key={m.id} onPress={() => abrir(m)} style={{ gap: 12 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <Avatar nombre={quien} />
              <View style={{ flex: 1 }}>
                <Text numberOfLines={1} style={{ fontSize: 15, fontWeight: m.escuchado ? "500" : "800", color: c.texto }}>
                  {quien}
                </Text>
                <Text style={{ fontSize: 12.5, color: c.textoSecundario, marginTop: 2 }}>
                  {cuando(m.created_at)} · {mmss(m.duracion)} · Ext. {m.extension}
                </Text>
              </View>
              {!m.escuchado ? <Pildora texto="Nuevo" tono="marca" /> : null}
            </View>
            {abierto === m.id ? (
              <View style={{ gap: 12 }}>
                <AudioDeApi ruta={`/api/buzon/${m.id}/audio`} />
                <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                  {m.caller_number ? (
                    <Boton chico titulo="Devolver la llamada" icono="telefono" variante="ok" onPress={() => devolver(m.caller_number!)} />
                  ) : null}
                  <Boton chico titulo="Marcar como nuevo" variante="contorno" onPress={() => marcar(m, false)} />
                  <Boton chico titulo="Borrar" icono="eliminar" variante="texto" onPress={() => borrar(m)} />
                </View>
              </View>
            ) : null}
          </Tarjeta>
        );
      })}
      <PinRemoto />
    </Pantalla>
  );
}

/** PIN para escuchar el buzón marcando *96 desde otro teléfono (el mismo del panel). */
function PinRemoto() {
  const c = useColores();
  const { datos, mutar } = useDatos<{ extension: string; tiene_pin: boolean; marcar: string }>("/api/buzon/pin");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  if (!datos) return null;

  const guardar = async () => {
    setTrabajando(true);
    setError("");
    try {
      const nuevo = await peticion<typeof datos>("/api/buzon/pin", { method: "PUT", body: { pin } });
      mutar(() => nuevo);
      setPin("");
      exito();
    } catch (e) {
      fallo();
      setError(e instanceof ApiError ? e.message : "No se pudo guardar el PIN");
    } finally {
      setTrabajando(false);
    }
  };

  return (
    <Tarjeta style={{ gap: 10 }}>
      <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>Escuchar desde otro teléfono</Text>
      <Text style={{ fontSize: 13, color: c.textoSecundario, lineHeight: 19 }}>
        {datos.tiene_pin
          ? `Marca ${datos.marcar} desde cualquier extensión, luego tu extensión (${datos.extension}) y tu PIN, cada uno con #.`
          : `Ponle un PIN para escucharlo marcando ${datos.marcar} desde otro teléfono.`}
      </Text>
      <Campo
        etiqueta={datos.tiene_pin ? "Nuevo PIN" : "PIN (4 a 8 números)"}
        value={pin}
        onChangeText={(v) => setPin(v.replace(/[^0-9]/g, "").slice(0, 8))}
        keyboardType="number-pad"
        secureTextEntry
        error={error || undefined}
        ayuda="Evita PIN fáciles (1111, 1234 o tu extensión): no se aceptan."
      />
      <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
        <Boton chico titulo={datos.tiene_pin ? "Cambiar PIN" : "Guardar PIN"} cargando={trabajando} deshabilitado={pin.length < 4} onPress={guardar} />
        {datos.tiene_pin ? (
          <Boton
            chico
            titulo="Quitar el PIN"
            variante="texto"
            onPress={async () => {
              toque();
              await peticion("/api/buzon/pin", { method: "DELETE" }).catch(() => undefined);
              mutar(() => ({ ...datos, tiene_pin: false }));
            }}
          />
        ) : null}
      </View>
    </Tarjeta>
  );
}
