import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { radios, useColores } from "@/src/tema";
import { Pildora } from "@/src/ui";

interface Ficha {
  contacto: { nombre: string | null; documento: string | null; ciudad: string | null } | null;
  no_llamar: boolean;
  notas: { texto: string; autor: string | null }[];
  llamadas: { started_at: string; estado: string }[];
}

/** El número dentro de «Nombre (3001234567)» o el texto tal cual. */
export function numeroDe(remoto: string): string {
  const m = remoto.match(/\(([^)]+)\)\s*$/);
  return (m ? m[1] : remoto).replace(/[^0-9+]/g, "");
}

/**
 * Quién llama, según el CRM de la empresa (la misma ficha del panel, fase C):
 * su nombre, si está en «no llamar», la última nota y cuántas veces llamó.
 * Solo números de afuera (más de 6 dígitos); en silencio si no se encuentra.
 */
export function FichaLlamada({ remoto }: { remoto: string }) {
  const c = useColores();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const numero = numeroDe(remoto);

  useEffect(() => {
    let vivo = true;
    setFicha(null);
    if (numero.replace("+", "").length < 7) return;
    peticion<Ficha>(`/api/llamada/ficha?numero=${encodeURIComponent(numero)}`).then(
      (f) => vivo && setFicha(f),
      () => undefined,
    );
    return () => {
      vivo = false;
    };
  }, [numero]);

  if (!ficha || (!ficha.contacto && !ficha.no_llamar && !ficha.llamadas.length)) return null;
  const nota = ficha.notas[0];
  return (
    <View style={{ backgroundColor: c.superficie, borderColor: c.borde, borderWidth: 1, borderRadius: radios.medio, padding: 12, gap: 6, alignSelf: "stretch" }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ fontSize: 15, fontWeight: "700", color: c.texto }}>{ficha.contacto?.nombre || "Cliente sin nombre"}</Text>
        {ficha.no_llamar ? <Pildora texto="No llamar" tono="peligro" /> : null}
        {ficha.llamadas.length ? <Pildora texto={`${ficha.llamadas.length} llamada(s) antes`} tono="neutro" /> : null}
      </View>
      {ficha.contacto?.documento || ficha.contacto?.ciudad ? (
        <Text style={{ fontSize: 12.5, color: c.textoSecundario }}>
          {[ficha.contacto?.documento, ficha.contacto?.ciudad].filter(Boolean).join(" · ")}
        </Text>
      ) : null}
      {nota ? (
        <Text style={{ fontSize: 13, color: c.textoSuave }} numberOfLines={3}>
          «{nota.texto}»{nota.autor ? ` — ${nota.autor}` : ""}
        </Text>
      ) : null}
    </View>
  );
}
