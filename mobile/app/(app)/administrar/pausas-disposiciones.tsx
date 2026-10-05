import { useState } from "react";
import { View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, CampoDef, HojaFormulario, ListaEsqueleto, Pantalla } from "@/src/gestion";
import { Boton, FilaMenu, Pildora, Seccion, Segmentado } from "@/src/ui";

type Categoria = "venta" | "contacto" | "no_contacto" | "callback" | "promesa" | "no_llamar";

interface Disposicion {
  id: number;
  codigo: string;
  nombre: string;
  categoria: Categoria;
  contacto_humano: boolean;
  activa: boolean;
}

interface Pausa {
  id: number;
  codigo: string;
  nombre: string;
  pagada: boolean;
  max_minutos: number | null;
  activo: boolean;
}

const CATEGORIAS: { valor: Categoria; etiqueta: string; detalle: string }[] = [
  { valor: "venta", etiqueta: "Venta", detalle: "Cierra el lead" },
  { valor: "contacto", etiqueta: "Contacto", detalle: "Cierra el lead" },
  { valor: "promesa", etiqueta: "Promesa de pago", detalle: "Cierra el lead" },
  { valor: "no_contacto", etiqueta: "No contacto", detalle: "Lo recicla según la campaña" },
  { valor: "callback", etiqueta: "Volver a llamar", detalle: "Lo agenda con fecha y hora" },
  { valor: "no_llamar", etiqueta: "No llamar", detalle: "Lo pasa a la lista de no llamar" },
];

const codigo = (v: unknown) => String(v ?? "").trim().toUpperCase().replace(/[^A-Z0-9_]/g, "_");

/** Pausas y disposiciones del contact center (igual que en el panel). */
export default function PausasDisposiciones() {
  const [vista, setVista] = useState<"disposiciones" | "pausas">("disposiciones");
  const dispos = useDatos<Disposicion[]>("/api/contact-center/disposiciones");
  const pausas = useDatos<Pausa[]>("/api/contact-center/pausas");
  const [dispo, setDispo] = useState<Disposicion | "nueva" | null>(null);
  const [pausa, setPausa] = useState<Pausa | "nueva" | null>(null);

  const refrescar = () => {
    invalidar("/api/contact-center");
    dispos.recargar();
    pausas.recargar();
  };

  const camposDispo: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "Venta cerrada" },
    ...(dispo === "nueva" ? [{ clave: "codigo", etiqueta: "Código", placeholder: "VENTA", ayuda: "Corto, en mayúsculas. No cambia después." }] : []),
    { clave: "categoria", etiqueta: "Categoría", tipo: "opciones", opciones: CATEGORIAS },
    { clave: "contacto_humano", etiqueta: "Hubo conversación con una persona", tipo: "conmutador" },
    { clave: "activa", etiqueta: "Activa", tipo: "conmutador" },
  ];
  const camposPausa: CampoDef[] = [
    { clave: "nombre", etiqueta: "Nombre", placeholder: "Descanso" },
    ...(pausa === "nueva" ? [{ clave: "codigo", etiqueta: "Código", placeholder: "BREAK" }] : []),
    { clave: "max_minutos", etiqueta: "Máximo (minutos)", tipo: "numero", placeholder: "Sin máximo" },
    { clave: "pagada", etiqueta: "Tiempo pagado", tipo: "conmutador" },
    { clave: "activo", etiqueta: "Activo", tipo: "conmutador" },
  ];

  return (
    <Pantalla refrescando={dispos.refrescando} onRefrescar={refrescar}>
      <Segmentado
        valor={vista}
        onChange={setVista}
        opciones={[
          { valor: "disposiciones", etiqueta: "Disposiciones" },
          { valor: "pausas", etiqueta: "Pausas" },
        ]}
      />
      {vista === "disposiciones" ? (
        <>
          <Boton titulo="Nueva disposición" icono="agregar" onPress={() => setDispo("nueva")} />
          {dispos.error && !dispos.datos ? <Aviso texto={dispos.error} /> : null}
          {!dispos.datos ? <ListaEsqueleto /> : null}
          {dispos.datos ? (
            <Seccion>
              {dispos.datos.map((d, i) => (
                <FilaMenu
                  key={d.id}
                  titulo={d.nombre}
                  detalle={`${d.codigo} · ${CATEGORIAS.find((c) => c.valor === d.categoria)?.etiqueta ?? d.categoria}`}
                  derecha={d.activa ? undefined : <Pildora texto="Inactiva" tono="neutro" />}
                  onPress={() => setDispo(d)}
                  ultima={i === dispos.datos!.length - 1}
                />
              ))}
            </Seccion>
          ) : null}
        </>
      ) : (
        <>
          <Boton titulo="Nuevo código de pausa" icono="agregar" onPress={() => setPausa("nueva")} />
          {!pausas.datos ? <ListaEsqueleto /> : null}
          {pausas.datos ? (
            <Seccion>
              {pausas.datos.map((p, i) => (
                <FilaMenu
                  key={p.id}
                  titulo={p.nombre}
                  detalle={`${p.codigo}${p.max_minutos ? ` · máx. ${p.max_minutos} min` : ""}${p.pagada ? "" : " · no pagada"}`}
                  derecha={p.activo ? undefined : <Pildora texto="Inactivo" tono="neutro" />}
                  onPress={() => setPausa(p)}
                  ultima={i === pausas.datos!.length - 1}
                />
              ))}
            </Seccion>
          ) : null}
        </>
      )}
      <View />

      <HojaFormulario
        visible={dispo !== null}
        titulo={dispo === "nueva" ? "Nueva disposición" : "Editar disposición"}
        campos={camposDispo}
        inicial={
          dispo && dispo !== "nueva"
            ? { ...dispo }
            : { nombre: "", codigo: "", categoria: "contacto", contacto_humano: true, activa: true }
        }
        onGuardar={async (v) => {
          const cuerpo = {
            nombre: String(v.nombre ?? "").trim(),
            categoria: String(v.categoria || "contacto"),
            contacto_humano: !!v.contacto_humano,
            activa: !!v.activa,
          };
          if (!cuerpo.nombre) throw new Error("Ponle un nombre.");
          if (dispo === "nueva") {
            await peticion("/api/contact-center/disposiciones", { method: "POST", body: { ...cuerpo, codigo: codigo(v.codigo) } });
          } else if (dispo) {
            await peticion(`/api/contact-center/disposiciones/${dispo.id}`, { method: "PUT", body: cuerpo });
          }
          setDispo(null);
          refrescar();
        }}
        onCerrar={() => setDispo(null)}
      />
      <HojaFormulario
        visible={pausa !== null}
        titulo={pausa === "nueva" ? "Nuevo código de pausa" : "Editar código de pausa"}
        campos={camposPausa}
        inicial={
          pausa && pausa !== "nueva"
            ? { ...pausa, max_minutos: pausa.max_minutos ?? "" }
            : { nombre: "", codigo: "", max_minutos: "", pagada: true, activo: true }
        }
        onGuardar={async (v) => {
          const cuerpo = {
            nombre: String(v.nombre ?? "").trim(),
            max_minutos: String(v.max_minutos ?? "").trim() ? Number(v.max_minutos) : null,
            pagada: !!v.pagada,
            activo: !!v.activo,
          };
          if (!cuerpo.nombre) throw new Error("Ponle un nombre.");
          if (pausa === "nueva") {
            await peticion("/api/contact-center/pausas", { method: "POST", body: { ...cuerpo, codigo: codigo(v.codigo) } });
          } else if (pausa) {
            await peticion(`/api/contact-center/pausas/${pausa.id}`, { method: "PUT", body: cuerpo });
          }
          setPausa(null);
          refrescar();
        }}
        onCerrar={() => setPausa(null)}
      />
    </Pantalla>
  );
}
