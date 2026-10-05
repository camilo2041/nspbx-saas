/**
 * Servidores FreeSWITCH de la plataforma y en cuál vive cada empresa (lo
 * mismo que en Empresas del panel, frontend/components/servidores-freeswitch.tsx).
 * Ver backend/app/api/nodos.py y docs/escala.md §4.
 */
import { useState } from "react";
import { Alert } from "react-native";

import { ApiError, peticion } from "@/src/api/client";
import { useDatos } from "@/src/datos";
import { Aviso, CampoDef, HojaFormulario } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { Boton, FilaMenu, Pildora, Seccion } from "@/src/ui";

export interface NodoFreeswitch {
  id: number | null;
  nombre: string;
  esl_host: string;
  esl_port: number;
  sip_host: string | null;
  capacidad_agentes: number | null;
  activo: boolean;
  principal: boolean;
  empresas: number;
  agentes_conectados: number;
  conectado?: boolean;
  error?: string;
  canales?: number | null;
}

const campos = (nuevo: boolean): CampoDef[] => [
  ...(nuevo
    ? [{ clave: "nombre", etiqueta: "Nombre", placeholder: "fs2", ayuda: "Letras, números y guiones. Su carpeta de troncales es FS_CONF/nodos/<nombre>/." }]
    : []),
  { clave: "esl_host", etiqueta: "Servidor ESL", placeholder: "10.0.0.12" },
  { clave: "esl_port", etiqueta: "Puerto ESL", tipo: "numero" },
  {
    clave: "esl_password",
    etiqueta: "Clave ESL",
    tipo: "secreto",
    ayuda: nuevo ? "Mínimo 8 caracteres. Se guarda cifrada." : "Vacía = se deja la que está.",
  },
  {
    clave: "sip_host",
    etiqueta: "Dirección SIP",
    placeholder: "fs2.pbx.ejemplo.com",
    ayuda: "A donde apunta el DNS del dominio SIP de sus empresas (ahí se registran sus teléfonos).",
  },
  { clave: "capacidad_agentes", etiqueta: "Capacidad (agentes)", tipo: "numero", ayuda: "Referencia para repartir empresas." },
  { clave: "activo", etiqueta: "Activo", tipo: "conmutador", ayuda: "Desactivado no recibe nada: sus empresas pasan al principal." },
];

export function useNodos() {
  return useDatos<NodoFreeswitch[]>("/api/plataforma/nodos", { ttl: 15_000 });
}

export function nombreServidor(nodos: NodoFreeswitch[] | undefined, id: number | null): string {
  return nodos?.find((n) => n.id === id)?.nombre ?? "principal";
}

export function ServidoresFreeswitch({ onCambio }: { onCambio: () => void }) {
  const { datos, recargar } = useNodos();
  const [editando, setEditando] = useState<NodoFreeswitch | "nuevo" | null>(null);

  const cambio = () => {
    recargar();
    onCambio();
  };

  const guardar = async (v: Record<string, unknown>) => {
    const cuerpo: Record<string, unknown> = {
      esl_host: String(v.esl_host ?? "").trim(),
      esl_port: Number(v.esl_port || 8021),
      sip_host: String(v.sip_host ?? "").trim(),
      capacidad_agentes: Number(v.capacidad_agentes || 200),
      activo: !!v.activo,
    };
    if (v.esl_password) cuerpo.esl_password = String(v.esl_password);
    if (editando === "nuevo") {
      await peticion("/api/plataforma/nodos", { method: "POST", body: { ...cuerpo, nombre: String(v.nombre ?? "").trim() } });
    } else if (editando) {
      await peticion(`/api/plataforma/nodos/${editando.id}`, { method: "PUT", body: cuerpo });
    }
    exito();
    setEditando(null);
    cambio();
  };

  const probar = async (n: NodoFreeswitch) => {
    try {
      const r = await peticion<{ conectado: boolean; version?: string; canales?: number; error?: string }>(`/api/plataforma/nodos/${n.id}/probar`, {
        method: "POST",
      });
      if (r.conectado) exito();
      else fallo();
      Alert.alert(n.nombre, r.conectado ? `Conecta: FreeSWITCH ${r.version ?? ""}, ${r.canales ?? 0} canales.` : `No conecta: ${r.error ?? ""}`);
    } catch (err) {
      Alert.alert("No se pudo probar", err instanceof Error ? err.message : "Error");
    }
  };

  const borrar = (n: NodoFreeswitch) =>
    Alert.alert("Borrar servidor", `¿Borrar ${n.nombre}?`, [
      { text: "Cancelar", style: "cancel" },
      {
        text: "Borrar",
        style: "destructive",
        onPress: async () => {
          try {
            await peticion(`/api/plataforma/nodos/${n.id}`, { method: "DELETE" });
            exito();
            setEditando(null);
            cambio();
          } catch (err) {
            Alert.alert("No se pudo borrar", err instanceof Error ? err.message : "Error");
          }
        },
      },
    ]);

  if (!datos) return null;
  return (
    <>
      <Seccion titulo="Servidores FreeSWITCH">
        {datos.map((n, i) => {
          const cap = n.capacidad_agentes;
          return (
            <FilaMenu
              key={n.id ?? "principal"}
              titulo={n.principal ? `${n.nombre} (principal)` : n.nombre}
              detalle={`${n.empresas} empresa(s) · ${n.agentes_conectados}${cap ? ` / ${cap}` : ""} agentes · ${n.esl_host}`}
              icono="servidor"
              tono={!n.activo ? "neutro" : n.conectado ? "ok" : "peligro"}
              derecha={
                !n.activo ? (
                  <Pildora texto="Desactivado" tono="neutro" />
                ) : n.conectado ? (
                  <Pildora texto={`${n.canales ?? 0} canales`} tono={cap && n.agentes_conectados >= cap * 0.9 ? "aviso" : "ok"} />
                ) : (
                  <Pildora texto="Sin conexión" tono="peligro" />
                )
              }
              onPress={n.principal ? undefined : () => setEditando(n)}
              ultima={i === datos.length - 1}
            />
          );
        })}
      </Seccion>
      <Boton titulo="Agregar servidor FreeSWITCH" icono="agregar" variante="suave" onPress={() => setEditando("nuevo")} />

      <HojaFormulario
        visible={editando !== null}
        titulo={editando === "nuevo" ? "Nuevo servidor" : editando ? editando.nombre : ""}
        campos={campos(editando === "nuevo")}
        inicial={
          editando && editando !== "nuevo"
            ? {
                esl_host: editando.esl_host,
                esl_port: String(editando.esl_port),
                esl_password: "",
                sip_host: editando.sip_host ?? "",
                capacidad_agentes: String(editando.capacidad_agentes ?? 200),
                activo: editando.activo,
              }
            : { nombre: "", esl_host: "", esl_port: "8021", esl_password: "", sip_host: "", capacidad_agentes: "200", activo: true }
        }
        extra={() =>
          editando && editando !== "nuevo" ? (
            <>
              <Boton titulo="Probar conexión" icono="diagnostico" variante="contorno" onPress={() => probar(editando)} />
              <Boton titulo="Borrar servidor" icono="eliminar" variante="texto" onPress={() => borrar(editando)} />
            </>
          ) : null
        }
        onGuardar={guardar}
        onCerrar={() => setEditando(null)}
      />
    </>
  );
}

/** Mover una empresa de servidor. Con agentes conectados pide confirmación aparte. */
export function MoverEmpresa({
  empresa,
  onCerrar,
  onCambio,
}: {
  empresa: { id: number; name: string; sip_domain: string; nodo_id: number | null } | null;
  onCerrar: () => void;
  onCambio: () => void;
}) {
  const nodos = useNodos();

  const enviar = async (nodo: string, forzar: boolean): Promise<void> => {
    if (!empresa) return;
    try {
      const r = await peticion<{ cambio: boolean; avisos?: string[] }>(`/api/plataforma/nodos/empresas/${empresa.id}`, {
        method: "PUT",
        body: { nodo_id: nodo === "" ? null : Number(nodo), forzar },
      });
      exito();
      nodos.recargar();
      onCambio();
      if (r.avisos?.length) Alert.alert("Empresa movida", `Falta:\n\n${r.avisos.join("\n\n")}`);
      onCerrar();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && !forzar && err.message.includes("conectados")) {
        await new Promise<void>((listo) =>
          Alert.alert("Agentes conectados", `${err.message}. Sus agentes perderán la sesión y tendrán que volver a entrar.`, [
            { text: "Cancelar", style: "cancel", onPress: () => listo() },
            { text: "Mover igual", style: "destructive", onPress: () => enviar(nodo, true).finally(listo) },
          ])
        );
        return;
      }
      throw err;
    }
  };

  const opciones = (nodos.datos ?? [])
    .filter((n) => n.activo)
    .map((n) => ({
      valor: n.id === null ? "" : String(n.id),
      etiqueta: n.nombre,
      detalle: `${n.agentes_conectados}${n.capacidad_agentes ? ` / ${n.capacidad_agentes}` : ""} agentes · ${n.empresas} empresa(s)`,
    }));

  return (
    <HojaFormulario
      visible={!!empresa}
      titulo={`Servidor de ${empresa?.name ?? ""}`}
      campos={[{ clave: "nodo", etiqueta: "Servidor", tipo: "opciones", opciones }]}
      inicial={{ nodo: empresa?.nodo_id == null ? "" : String(empresa.nodo_id) }}
      textoGuardar="Mover"
      extra={() => (
        <Aviso
          tono="info"
          texto={`Sus troncales pasan al servidor nuevo. Sus teléfonos tienen que registrarse ahí: cambia el DNS de ${empresa?.sip_domain ?? "su dominio SIP"}. Hazlo fuera de la jornada.`}
        />
      )}
      onGuardar={(v) => enviar(String(v.nodo ?? ""), false)}
      onCerrar={onCerrar}
    />
  );
}
