import { Contact, ContactField, getPermissionsAsync, requestPermissionsAsync } from "expo-contacts";
import { useCallback, useEffect, useState } from "react";

export interface ContactoTel {
  clave: string;
  nombre: string;
  numeros: { etiqueta: string; numero: string }[];
}

export type EstadoContactos = "revisando" | "sin-permiso" | "denegado" | "cargando" | "listo" | "error";

/** Contactos del teléfono, solo lectura. El permiso se pide únicamente cuando la persona abre la pestaña. */
export function useContactos(activo: boolean) {
  const [estado, setEstado] = useState<EstadoContactos>("revisando");
  const [contactos, setContactos] = useState<ContactoTel[]>([]);

  const cargar = useCallback(async () => {
    setEstado("cargando");
    try {
      const filas = await Contact.getAllDetails([ContactField.GIVEN_NAME, ContactField.FAMILY_NAME, ContactField.PHONES] as const);
      const lista: ContactoTel[] = [];
      filas.forEach((c, i) => {
        const numeros = (c.phones ?? [])
          .map((p: { label?: string | null; number?: string | null }) => ({ etiqueta: p.label ?? "", numero: (p.number ?? "").trim() }))
          .filter((p: { numero: string }) => p.numero.length >= 3);
        const nombre = `${c.givenName ?? ""} ${c.familyName ?? ""}`.trim();
        if (numeros.length) lista.push({ clave: `${i}-${nombre}`, nombre: nombre || numeros[0].numero, numeros });
      });
      lista.sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
      setContactos(lista);
      setEstado("listo");
    } catch {
      setEstado("error");
    }
  }, []);

  useEffect(() => {
    if (!activo) return;
    let vivo = true;
    getPermissionsAsync()
      .then((p) => {
        if (!vivo) return;
        if (p.granted) cargar();
        else setEstado(p.canAskAgain === false ? "denegado" : "sin-permiso");
      })
      .catch(() => vivo && setEstado("error"));
    return () => {
      vivo = false;
    };
  }, [activo, cargar]);

  const pedirPermiso = useCallback(async () => {
    const p = await requestPermissionsAsync();
    if (p.granted) await cargar();
    else setEstado(p.canAskAgain === false ? "denegado" : "sin-permiso");
  }, [cargar]);

  return { estado, contactos, pedirPermiso };
}
