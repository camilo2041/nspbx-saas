/**
 * Registro de auditoría: quién hizo qué, cuándo y desde dónde. Lo usan
 * Seguridad (la empresa, /api/security/auditoria) y Empresas (la plataforma,
 * /api/plataforma/auditoria), igual que el panel.
 */
import { useState } from "react";
import { View } from "react-native";

import { useDatos } from "@/src/datos";
import { FiltroChips, Hoja } from "@/src/gestion";
import { radios, useColores } from "@/src/tema";
import { FilaMenu, Pildora, Seccion, Tono } from "@/src/ui";

interface Registro {
  id: number;
  cuando: string;
  actor: string | null;
  accion: string;
  recurso: string | null;
  resultado: string;
  ip: string | null;
  tenant_id?: number | null;
}

const RESULTADO: Record<string, Tono> = { ok: "ok", denegado: "aviso", rechazado: "aviso", error: "peligro" };

export const fechaUtc = (iso: string | null) =>
  iso
    ? new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";

export function Auditoria({ endpoint, titulo }: { endpoint: string; titulo: string }) {
  const c = useColores();
  const [resultado, setResultado] = useState("");
  const [abierto, setAbierto] = useState<Registro | null>(null);
  const { datos } = useDatos<Registro[]>(`${endpoint}?limite=100${resultado ? `&resultado=${resultado}` : ""}`, { ttl: 15_000 });
  const filas = datos ?? [];

  return (
    <Seccion titulo={titulo} sinTarjeta>
      <View style={{ gap: 8 }}>
        <FiltroChips
          valor={resultado}
          onChange={setResultado}
          opciones={[
            { valor: "", etiqueta: "Todos" },
            { valor: "ok", etiqueta: "Correctos" },
            { valor: "denegado", etiqueta: "Denegados" },
            { valor: "rechazado", etiqueta: "Rechazados" },
            { valor: "error", etiqueta: "Con error" },
          ]}
        />
        <View style={{ borderRadius: radios.grande, borderWidth: 1, borderColor: c.borde, backgroundColor: c.superficie, overflow: "hidden" }}>
          {datos && filas.length === 0 ? <FilaMenu titulo="Sin registros con este filtro" icono="info" ultima /> : null}
          {filas.map((x, i) => (
            <FilaMenu
              key={x.id}
              titulo={x.accion}
              detalle={`${x.actor ?? "—"} · ${fechaUtc(x.cuando)}`}
              derecha={<Pildora texto={x.resultado} tono={RESULTADO[x.resultado] ?? "info"} />}
              onPress={() => setAbierto(x)}
              ultima={i === filas.length - 1}
            />
          ))}
        </View>
      </View>

      <Hoja visible={!!abierto} titulo={abierto?.accion ?? ""} onCerrar={() => setAbierto(null)}>
        {abierto ? (
          <View style={{ padding: 20, paddingTop: 4 }}>
            <Seccion>
              <FilaMenu titulo="Quién" icono="usuario" valor={abierto.actor ?? "—"} />
              <FilaMenu titulo="Cuándo" icono="horario" valor={fechaUtc(abierto.cuando)} />
              <FilaMenu titulo="Recurso" icono="info" valor={abierto.recurso ?? "—"} />
              {abierto.tenant_id != null ? <FilaMenu titulo="Empresa" icono="servidor" valor={`#${abierto.tenant_id}`} /> : null}
              <FilaMenu titulo="Resultado" icono="ok" valor={abierto.resultado} />
              <FilaMenu titulo="IP" icono="mundo" valor={abierto.ip ?? "—"} ultima />
            </Seccion>
          </View>
        ) : null}
      </Hoja>
    </Seccion>
  );
}
