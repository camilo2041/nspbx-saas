import { useState } from "react";
import { Alert } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, AvisoSinConexion, CampoDef, EstadoVacio, Fila, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { exito } from "@/src/haptico";
import { Boton, CajaIcono, Pildora } from "@/src/ui";

interface Ruta {
  id: number;
  name: string;
  pattern: string;
  strip_digits: number;
  prepend: string | null;
  trunk_ids: string;
  allow_international: boolean;
  priority: number;
  enabled: boolean;
}

/**
 * Qué marca la regla y con qué número sale, calculado mientras se escribe
 * (mismo cálculo que el panel). El error caro acá es silencioso: una regla
 * que atrapa de más manda llamadas por la troncal equivocada.
 */
function ejemplo(patron: string, quitar: number, anteponer: string): string {
  const simbolos: string[] = [];
  for (let i = 0; i < patron.length; i++) {
    const ch = patron[i];
    if (ch === "[") {
      const fin = patron.indexOf("]", i);
      if (fin < 0) return "Patrón incompleto: falta cerrar ]";
      simbolos.push(patron[i + 1] ?? "1");
      i = fin;
    } else if (ch === "X") simbolos.push("5");
    else if (ch === "Z") simbolos.push("3");
    else if (ch === "N") simbolos.push("7");
    else if (ch === ".") simbolos.push("123");
    else simbolos.push(ch);
  }
  if (!simbolos.length) return "";
  if (quitar >= simbolos.length) return "Quitas más dígitos de los que tiene el patrón";
  return `Marcando ${simbolos.join("")} sale ${anteponer + simbolos.slice(quitar).join("")}`;
}

export default function RutasSalientes() {
  const { datos, cargando, refrescando, error, sinConexion, recargar } = useDatos<Ruta[]>("/api/outbound-routes");
  const troncales = useDatos<{ id: number; name: string }[]>("/api/trunks", { ttl: 60_000 });
  const [editando, setEditando] = useState<Ruta | "nueva" | null>(null);

  const nombreTroncal = (id: string) => troncales.datos?.find((t) => String(t.id) === id)?.name ?? `#${id}`;

  const campos: CampoDef[] = [
    { clave: "name", etiqueta: "Nombre", placeholder: "Celulares Colombia" },
    {
      clave: "pattern",
      etiqueta: "Patrón de marcado",
      placeholder: "3XXXXXXXXX",
      ayuda: "X = 0-9 · Z = 1-9 · N = 2-9 · . = uno o más · [1-5] = rango. Ej.: 3XXXXXXXXX celulares, 601XXXXXXX fijos de Bogotá.",
    },
    { clave: "priority", etiqueta: "Prioridad", tipo: "numero", ayuda: "Se revisan de menor a mayor; la primera que coincide gana." },
    { clave: "strip_digits", etiqueta: "Quitar dígitos por la izquierda", tipo: "numero" },
    { clave: "prepend", etiqueta: "Anteponer (después de quitar)", tipo: "telefono", placeholder: "57" },
    {
      clave: "trunk_ids",
      etiqueta: "Sale por (si el primero falla, prueba el siguiente)",
      tipo: "multiples",
      conOrden: true,
      opciones: (troncales.datos ?? []).map((t) => ({ valor: String(t.id), etiqueta: t.name })),
      ayuda: "Si la primera rechaza, se intenta la siguiente. Sin ninguna marcada se usan todas las habilitadas.",
    },
    {
      clave: "allow_international",
      etiqueta: "Permitir internacional",
      tipo: "conmutador",
      ayuda: "Apagado bloquea los prefijos 00 y 011, donde vive el fraude telefónico.",
    },
    { clave: "enabled", etiqueta: "Activa", tipo: "conmutador" },
  ];

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo = {
      name: String(v.name ?? "").trim(),
      pattern: String(v.pattern ?? "").trim(),
      priority: Number(v.priority) || 0,
      strip_digits: Number(v.strip_digits) || 0,
      prepend: String(v.prepend ?? "").trim() || null,
      trunk_ids: String(v.trunk_ids ?? ""),
      allow_international: !!v.allow_international,
      enabled: !!v.enabled,
    };
    if (editando === "nueva") await peticion("/api/outbound-routes", { method: "POST", body: cuerpo });
    else if (editando) await peticion(`/api/outbound-routes/${editando.id}`, { method: "PUT", body: cuerpo });
    invalidar("/api/outbound-routes");
    setEditando(null);
    recargar();
  };

  const eliminar = () => {
    if (!editando || editando === "nueva") return;
    const r = editando;
    Alert.alert("Eliminar ruta", `Lo que marque "${r.pattern}" saldrá por la siguiente regla que coincida, o por todas las troncales.`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Eliminar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/outbound-routes/${r.id}`, { method: "DELETE" });
            exito();
            invalidar("/api/outbound-routes");
            setEditando(null);
            recargar();
          } catch (err) {
            Alert.alert("No se pudo eliminar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);
  };

  const lista = [...(datos ?? [])].sort((a, b) => a.priority - b.priority);
  const r = editando === "nueva" ? null : editando;

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Boton titulo="Nueva ruta saliente" icono="agregar" onPress={() => setEditando("nueva")} />
        {sinConexion ? <AvisoSinConexion /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <ListaEsqueleto filas={3} /> : null}
        {datos && datos.length === 0 ? (
          <EstadoVacio
            icono="saliente"
            titulo="No hay rutas salientes"
            texto="Sin reglas, todo sale por la cadena completa de troncales habilitadas. Crea reglas para separar celulares de fijos o abrir internacional solo donde haga falta."
          />
        ) : null}
        {lista.map((x) => {
          const ids = x.trunk_ids.split(",").filter(Boolean);
          return (
            <Fila
              key={x.id}
              titulo={`${x.name} · ${x.pattern}`}
              subtitulo={`${ids.length ? ids.map(nombreTroncal).join(" → ") : "Todas las troncales"} · prioridad ${x.priority}`}
              izquierda={<CajaIcono icono="saliente" tono={x.allow_international ? "aviso" : "ok"} />}
              derecha={
                !x.enabled ? (
                  <Pildora texto="Apagada" tono="neutro" />
                ) : x.allow_international ? (
                  <Pildora texto="Internacional" tono="aviso" icono="mundo" />
                ) : undefined
              }
              onPress={() => setEditando(x)}
            />
          );
        })}
      </Pantalla>

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nueva" ? "Nueva ruta saliente" : r?.name ?? ""}
        campos={campos}
        inicial={{
          name: r?.name ?? "",
          pattern: r?.pattern ?? "",
          priority: r?.priority ?? 10,
          strip_digits: r?.strip_digits ?? 0,
          prepend: r?.prepend ?? "",
          trunk_ids: r?.trunk_ids ?? "",
          allow_international: r?.allow_international ?? false,
          enabled: r?.enabled ?? true,
        }}
        extra={(v) => {
          const texto = ejemplo(String(v.pattern ?? "").trim(), Number(v.strip_digits) || 0, String(v.prepend ?? "").trim());
          return texto ? <Aviso tono="info" texto={texto} /> : null;
        }}
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
        onEliminar={editando && editando !== "nueva" ? eliminar : undefined}
      />
    </>
  );
}
