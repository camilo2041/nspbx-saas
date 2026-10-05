"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  Connection,
  Node,
  Edge,
  NodeChange,
  EdgeChange,
} from "@xyflow/react";
import { Button, ErrorBanner, Modal, Spinner, Table, Td, Tr } from "@/components/ui";
import { api } from "@/lib/api";
import { FlowNode, FlowEdge, TtsVoice, VoiceBot } from "@/lib/types";
import { nodeTypes } from "./FlowNodes";
import { NodePanel } from "./NodePanel";

let idCounter = 1;
const newId = () => `n${Date.now()}_${idCounter++}`;

export default function VoiceBotFlowPage() {
  const params = useParams();
  const router = useRouter();
  const botId = Number(params.id);

  const [bot, setBot] = useState<VoiceBot | null>(null);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedOk, setSavedOk] = useState(false);
  // Historial: cada guardado es una versión y se puede volver a cualquiera
  // (ver backend VoiceBotVersion). Un flujo roto se arregla en un clic.
  const [versiones, setVersiones] = useState<
    { id: number; version: number; cuando: string; quien: string | null; motivo: string | null; nodos: number }[] | null
  >(null);

  useEffect(() => {
    (async () => {
      try {
        const [b, v, flow] = await Promise.all([
          api.get<VoiceBot>(`/api/voicebots/${botId}`),
          api.get<TtsVoice[]>(`/api/voicebots/tts/voices`),
          api.get<{ nodes: FlowNode[]; edges: FlowEdge[] }>(`/api/voicebots/${botId}/flow`),
        ]);
        setBot(b);
        setVoices(v);
        setNodes(flow.nodes.length ? flow.nodes : [defaultStartNode()]);
        setEdges(flow.edges as Edge[]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al cargar el flujo");
      } finally {
        setLoading(false);
      }
    })();
  }, [botId]);

  const defaultStartNode = (): Node => ({
    id: newId(),
    type: "menu",
    position: { x: 80, y: 200 },
    data: { label: "Saludo", start: true },
  });

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback(
    (conn: Connection) => setEdges((eds) => addEdge({ ...conn, id: `e${conn.source}_${conn.sourceHandle}_${conn.target}` }, eds)),
    []
  );

  const addNode = (type: "menu" | "transfer" | "hangup") => {
    const id = newId();
    const label = type === "menu" ? "Menú de audio" : type === "transfer" ? "Transferir" : "Colgar";
    setNodes((nds) => [
      ...nds,
      { id, type, position: { x: 300 + Math.random() * 200, y: 100 + Math.random() * 300 }, data: { label } },
    ]);
  };

  const selectedNode = nodes.find((n) => n.id === selectedId) as FlowNode | undefined;

  const updateSelectedData = (patch: Partial<FlowNode["data"]>, autoSave = false) => {
    if (!selectedId) return;
    const updated = nodes.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n));
    setNodes(updated);
    // El audio/voz generado ya quedó guardado en disco del lado del backend
    // apenas se genera, pero el flujo (qué nodo usa qué archivo) solo se
    // persiste al guardar — si el usuario genera voz y no le da a "Guardar
    // flujo" antes de salir, el cambio se pierde visualmente aunque el
    // archivo exista. Se autoguarda al generar/subir audio para que "no
    // guarda" deje de pasar.
    if (autoSave) persistFlow(updated, edges);
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedId));
    setEdges((eds) => eds.filter((e) => e.source !== selectedId && e.target !== selectedId));
    setSelectedId(null);
  };

  const persistFlow = async (nodesToSave: Node[], edgesToSave: Edge[]) => {
    setSaving(true);
    setError("");
    setSavedOk(false);
    try {
      await api.put(`/api/voicebots/${botId}/flow`, {
        nodes: nodesToSave.map((n) => ({ id: n.id, type: n.type, position: n.position, data: n.data })),
        edges: edgesToSave.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle })),
      });
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar el flujo");
    } finally {
      setSaving(false);
    }
  };

  const save = () => persistFlow(nodes, edges);

  const abrirHistorial = async () => {
    try {
      setVersiones(await api.get(`/api/voicebots/${botId}/versiones`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el historial");
    }
  };

  const restaurar = async (id: number, version: number) => {
    if (!confirm(`¿Volver a la versión ${version}? Las llamadas siguientes usarán ese flujo. Se puede deshacer.`)) return;
    try {
      await api.post(`/api/voicebots/${botId}/versiones/${id}/restaurar`, {});
      const flow = await api.get<{ nodes: FlowNode[]; edges: FlowEdge[] }>(`/api/voicebots/${botId}/flow`);
      setNodes(flow.nodes.length ? flow.nodes : [defaultStartNode()]);
      setEdges(flow.edges as Edge[]);
      setVersiones(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo restaurar");
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col bg-bg">
      <div className="glass flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/80 px-5 py-3">
        <div className="min-w-0">
          <button
            onClick={() => router.push("/voicebots")}
            className="inline-flex items-center gap-1 text-xs text-muted transition-colors hover:text-brand-text"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 6l-6 6 6 6" />
            </svg>
            Voizbots
          </button>
          <h1 className="truncate text-lg font-bold tracking-tight text-fg">Flujo: {bot?.name}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => addNode("menu")}>
            + Menú de audio
          </Button>
          <Button variant="secondary" onClick={() => addNode("transfer")}>
            + Transferir
          </Button>
          <Button variant="secondary" onClick={() => addNode("hangup")}>
            + Colgar
          </Button>
          <Button variant="ghost" onClick={abrirHistorial}>
            Historial
          </Button>
          <Button onClick={save} loading={saving}>
            {saving ? "Guardando..." : savedOk ? "Guardado ✓" : "Guardar flujo"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="px-5 pt-3">
          <ErrorBanner message={error} />
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background color="var(--line-strong)" gap={18} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        {selectedNode && (
          <NodePanel
            botId={botId}
            node={selectedNode}
            voices={voices}
            onChange={updateSelectedData}
            onDelete={deleteSelected}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
      <Modal open={versiones !== null} onClose={() => setVersiones(null)} title="Historial del flujo">
        {versiones && versiones.length === 0 ? (
          <p className="text-sm text-muted">Todavía no hay versiones guardadas.</p>
        ) : (
          <Table head={["Versión", "Cuándo", "Quién", "Cambio", ""]}>
            {(versiones ?? []).map((v, i) => (
              <Tr key={v.id}>
                <Td strong>v{v.version}</Td>
                <Td muted>{new Date(v.cuando + "Z").toLocaleString()}</Td>
                <Td>{v.quien ?? "—"}</Td>
                <Td muted>
                  {v.motivo ?? ""} · {v.nodos} nodos
                </Td>
                <Td>
                  {i === 0 ? (
                    <span className="text-xs text-faint">actual</span>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={() => restaurar(v.id, v.version)}>
                      Restaurar
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Modal>
    </div>
  );
}
