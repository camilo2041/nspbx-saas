/**
 * Consumo del mes (backend/app/services/consumo.py). En una empresa, sus
 * números; en la plataforma, una fila por empresa: la base para facturar.
 * El CSV se comparte con la hoja del sistema (correo, WhatsApp, Drive…).
 */
import { useState } from "react";
import { Share, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { useDatos } from "@/src/datos";
import { Aviso, Esqueleto } from "@/src/gestion";
import { useColores } from "@/src/tema";
import { Boton, BotonIcono, FilaMenu, Seccion } from "@/src/ui";

interface Consumo {
  mes: string;
  tenant_id: number;
  empresa?: string;
  llamadas: number;
  llamadas_contestadas: number;
  minutos_hablados: number;
  llamadas_por_troncal: number;
  minutos_por_troncal: number;
  conversaciones_ia: number;
  minutos_ia: number;
  costo_ia_usd: number;
  grabaciones_mb: number;
}

const COLUMNAS: [keyof Consumo, string][] = [
  ["minutos_por_troncal", "Minutos por troncal (se facturan)"],
  ["llamadas", "Llamadas"],
  ["llamadas_contestadas", "Contestadas"],
  ["minutos_hablados", "Minutos hablados"],
  ["conversaciones_ia", "Conversaciones con IA"],
  ["minutos_ia", "Minutos de IA"],
  ["costo_ia_usd", "Costo IA (USD)"],
  ["grabaciones_mb", "Grabaciones (MB)"],
];

const aMes = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;

function nombreMes(mes: string) {
  const [a, m] = mes.split("-").map(Number);
  const t = new Date(a, m - 1, 1).toLocaleDateString("es-CO", { month: "long", year: "numeric" });
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function ConsumoMensual({ plataforma = false }: { plataforma?: boolean }) {
  const c = useColores();
  const [mes, setMes] = useState(aMes(new Date()));
  const [error, setError] = useState("");
  const [exportando, setExportando] = useState(false);
  const ruta = plataforma ? "/api/plataforma/consumo" : "/api/consumo";
  const { datos, cargando, error: errorCarga } = useDatos<Consumo | Consumo[]>(`${ruta}?mes=${mes}`, { ttl: 60_000 });
  const filas = datos ? (Array.isArray(datos) ? datos : [datos]) : null;

  const mover = (delta: number) => {
    const [a, m] = mes.split("-").map(Number);
    const d = new Date(a, m - 1 + delta, 1);
    if (d > new Date()) return;
    setMes(aMes(d));
  };

  const exportar = async () => {
    setExportando(true);
    setError("");
    try {
      const csv = await peticion<string>(plataforma ? `/api/plataforma/consumo/csv?mes=${mes}` : "/api/consumo/csv?meses=12", { texto: true });
      await Share.share({ title: plataforma ? `consumo-${mes}.csv` : "consumo.csv", message: csv });
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo exportar");
    } finally {
      setExportando(false);
    }
  };

  return (
    <Seccion titulo="Consumo del mes" sinTarjeta>
      <View style={{ gap: 10 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          <BotonIcono icono="izquierda" etiqueta="Mes anterior" onPress={() => mover(-1)} tam={36} />
          <Text style={{ flex: 1, textAlign: "center", fontSize: 15, fontWeight: "700", color: c.texto }}>{nombreMes(mes)}</Text>
          <BotonIcono icono="derecha" etiqueta="Mes siguiente" onPress={() => mover(1)} tam={36} deshabilitado={mes === aMes(new Date())} />
        </View>
        <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 17 }}>
          Los minutos que se facturan son los que salen por una troncal; las llamadas internas no cuentan.
        </Text>
        {error || errorCarga ? <Aviso texto={error || errorCarga} /> : null}
        {!filas && cargando ? <Esqueleto alto={160} /> : null}
        {filas?.length === 0 ? <Aviso tono="info" texto="Sin consumo registrado en este mes." /> : null}
        {filas?.map((f) => (
          <Seccion key={f.tenant_id} titulo={plataforma ? f.empresa : undefined}>
            {COLUMNAS.map(([k, etiqueta], i) => (
              <FilaMenu
                key={k}
                titulo={etiqueta}
                valor={Number(f[k] ?? 0).toLocaleString("es-CO", { maximumFractionDigits: k === "costo_ia_usd" ? 2 : 1 })}
                ultima={i === COLUMNAS.length - 1}
              />
            ))}
          </Seccion>
        ))}
        <Boton titulo={plataforma ? "Compartir CSV del mes" : "Compartir CSV (12 meses)"} icono="enviar" variante="contorno" cargando={exportando} onPress={exportar} />
      </View>
    </Seccion>
  );
}
