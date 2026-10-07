"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { api } from "@/lib/api";

interface Pregunta {
  id: number;
  pregunta: string;
  veces: number;
  origen: "panel" | "app";
  ultima_vez: string;
}

/**
 * «¿Cómo hago…?» que ninguna guía respondió (services/preguntas_sin_guia.py),
 * las más repetidas primero: dice qué guía escribir (frontend/lib/guias.ts y
 * mobile/src/guias.ts). «Ya tiene guía» la saca hasta que se vuelva a preguntar.
 */
export function PreguntasSinGuia() {
  const [lista, setLista] = useState<Pregunta[] | null>(null);
  useEffect(() => {
    api.get<Pregunta[]>("/api/plataforma/preguntas-sin-guia").then(setLista, () => setLista(null));
  }, []);
  if (!lista || !lista.length) return null;
  return (
    <Card className="mb-4">
      <CardHeader
        title="Preguntas sin guía"
        subtitle="Lo que la gente le pregunta al asistente y ninguna guía en pantalla responde. Las más repetidas son las próximas guías por escribir."
      />
      <ul className="divide-y divide-line border-t border-line">
        {lista.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-sm">
            <span className="w-12 shrink-0 text-right font-semibold tabular-nums text-fg">{p.veces}×</span>
            <span className="min-w-0 flex-1 text-fg-soft">«{p.pregunta}»</span>
            <Badge color={p.origen === "app" ? "violet" : "blue"}>{p.origen === "app" ? "App" : "Panel"}</Badge>
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                await api.del(`/api/plataforma/preguntas-sin-guia/${p.id}`).catch(() => undefined);
                setLista((xs) => (xs ?? []).filter((x) => x.id !== p.id));
              }}
            >
              Ya tiene guía
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
