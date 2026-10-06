import { useEffect, useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { Fila, Hoja } from "@/src/gestion";
import { exito, fallo, toque } from "@/src/haptico";
import { radios, useColores } from "@/src/tema";
import { Boton, BotonIcono, Segmentado } from "@/src/ui";

interface Destinos {
  extensiones: { numero: string; nombre: string | null; buzon?: boolean }[];
  grupos: { numero: string; nombre: string }[];
}

type Modo = "consultar" | "directa";

/**
 * Espera y transferencia de la llamada en curso, igual que en el softphone
 * del panel: lo hace la central (/api/llamada/*), no el teléfono, así la
 * llamada sigue las reglas de la empresa.
 *
 * - Directa: la llamada pasa al destino y sales.
 * - Consultando primero: el cliente espera con música mientras hablas con
 *   el destino; después se la pasas, vuelves con el cliente o hablan los tres.
 */
export function ControlesLlamada() {
  const c = useColores();
  const [enEspera, setEnEspera] = useState(false);
  const [consulta, setConsulta] = useState<string | null>(null);
  const [tres, setTres] = useState(false);
  const [hoja, setHoja] = useState(false);
  const [modo, setModo] = useState<Modo>("consultar");
  const [escrito, setEscrito] = useState("");
  const [destinos, setDestinos] = useState<Destinos | null>(null);
  const [trabajando, setTrabajando] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!hoja || destinos) return;
    peticion<Destinos>("/api/llamada/destinos")
      .then(setDestinos)
      .catch(() => setDestinos({ extensiones: [], grupos: [] }));
  }, [hoja, destinos]);

  const pedir = async <T,>(nombre: string, ruta: string, cuerpo?: unknown): Promise<T | null> => {
    setTrabajando(nombre);
    setError("");
    try {
      const r = await peticion<T>(ruta, { method: "POST", body: cuerpo });
      exito();
      return r;
    } catch (e) {
      fallo();
      setError(e instanceof ApiError ? e.message : "No se pudo. Revisa tu conexión.");
      return null;
    } finally {
      setTrabajando("");
    }
  };

  const nombre = (n: string): string => {
    const ext = destinos?.extensiones.find((e) => e.numero === n);
    if (ext) return ext.nombre ? ext.nombre : `la ${n}`;
    const g = destinos?.grupos.find((x) => x.numero === n);
    return g ? `el grupo ${g.nombre}` : n;
  };

  const alternarEspera = async () => {
    const r = await pedir<{ en_espera: boolean }>("espera", "/api/llamada/espera", { activar: !enEspera });
    if (r) setEnEspera(r.en_espera);
  };

  const transferir = async (destino: string) => {
    const d = destino.replace(/[^0-9+*#]/g, "");
    if (!d) return;
    const r = await pedir<{ estado: string }>(modo, "/api/llamada/transferir", { destino: d, consultada: modo === "consultar" });
    if (!r) return;
    setHoja(false);
    setEscrito("");
    if (r.estado === "consultando") {
      setConsulta(d);
      setEnEspera(true);
    }
    // Directa: la central corta esta llamada sola y la pantalla vuelve al marcador.
  };

  const terminarConsulta = () => {
    setConsulta(null);
    setTres(false);
    setEnEspera(false);
  };

  if (consulta) {
    return (
      <View style={{ gap: 10, backgroundColor: c.avisoSuave, borderRadius: radios.medio, padding: 14 }}>
        <Text style={{ color: c.avisoTexto, fontSize: 14, lineHeight: 20, textAlign: "center" }}>
          {tres
            ? `Están hablando los tres: tú, el cliente y ${nombre(consulta)}.`
            : `Hablando con ${nombre(consulta)}. El cliente espera con música.`}
        </Text>
        <Boton
          titulo={tres ? "Salir (que sigan ellos)" : "Pasarle la llamada"}
          variante="ok"
          cargando={trabajando === "completar"}
          onPress={async () => {
            if (await pedir("completar", "/api/llamada/transferencia/completar")) terminarConsulta();
          }}
        />
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Boton
            style={{ flex: 1 }}
            chico
            titulo={tres ? `Sacar a ${nombre(consulta)}` : "Volver con el cliente"}
            variante="contorno"
            cargando={trabajando === "cancelar"}
            onPress={async () => {
              if (await pedir("cancelar", "/api/llamada/transferencia/cancelar")) terminarConsulta();
            }}
          />
          {!tres ? (
            <Boton
              style={{ flex: 1 }}
              chico
              titulo="Hablar los tres"
              variante="contorno"
              cargando={trabajando === "tres"}
              onPress={async () => {
                if (await pedir("tres", "/api/llamada/transferencia/conferencia")) setTres(true);
              }}
            />
          ) : null}
        </View>
        {error ? <Text style={{ color: c.peligroTexto, fontSize: 12.5, textAlign: "center" }}>{error}</Text> : null}
      </View>
    );
  }

  const opciones = [
    ...(destinos?.extensiones ?? []).map((e) => ({ numero: e.numero, titulo: e.nombre || `Extensión ${e.numero}`, detalle: `Ext. ${e.numero}` })),
    ...(destinos?.grupos ?? []).map((g) => ({ numero: g.numero, titulo: g.nombre, detalle: `Grupo · ${g.numero}` })),
  ].filter((o) => !escrito || `${o.titulo} ${o.numero}`.toLowerCase().includes(escrito.toLowerCase()));

  return (
    <View style={{ gap: 6 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-evenly" }}>
        <View style={{ alignItems: "center", gap: 8 }}>
          <BotonIcono icono="pausa" etiqueta={enEspera ? "Retomar" : "Espera"} activo={enEspera} onPress={alternarEspera} tam={64} />
          <Text style={{ fontSize: 12.5, fontWeight: "500", color: c.textoSuave }}>{enEspera ? "Retomar" : "Espera"}</Text>
        </View>
        <View style={{ alignItems: "center", gap: 8 }}>
          <BotonIcono
            icono="transferir"
            etiqueta="Transferir"
            onPress={() => {
              toque();
              setError("");
              setHoja(true);
            }}
            tam={64}
          />
          <Text style={{ fontSize: 12.5, fontWeight: "500", color: c.textoSuave }}>Transferir</Text>
        </View>
      </View>
      {error && !hoja ? <Text style={{ color: c.peligroTexto, fontSize: 12.5, textAlign: "center" }}>{error}</Text> : null}

      <Hoja visible={hoja} titulo="Transferir la llamada" onCerrar={() => setHoja(false)}>
        <View style={{ paddingHorizontal: 20, gap: 12, paddingBottom: 8 }}>
          <Segmentado<Modo>
            valor={modo}
            onChange={setModo}
            opciones={[
              { valor: "consultar", etiqueta: "Consultar primero" },
              { valor: "directa", etiqueta: "Pasar directo" },
            ]}
          />
          <Text style={{ fontSize: 12.5, color: c.textoSecundario, lineHeight: 18 }}>
            {modo === "consultar"
              ? "El cliente espera con música mientras hablas con la otra persona; después decides."
              : "La llamada pasa ya y tú sales de ella."}
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              value={escrito}
              onChangeText={setEscrito}
              placeholder="Nombre, extensión o número"
              placeholderTextColor={c.placeholder}
              style={{
                flex: 1,
                borderWidth: 1,
                borderColor: c.borde,
                borderRadius: radios.medio,
                paddingHorizontal: 12,
                paddingVertical: 10,
                color: c.texto,
                backgroundColor: c.superficie,
              }}
            />
            <Boton
              chico
              titulo="Ir"
              onPress={() => transferir(escrito)}
              deshabilitado={!/[0-9]/.test(escrito)}
              cargando={trabajando === modo && !!escrito}
            />
          </View>
          {error ? <Text style={{ color: c.peligroTexto, fontSize: 12.5 }}>{error}</Text> : null}
        </View>
        <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 8 }} keyboardShouldPersistTaps="handled">
          {opciones.map((o) => (
            <Fila key={o.numero} titulo={o.titulo} subtitulo={o.detalle} onPress={() => transferir(o.numero)} />
          ))}
        </ScrollView>
      </Hoja>
    </View>
  );
}
