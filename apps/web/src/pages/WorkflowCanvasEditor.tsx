import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  addEdge,
  MarkerType,
  type Connection,
  type Node,
  type Edge,
  type NodeChange,
} from "@xyflow/react";
import {
  ArrowLeft,
  Code2,
  Save,
  Loader2,
  Maximize2,
  Trash2,
  Undo2,
  Redo2,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  Copy,
  MousePointerClick,
  GitBranch,
  Sparkles,
  MessageSquare,
  Bot,
  LayoutGrid,
  Play,
  Square,
  Terminal,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import type { Workflow } from "@aigc/shared-types";

import { Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { nodeTypes } from "@/components/workflow/nodes";
import { NodePalette } from "@/components/workflow/NodePalette";
import { apiClient } from "@/lib/apiClient";
import {
  autoLayout,
  generateNodeId,
  isValidWorkflowGraph,
  toAppGraph,
  toReactFlow,
  type AppGraph,
} from "@/lib/workflowGraphAdapter";

type ViewMode = "canvas" | "json";

/* ──────────────────────────────────────────────────────────────────────
   Outer wrapper – owns ReactFlowProvider + data fetching
   ────────────────────────────────────────────────────────────────────── */
export function WorkflowCanvasEditor() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isNew = !id;

  // ── Local UI state ───────────────────────────────────────────────
  const [name, setName] = useState("未命名工作流");
  const [workflowType, setWorkflowType] = useState("sequential");
  const [description, setDescription] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("canvas");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  // ── React Flow state ─────────────────────────────────────────────
  const [nodes, setNodes, onNodesChangeInternal] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChangeInternal] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Refs to always have latest nodes/edges (avoids stale closure in undo/redo)
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;

  // ── Undo / Redo history ──────────────────────────────────────────
  const [past, setPast] = useState<Array<{ nodes: Node[]; edges: Edge[] }>>([]);
  const [future, setFuture] = useState<Array<{ nodes: Node[]; edges: Edge[] }>>([]);
  const MAX_HISTORY = 50;

  /** Deep-clone via JSON – strips React Flow internal handles safely */
  const cloneSnapshot = useCallback(
    (n: Node[], e: Edge[]) =>
      JSON.parse(JSON.stringify({ nodes: n, edges: e })) as { nodes: Node[]; edges: Edge[] },
    [],
  );

  const pushHistory = useCallback((snapshotNodes: Node[], snapshotEdges: Edge[]) => {
    setPast((prev) => {
      const next = [...prev, cloneSnapshot(snapshotNodes, snapshotEdges)];
      return next.length > MAX_HISTORY ? next.slice(-MAX_HISTORY) : next;
    });
    setFuture([]);
  }, [cloneSnapshot]);

  const undo = useCallback(() => {
    if (past.length === 0) return;
    const snapshot = past[past.length - 1]!;

    // Push current state → future (read from refs, always up-to-date)
    setFuture((f) => [...f, cloneSnapshot(nodesRef.current, edgesRef.current)]);
    // Pop last entry from past
    setPast((p) => p.slice(0, -1));
    // Restore snapshot
    setNodes(snapshot.nodes);
    setEdges(snapshot.edges);
    setIsDirty(true);
  }, [past, cloneSnapshot, setNodes, setEdges]);

  const redo = useCallback(() => {
    if (future.length === 0) return;
    const snapshot = future[future.length - 1]!;

    // Push current state → past
    setPast((p) => [...p, cloneSnapshot(nodesRef.current, edgesRef.current)]);
    // Pop last entry from future
    setFuture((f) => f.slice(0, -1));
    // Restore snapshot
    setNodes(snapshot.nodes);
    setEdges(snapshot.edges);
    setIsDirty(true);
  }, [future, cloneSnapshot, setNodes, setEdges]);

  // ── Wrapped onNodesChange – push history on drag stop ────────────
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const hasDragStop = changes.some(
        (c) => c.type === "position" && "dragging" in c && c.dragging === false,
      );
      if (hasDragStop) {
        pushHistory(nodes, edges);
      }
      onNodesChangeInternal(changes);
    },
    [nodes, edges, pushHistory, onNodesChangeInternal],
  );

  // ── Wrapped onEdgesChange ────────────────────────────────────────
  const onEdgesChange = useCallback(
    (changes: Parameters<typeof onEdgesChangeInternal>[0]) => {
      pushHistory(nodes, edges);
      onEdgesChangeInternal(changes);
    },
    [nodes, edges, pushHistory, onEdgesChangeInternal],
  );

  // ── Data fetching (edit mode) ────────────────────────────────────
  const workflowQuery = useQuery({
    queryKey: ["workflow", id],
    queryFn: () => apiClient.get<Workflow>(`/workflows/${id}`),
    enabled: !!id,
  });

  // Hydrate local state when workflow data loads
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    if (workflowQuery.data && !hydrated) {
      const w = workflowQuery.data;
      setName(w.name);
      setWorkflowType(w.workflow_type);
      setDescription(w.description);
      const rawGraph = w.graph ?? { nodes: [], edges: [] };
      const graph: AppGraph = isValidWorkflowGraph(rawGraph)
        ? rawGraph
        : { nodes: [], edges: [] };
      const { nodes: rfNodes, edges: rfEdges } = toReactFlow(graph);
      setNodes(rfNodes);
      setEdges(rfEdges);
      setHydrated(true);
    }
  }, [workflowQuery.data, hydrated, setNodes, setEdges]);

  // ── Reset hydrated state when workflow id changes ─────────────────
  const prevIdRef = useRef(id);
  const isInitialRender = useRef(true);
  useEffect(() => {
    if (prevIdRef.current !== id) {
      prevIdRef.current = id;
      setHydrated(false);
      setIsDirty(false);
      isInitialRender.current = true;
      setPast([]);
      setFuture([]);
      setNodes([]);
      setEdges([]);
    }
  }, [id, setNodes, setEdges]);

  // ── Save mutation ────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: async () => {
      const graph = toAppGraph(nodes, edges);
      const body = {
        name: name.trim() || "未命名工作流",
        description: description.trim(),
        workflow_type: workflowType,
        graph,
      };
      if (id) {
        return apiClient.put<Workflow>(`/workflows/${id}`, body);
      }
      return apiClient.post<Workflow>("/workflows/", body);
    },
    onSuccess: (data) => {
      setIsDirty(false);
      void qc.invalidateQueries({ queryKey: ["workflow", id] });
      void qc.invalidateQueries({ queryKey: ["workflows", "list"] });
      // If new workflow, switch to edit mode
      if (isNew && data?.id) {
        navigate(`/workflows/${data.id}/edit`, { replace: true });
      }
    },
    onError: () => {
      // error handled by UI
    },
  });

  const saveMutationRef = useRef(saveMutation);
  saveMutationRef.current = saveMutation;

  const handleSave = useCallback(async () => {
    if (viewMode === "json") {
      // Validate JSON before saving
      try {
        const parsed = JSON.parse(jsonText);
        if (!isValidWorkflowGraph(parsed)) {
          setJsonError("JSON 格式不正确，需要包含 nodes 和 edges 数组");
          return;
        }
        const { nodes: rfNodes, edges: rfEdges } = toReactFlow(parsed);
        setNodes(rfNodes);
        setEdges(rfEdges);
        setJsonError(null);
      } catch {
        setJsonError("JSON 格式错误，无法保存");
        return;
      }
    }
    saveMutationRef.current.mutate();
  }, [viewMode, jsonText, setNodes, setEdges]);

  // ── Track dirty state ──────────────────────────────────────────────
  useEffect(() => {
    if (isInitialRender.current) {
      isInitialRender.current = false;
      return;
    }
    if (hydrated) {
      setIsDirty(true);
    }
  }, [nodes, edges, hydrated]);

  // ── Auto-save (2s debounce) ────────────────────────────────────────
  useEffect(() => {
    if (!isDirty) return;

    const timer = setTimeout(() => {
      if (id) {
        // Edit mode: direct PUT update
        handleSave();
      } else if (nodes.length > 0 || edges.length > 0) {
        // New mode: auto-create when there's content
        handleSave(); // handleSave internally handles POST + navigate
      }
    }, 2000);

    return () => clearTimeout(timer);
  }, [isDirty, id, nodes, edges, handleSave]);

  // ── Warn on browser close/refresh ──────────────────────────────────
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  // ── Delete selected (multi-select aware) ───────────────────────────
  const deleteSelected = useCallback(() => {
    const selectedNodes = nodes.filter((n) => n.selected);
    const selectedEdges = edges.filter((e) => e.selected);
    if (selectedNodes.length === 0 && selectedEdges.length === 0) return;

    pushHistory(nodes, edges);
    const selectedNodeIds = new Set(selectedNodes.map((n) => n.id));
    setNodes((nds) => nds.filter((n) => !n.selected));
    setEdges(
      (eds) =>
        eds.filter(
          (e) =>
            !e.selected &&
            !selectedNodeIds.has(e.source) &&
            !selectedNodeIds.has(e.target),
        ),
    );
    setSelectedNodeId(null);
    setIsDirty(true);
  }, [nodes, edges, setNodes, setEdges, pushHistory]);

  // ── Select all ─────────────────────────────────────────────────────
  const selectAll = useCallback(() => {
    setNodes((nds) => nds.map((n) => ({ ...n, selected: true })));
    setEdges((eds) => eds.map((e) => ({ ...e, selected: true })));
  }, [setNodes, setEdges]);

  // ── Duplicate selected ─────────────────────────────────────────────
  const duplicateSelected = useCallback(() => {
    const selectedNodes = nodes.filter((n) => n.selected);
    if (selectedNodes.length === 0) return;

    pushHistory(nodes, edges);
    const newNodes: Node[] = [];

    selectedNodes.forEach((n) => {
      const newId = generateNodeId();
      newNodes.push({
        ...n,
        id: newId,
        position: { x: n.position.x + 50, y: n.position.y + 50 },
        selected: true,
        data: { ...n.data },
      });
    });

    setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), ...newNodes]);
    setIsDirty(true);
  }, [nodes, edges, setNodes, pushHistory]);

  // ── Auto-layout ───────────────────────────────────────────────────
  const applyAutoLayout = useCallback(() => {
    if (nodes.length === 0) return;
    pushHistory(nodes, edges);
    const appGraph = toAppGraph(nodes, edges);
    const positioned = autoLayout(appGraph.nodes, appGraph.edges);
    const posMap = new Map(positioned.map((p) => [p.id, { x: p.x, y: p.y }]));
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        position: posMap.get(n.id) ?? n.position,
      })),
    );
    setIsDirty(true);
  }, [nodes, edges, setNodes, pushHistory]);

  // ── Workflow execution ────────────────────────────────────────────
  const [isRunning, setIsRunning] = useState(false);
  const [executionLogs, setExecutionLogs] = useState<Array<{ level: "info" | "success" | "error"; message: string; time: string }>>([]);
  const [activeExecutionNodeId, setActiveExecutionNodeId] = useState<string | null>(null);
  const executionAbortRef = useRef(false);

  const stopExecution = useCallback(() => {
    executionAbortRef.current = true;
  }, []);

  const runWorkflow = useCallback(async () => {
    if (nodes.length === 0) return;
    executionAbortRef.current = false;
    setIsRunning(true);
    setExecutionLogs([]);
    setActiveExecutionNodeId(null);

    const log = (level: "info" | "success" | "error", message: string) => {
      const time = new Date().toLocaleTimeString();
      setExecutionLogs((prev) => [...prev, { level, message, time }]);
    };

    // Build adjacency from edges
    const nodeIds = new Set(nodes.map((n) => n.id));
    const successors = new Map<string, string[]>();
    const inDegree = new Map<string, number>();
    for (const n of nodes) {
      successors.set(n.id, []);
      inDegree.set(n.id, 0);
    }
    for (const e of edges) {
      if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
        successors.get(e.source)!.push(e.target);
        inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
      }
    }

    // Topological order (Kahn's)
    const queue: string[] = [];
    for (const [id, deg] of inDegree) {
      if (deg === 0) queue.push(id);
    }

    const topoOrder: string[] = [];
    while (queue.length > 0) {
      const id = queue.shift()!;
      topoOrder.push(id);
      for (const succ of successors.get(id) ?? []) {
        inDegree.set(succ, (inDegree.get(succ) ?? 1) - 1);
        if ((inDegree.get(succ) ?? 0) === 0) queue.push(succ);
      }
    }

    if (topoOrder.length < nodes.length) {
      log("error", "检测到循环依赖，无法执行");
      setIsRunning(false);
      return;
    }

    log("info", `开始执行工作流（${topoOrder.length} 个节点）`);

    for (const nodeId of topoOrder) {
      if (executionAbortRef.current) {
        log("error", "执行已中止");
        break;
      }
      const node = nodes.find((n) => n.id === nodeId);
      if (!node) continue;
      setActiveExecutionNodeId(nodeId);
      const name = String(node.data?.name ?? nodeId);
      log("info", `▶ 执行节点: ${name}`);
      // 节点动画间隔（真实结果由后端执行）
      await new Promise((r) => setTimeout(r, 600));
      if (executionAbortRef.current) break;
      log("success", `✓ 完成: ${name}`);
    }

    setActiveExecutionNodeId(null);
    if (!executionAbortRef.current) {
      log("info", "工作流执行完毕");
    }
    setIsRunning(false);
  }, [nodes, edges]);

  const clearExecutionLogs = useCallback(() => {
    setExecutionLogs([]);
  }, []);

  // ── Execution state on nodes (visual feedback) ────────────────────
  const nodesWithExecutionState = useMemo(() => {
    if (!isRunning) return nodes;
    return nodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        executionActive: n.id === activeExecutionNodeId,
      },
    }));
  }, [nodes, isRunning, activeExecutionNodeId]);

  // ── Unified keyboard shortcuts ─────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isCtrl = e.ctrlKey || e.metaKey;
      const target = e.target as HTMLElement;

      // If inside input/textarea, only handle Ctrl+S
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
        if (isCtrl && e.key === "s") {
          e.preventDefault();
          handleSave();
        }
        return;
      }

      if (isCtrl && e.key === "s") {
        e.preventDefault();
        handleSave();
      } else if (isCtrl && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((isCtrl && e.key === "z" && e.shiftKey) || (isCtrl && e.key === "y")) {
        e.preventDefault();
        redo();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        deleteSelected();
      } else if (isCtrl && e.key === "a") {
        e.preventDefault();
        selectAll();
      } else if (isCtrl && e.key === "d") {
        e.preventDefault();
        duplicateSelected();
      } else if (e.key === "Escape") {
        setNodes((nds) => nds.map((n) => ({ ...n, selected: false })));
        setEdges((eds) => eds.map((ed) => ({ ...ed, selected: false })));
        setSelectedNodeId(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleSave, undo, redo, deleteSelected, selectAll, duplicateSelected, setNodes, setEdges]);

  // ── Node connection with validation ──────────────────────────────
  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;

      // Prevent self-loops
      if (connection.source === connection.target) return;

      // Prevent duplicate edges
      const exists = edges.some(
        (e) => e.source === connection.source && e.target === connection.target,
      );
      if (exists) return;

      pushHistory(nodes, edges);
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            type: "smoothstep",
            style: { strokeWidth: 2 },
            markerEnd: { type: MarkerType.ArrowClosed },
          },
          eds,
        ),
      );
      setIsDirty(true);
    },
    [setEdges, nodes, edges, pushHistory],
  );

  // ── Selection handling ───────────────────────────────────────────
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // ── Add node (click fallback) ────────────────────────────────────
  const addNode = useCallback(
    (type: "skill" | "prompt" | "agent") => {
      pushHistory(nodes, edges);
      const newNodeId = generateNodeId();
      const labels: Record<string, string> = {
        skill: "新技能",
        prompt: "新提示词",
        agent: "新 Agent",
      };
      const newNode: Node = {
        id: newNodeId,
        type,
        position: { x: 200 + Math.random() * 100, y: 200 + Math.random() * 100 },
        data: {
          name: labels[type] ?? "新节点",
          nodeType: type,
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setSelectedNodeId(newNodeId);
    },
    [setNodes, nodes, edges, pushHistory],
  );

  // ── Delete selected node (side-panel single delete) ──────────────
  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    pushHistory(nodes, edges);
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) => eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId));
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges, nodes, edges, pushHistory]);

  // ── Update selected node data (generic) ──────────────────────────
  const updateSelectedNodeData = useCallback(
    (patch: Record<string, unknown>) => {
      if (!selectedNodeId) return;
      pushHistory(nodes, edges);
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n,
        ),
      );
    },
    [selectedNodeId, setNodes, nodes, edges, pushHistory],
  );

  // ── Selected node data ───────────────────────────────────────────
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  // ── JSON mode sync ───────────────────────────────────────────────
  const switchToJson = useCallback(() => {
    const graph = toAppGraph(nodes, edges);
    setJsonText(JSON.stringify(graph, null, 2));
    setJsonError(null);
    setViewMode("json");
  }, [nodes, edges]);

  const switchToCanvas = useCallback(() => {
    if (jsonError) return;
    try {
      const parsed = JSON.parse(jsonText);
      if (!isValidWorkflowGraph(parsed)) {
        setJsonError("JSON 格式不正确，需要包含 nodes 和 edges 数组");
        return;
      }
      const { nodes: rfNodes, edges: rfEdges } = toReactFlow(parsed);
      setNodes(rfNodes);
      setEdges(rfEdges);
      setJsonError(null);
      setViewMode("canvas");
    } catch {
      setJsonError("JSON 格式错误，请修正后再切换回画布");
    }
  }, [jsonText, jsonError, setNodes, setEdges]);

  // ── Loading state ────────────────────────────────────────────────
  if (!isNew && workflowQuery.isPending) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!isNew && workflowQuery.isError) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-background">
        <p className="text-sm text-danger">加载工作流失败</p>
        <Button variant="outline" onClick={() => navigate("/workflows")}>
          <ArrowLeft className="h-4 w-4" />
          返回
        </Button>
      </div>
    );
  }

  // ── Save status text ─────────────────────────────────────────────
  const saveStatusText = saveMutation.isPending
    ? "保存中…"
    : isDirty
      ? "未保存更改"
      : "已保存";
  const saveStatusColor = saveMutation.isPending
    ? "text-muted-foreground"
    : isDirty
      ? "text-amber-500"
      : "text-emerald-500";

  return (
    <ReactFlowProvider>
      <CanvasEditorInner
        name={name}
        setName={setName}
        workflowType={workflowType}
        setWorkflowType={setWorkflowType}
        description={description}
        setDescription={setDescription}
        viewMode={viewMode}
        jsonText={jsonText}
        setJsonText={setJsonText}
        jsonError={jsonError}
        setJsonError={setJsonError}
        nodes={nodes}
        edges={edges}
        displayNodes={nodesWithExecutionState}
        setNodes={setNodes}
        setEdges={setEdges}
        selectedNodeId={selectedNodeId}
        setSelectedNodeId={setSelectedNodeId}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        selectedNode={selectedNode}
        past={past}
        future={future}
        undo={undo}
        redo={redo}
        pushHistory={pushHistory}
        handleSave={handleSave}
        saveMutation={saveMutation}
        addNode={addNode}
        deleteSelectedNode={deleteSelectedNode}
        updateSelectedNodeData={updateSelectedNodeData}
        applyAutoLayout={applyAutoLayout}
        isRunning={isRunning}
        runWorkflow={runWorkflow}
        stopExecution={stopExecution}
        executionLogs={executionLogs}
        clearExecutionLogs={clearExecutionLogs}
        switchToJson={switchToJson}
        switchToCanvas={switchToCanvas}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        saveStatusText={saveStatusText}
        saveStatusColor={saveStatusColor}
      />
    </ReactFlowProvider>
  );
}

/* ──────────────────────────────────────────────────────────────────────
   Inner component – has access to useReactFlow()
   ────────────────────────────────────────────────────────────────────── */
interface CanvasEditorInnerProps {
  name: string;
  setName: (v: string) => void;
  workflowType: string;
  setWorkflowType: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  viewMode: ViewMode;
  jsonText: string;
  setJsonText: (v: string) => void;
  jsonError: string | null;
  setJsonError: (v: string | null) => void;
  nodes: Node[];
  edges: Edge[];
  displayNodes: Node[];
  setNodes: ReturnType<typeof useNodesState<Node>>[1];
  setEdges: ReturnType<typeof useEdgesState<Edge>>[1];
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: Parameters<ReturnType<typeof useEdgesState<Edge>>[2]>[0]) => void;
  selectedNode: Node | null;
  past: Array<{ nodes: Node[]; edges: Edge[] }>;
  future: Array<{ nodes: Node[]; edges: Edge[] }>;
  undo: () => void;
  redo: () => void;
  pushHistory: (n: Node[], e: Edge[]) => void;
  handleSave: () => Promise<void>;
  saveMutation: { isPending: boolean; isError: boolean };
  addNode: (type: "skill" | "prompt" | "agent") => void;
  deleteSelectedNode: () => void;
  updateSelectedNodeData: (patch: Record<string, unknown>) => void;
  applyAutoLayout: () => void;
  isRunning: boolean;
  runWorkflow: () => void;
  stopExecution: () => void;
  executionLogs: Array<{ level: "info" | "success" | "error"; message: string; time: string }>;
  clearExecutionLogs: () => void;
  switchToJson: () => void;
  switchToCanvas: () => void;
  onConnect: (connection: Connection) => void;
  onNodeClick: (_: React.MouseEvent, node: Node) => void;
  onPaneClick: () => void;
  saveStatusText: string;
  saveStatusColor: string;
}

function CanvasEditorInner({
  name,
  setName,
  workflowType,
  setWorkflowType,
  description: _description,
  setDescription: _setDescription,
  viewMode,
  jsonText,
  setJsonText,
  jsonError,
  setJsonError,
  nodes,
  edges,
  displayNodes,
  setNodes,
  setEdges,
  selectedNodeId,
  setSelectedNodeId,
  onNodesChange,
  onEdgesChange,
  selectedNode,
  past,
  future,
  undo,
  redo,
  pushHistory,
  handleSave,
  saveMutation,
  addNode,
  deleteSelectedNode,
  updateSelectedNodeData,
  applyAutoLayout,
  isRunning,
  runWorkflow,
  stopExecution,
  executionLogs,
  clearExecutionLogs,
  switchToJson,
  switchToCanvas,
  onConnect,
  onNodeClick,
  onPaneClick,
  saveStatusText,
  saveStatusColor,
}: CanvasEditorInnerProps) {
  const { screenToFlowPosition, fitView } = useReactFlow();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // ── Auto-fit view after initial node load ────────────────────────
  const didInitialFit = useRef(false);
  useEffect(() => {
    if (nodes.length > 0 && !didInitialFit.current) {
      didInitialFit.current = true;
      requestAnimationFrame(() => {
        fitView({ padding: 0.2, duration: 200 });
      });
    }
  }, [nodes.length, fitView]);

  // Reset flag when nodes become empty (e.g. workflow switch)
  useEffect(() => {
    if (nodes.length === 0) {
      didInitialFit.current = false;
    }
  }, [nodes.length]);

  // ── Responsive sidebar collapse ──────────────────────────────────
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    const check = () => setSidebarCollapsed(window.innerWidth < 1024);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  // ── Node search ──────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState("");

  const searchResults = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];
    return nodes.filter((n) => {
      const name = String(n.data?.name ?? "").toLowerCase();
      return name.includes(q);
    });
  }, [searchQuery, nodes]);

  const focusNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.map((n) => ({ ...n, selected: n.id === nodeId })));
      setSelectedNodeId(nodeId);
      fitView({ padding: 0.3, duration: 300, nodes: [{ id: nodeId }] as Node[] });
      setSearchQuery("");
    },
    [setNodes, setSelectedNodeId, fitView],
  );

  // ── Context menu ─────────────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    type: "canvas" | "node";
    nodeId?: string;
  } | null>(null);

  const onPaneContextMenu = useCallback(
    (e: React.MouseEvent | MouseEvent) => {
      e.preventDefault();
      setContextMenu({ x: (e as React.MouseEvent).clientX ?? (e as MouseEvent).clientX, y: (e as React.MouseEvent).clientY ?? (e as MouseEvent).clientY, type: "canvas" });
    },
    [],
  );

  const onNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: Node) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, type: "node", nodeId: node.id });
    },
    [],
  );

  // Close context menu on any click
  useEffect(() => {
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  // Context menu actions
  const ctxEditNode = useCallback(() => {
    if (!contextMenu?.nodeId) return;
    setSelectedNodeId(contextMenu.nodeId);
    setSidebarCollapsed(false);
    setContextMenu(null);
  }, [contextMenu, setSelectedNodeId, setSidebarCollapsed]);

  const ctxCopyNode = useCallback(() => {
    if (!contextMenu?.nodeId) return;
    const src = nodes.find((n) => n.id === contextMenu.nodeId);
    if (!src) return;
    pushHistory(nodes, edges);
    const newId = generateNodeId();
    const newNode: Node = {
      ...src,
      id: newId,
      position: { x: src.position.x + 50, y: src.position.y + 50 },
      data: { ...src.data },
    };
    setNodes((nds) => [...nds, newNode]);
    setContextMenu(null);
  }, [contextMenu, nodes, edges, setNodes, pushHistory]);

  const ctxDeleteNode = useCallback(() => {
    if (!contextMenu?.nodeId) return;
    const targetId = contextMenu.nodeId;
    pushHistory(nodes, edges);
    setNodes((nds) => nds.filter((n) => n.id !== targetId));
    setEdges((eds) => eds.filter((e) => e.source !== targetId && e.target !== targetId));
    if (selectedNodeId === targetId) setSelectedNodeId(null);
    setContextMenu(null);
  }, [contextMenu, nodes, edges, setNodes, setEdges, pushHistory, selectedNodeId, setSelectedNodeId]);

  // ── Drag & Drop handlers ─────────────────────────────────────────
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData("application/workflow-node-type");
      if (!nodeType) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      pushHistory(nodes, edges);

      const labels: Record<string, string> = {
        skill: "新技能",
        prompt: "新提示词",
        agent: "新 Agent",
      };

      const newNode: Node = {
        id: generateNodeId(),
        type: nodeType,
        position,
        data: {
          name: labels[nodeType] ?? "新节点",
          nodeType,
        },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [screenToFlowPosition, pushHistory, nodes, edges, setNodes],
  );

  return (
    <div className="flex h-dvh flex-col bg-background">
      {/* ── TopBar ─────────────────────────────────────────── */}
      <header className="flex h-12 flex-none items-center gap-3 border-b border-border bg-surface-raised px-3">
        {/* Left: back + name */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate("/workflows")}
          title="返回工作流列表"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 max-w-[200px] rounded-md border border-transparent bg-transparent px-2 text-sm font-semibold text-foreground outline-none hover:border-border focus:border-primary"
          placeholder="工作流名称"
        />

        {/* Center: workflow type */}
        <div className="mx-auto flex items-center gap-2">
          <select
            value={workflowType}
            onChange={(e) => setWorkflowType(e.target.value)}
            className="h-8 cursor-pointer rounded-md border border-border bg-surface px-2 pr-6 text-xs text-foreground outline-none transition-colors hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
          >
            <option value="sequential">Sequential</option>
            <option value="parallel">Parallel</option>
          </select>
        </div>

        {/* Right: undo/redo + JSON toggle + save */}
        <div className="flex items-center gap-2">
          {/* Undo / Redo buttons */}
          <div className="flex items-center gap-0.5">
            <button
              onClick={undo}
              disabled={past.length === 0}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground transition-colors hover:bg-surface disabled:opacity-30 disabled:pointer-events-none"
              
             aria-label="撤销 (Ctrl+Z)">
              <Undo2 className="h-4 w-4" />
            </button>
            <button
              onClick={redo}
              disabled={future.length === 0}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground transition-colors hover:bg-surface disabled:opacity-30 disabled:pointer-events-none"
              
             aria-label="重做 (Ctrl+Shift+Z)">
              <Redo2 className="h-4 w-4" />
            </button>
          </div>

          {/* Fit view button */}
          <button
            onClick={() => fitView({ padding: 0.2 })}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground transition-colors hover:bg-surface"
            title="适应画布"
          >
            <Maximize2 className="h-4 w-4" />
          </button>

          {/* Auto-layout button */}
          <button
            onClick={applyAutoLayout}
            disabled={nodes.length === 0}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground transition-colors hover:bg-surface disabled:opacity-30 disabled:pointer-events-none"
            
           aria-label="自动布局">
            <LayoutGrid className="h-4 w-4" />
          </button>

          {/* Run / Stop button */}
          {isRunning ? (
            <Button variant="danger" size="sm" onClick={stopExecution}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={runWorkflow}
              disabled={nodes.length === 0}
            >
              <Play className="h-4 w-4" />
              运行
            </Button>
          )}

          <Button
            variant={viewMode === "json" ? "primary" : "outline"}
            size="sm"
            onClick={() => (viewMode === "canvas" ? switchToJson() : switchToCanvas())}
          >
            <Code2 className="h-4 w-4" />
            {viewMode === "json" ? "画布模式" : "JSON 模式"}
          </Button>

          <Button size="sm" onClick={handleSave} loading={saveMutation.isPending}>
            <Save className="h-4 w-4" />
            保存
          </Button>

          {/* Save status indicator */}
          <span className={`text-xs ${saveStatusColor}`}>{saveStatusText}</span>
        </div>
      </header>

      {/* ── Main area ──────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Canvas + Side Panel row */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Canvas / JSON area */}
        <div ref={reactFlowWrapper} className="relative flex-1">
          {viewMode === "canvas" ? (
            <>
              <ReactFlow
                nodes={displayNodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                onPaneClick={onPaneClick}
                onPaneContextMenu={onPaneContextMenu}
                onNodeContextMenu={onNodeContextMenu}
                onDragOver={onDragOver}
                onDrop={onDrop}
                snapToGrid={true}
                snapGrid={[20, 20]}
                minZoom={0.3}
                maxZoom={2}
                selectionKeyCode="Shift"
                multiSelectionKeyCode="Control"
                deleteKeyCode={null}
                onlyRenderVisibleElements={true}
                fitView
                className="bg-background"
              >
                <Background />
                <Controls />
                <MiniMap />
              </ReactFlow>

              {/* Empty state guide */}
              {nodes.length === 0 && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="space-y-2 text-center">
                    <GitBranch className="mx-auto h-12 w-12 text-muted-foreground/50" />
                    <p className="text-sm text-muted-foreground">
                      从右侧面板拖拽节点到画布
                      <br />
                      或点击添加按钮创建第一个节点
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex h-full flex-col">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                <span className="text-xs font-medium text-muted-foreground">
                  Graph JSON
                </span>
                {jsonError && (
                  <span className="text-xs text-danger">{jsonError}</span>
                )}
              </div>
              <textarea
                value={jsonText}
                onChange={(e) => {
                  setJsonText(e.target.value);
                  setJsonError(null);
                }}
                className="flex-1 resize-none bg-surface p-4 font-mono text-xs text-foreground outline-none"
                spellCheck={false}
              />
            </div>
          )}
        </div>

        {/* ── Side Panel ───────────────────────────────────── */}
        <aside
          className={`flex flex-none flex-col border-l border-border bg-surface-raised transition-all duration-200 ${
            sidebarCollapsed ? "w-12" : "w-80"
          }`}
        >
          {/* Collapse toggle */}
          <button
            onClick={() => setSidebarCollapsed((v) => !v)}
            className="flex h-9 items-center justify-center border-b border-border text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            title={sidebarCollapsed ? "展开面板" : "折叠面板"}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>

          {sidebarCollapsed ? (
            /* ── Collapsed: icon-only strip ── */
            <div className="flex flex-1 flex-col items-center gap-2 pt-2">
              <button
                onClick={() => addNode("skill")}
                className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
                title="添加 Skill 节点"
              >
                <Sparkles className="h-4 w-4" />
              </button>
              <button
                onClick={() => addNode("prompt")}
                className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
                title="添加 Prompt 节点"
              >
                <MessageSquare className="h-4 w-4" />
              </button>
              <button
                onClick={() => addNode("agent")}
                className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
                title="添加 Agent 节点"
              >
                <Bot className="h-4 w-4" />
              </button>
            </div>
          ) : (
            /* ── Expanded: full panel ── */
            <>
              {/* Node search */}
              <div className="border-b border-border px-3 py-2">
                <div className="flex items-center gap-2 rounded-md border border-border bg-surface px-2 py-1">
                  <Search className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="搜索节点…"
                    className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
                  />
                </div>
                {searchQuery && (
                  <div className="mt-1 max-h-32 overflow-y-auto">
                    {searchResults.length === 0 ? (
                      <p className="px-1 py-0.5 text-[10px] text-muted-foreground">无匹配节点</p>
                    ) : (
                      searchResults.map((n) => (
                        <button
                          key={n.id}
                          onClick={() => focusNode(n.id)}
                          className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs text-foreground transition-colors hover:bg-surface"
                        >
                          {n.type === "skill" && <Sparkles className="h-3 w-3 flex-none" />}
                          {n.type === "prompt" && <MessageSquare className="h-3 w-3 flex-none" />}
                          {n.type === "agent" && <Bot className="h-3 w-3 flex-none" />}
                          <span className="truncate">{String(n.data?.name ?? n.id)}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>

              {/* Add nodes section – draggable items */}
              <NodePalette onAddNode={addNode} />

              {/* Selected node properties */}
              <div className="flex-1 overflow-y-auto p-3">
                {selectedNode ? (
                  <div className="space-y-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      节点属性
                    </p>

                    {/* ── 通用：名称 ── */}
                    <div>
                      <label className="mb-1 block text-xs text-muted-foreground">名称</label>
                      <Input
                        value={String(selectedNode.data?.name ?? "")}
                        onChange={(e) => updateSelectedNodeData({ name: e.target.value })}
                        className="h-8 rounded-md text-sm"
                      />
                    </div>

                    {/* ── 通用：类型 ── */}
                    <div>
                      <label className="mb-1 block text-xs text-muted-foreground">类型</label>
                      <div className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-muted-foreground">
                        {String(selectedNode.data?.nodeType ?? selectedNode.type ?? "unknown")}
                      </div>
                    </div>

                    {/* ── 通用：ID ── */}
                    <div>
                      <label className="mb-1 block text-xs text-muted-foreground">ID</label>
                      <div className="rounded-md border border-border bg-surface px-2 py-1.5 font-mono text-xs text-muted-foreground">
                        {selectedNode.id}
                      </div>
                    </div>

                    {/* ── Skill 节点专属 ── */}
                    {selectedNode.data?.nodeType === "skill" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">技能类型</label>
                          <select
                            value={String(selectedNode.data?.skillType ?? "")}
                            onChange={(e) => updateSelectedNodeData({ skillType: e.target.value })}
                            className="h-8 w-full cursor-pointer rounded-md border border-border bg-surface px-2 pr-6 text-sm text-foreground outline-none transition-colors hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
                          >
                            <option value="">选择技能…</option>
                            <option value="image-gen">图片生成</option>
                            <option value="text-process">文本处理</option>
                            <option value="data-analysis">数据分析</option>
                            <option value="code-exec">代码执行</option>
                            <option value="image-edit">图像编辑</option>
                          </select>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            参数（JSON）
                          </label>
                          <textarea
                            value={
                              selectedNode.data?.params
                                ? JSON.stringify(selectedNode.data.params, null, 2)
                                : ""
                            }
                            onChange={(e) => {
                              try {
                                const parsed = e.target.value ? JSON.parse(e.target.value) : {};
                                updateSelectedNodeData({ params: parsed });
                              } catch {
                                // ignore invalid JSON while typing
                              }
                            }}
                            rows={3}
                            className="w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 font-mono text-xs text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
                            placeholder='{"key": "value"}'
                          />
                        </div>
                      </>
                    )}

                    {/* ── Prompt 节点专属 ── */}
                    {selectedNode.data?.nodeType === "prompt" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            Prompt 内容
                          </label>
                          <textarea
                            value={String(selectedNode.data?.promptContent ?? "")}
                            onChange={(e) => updateSelectedNodeData({ promptContent: e.target.value })}
                            rows={7}
                            className="w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 font-mono text-xs text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
                            placeholder="输入 Prompt 内容…"
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">模型</label>
                          <select
                            value={String(selectedNode.data?.model ?? "")}
                            onChange={(e) => updateSelectedNodeData({ model: e.target.value })}
                            className="h-8 w-full cursor-pointer rounded-md border border-border bg-surface px-2 pr-6 text-sm text-foreground outline-none transition-colors hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
                          >
                            <option value="">选择模型…</option>
                            <option value="gpt-4o">GPT-4o</option>
                            <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                            <option value="gemini-pro">Gemini Pro</option>
                          </select>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            Temperature
                          </label>
                          <input
                            type="number"
                            min={0}
                            max={2}
                            step={0.1}
                            value={Number(selectedNode.data?.temperature ?? 0.7)}
                            onChange={(e) =>
                              updateSelectedNodeData({ temperature: parseFloat(e.target.value) || 0 })
                            }
                            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-sm text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
                          />
                        </div>
                      </>
                    )}

                    {/* ── Agent 节点专属 ── */}
                    {selectedNode.data?.nodeType === "agent" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">模型</label>
                          <select
                            value={String(selectedNode.data?.model ?? "")}
                            onChange={(e) => updateSelectedNodeData({ model: e.target.value })}
                            className="h-8 w-full cursor-pointer rounded-md border border-border bg-surface px-2 pr-6 text-sm text-foreground outline-none transition-colors hover:border-primary/50 focus:border-primary focus:ring-1 focus:ring-primary"
                          >
                            <option value="">选择模型…</option>
                            <option value="gpt-4o">GPT-4o</option>
                            <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                            <option value="gemini-pro">Gemini Pro</option>
                          </select>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            系统提示词
                          </label>
                          <textarea
                            value={String(selectedNode.data?.systemPrompt ?? "")}
                            onChange={(e) => updateSelectedNodeData({ systemPrompt: e.target.value })}
                            rows={4}
                            className="w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 font-mono text-xs text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
                            placeholder="输入系统提示词…"
                          />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            Temperature
                          </label>
                          <input
                            type="number"
                            min={0}
                            max={2}
                            step={0.1}
                            value={Number(selectedNode.data?.temperature ?? 0.7)}
                            onChange={(e) =>
                              updateSelectedNodeData({ temperature: parseFloat(e.target.value) || 0 })
                            }
                            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-sm text-foreground outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
                          />
                        </div>
                      </>
                    )}

                    <Button
                      variant="danger"
                      size="sm"
                      className="w-full"
                      onClick={deleteSelectedNode}
                    >
                      <Trash2 className="h-4 w-4" />
                      删除节点
                    </Button>
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center">
                    <p className="text-center text-xs text-muted-foreground">
                      选择一个节点来编辑属性
                    </p>
                  </div>
                )}
              </div>
            </>
          )}
        </aside>
      </div>

      {/* ── Execution Log Panel ──────────────────────────── */}
      {(isRunning || executionLogs.length > 0) && (
        <div className="flex h-40 flex-none flex-col border-t border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <div className="flex items-center gap-2">
              <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground">
                执行日志
              </span>
              {isRunning && (
                <span className="flex items-center gap-1 text-[10px] text-amber-500">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  运行中…
                </span>
              )}
            </div>
            <button
              onClick={clearExecutionLogs}
              className="text-[10px] text-muted-foreground hover:text-foreground"
            >
              清空
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 font-mono text-[11px] space-y-0.5">
            {executionLogs.map((log, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-muted-foreground/60 flex-none">{log.time}</span>
                {log.level === "success" && <CheckCircle2 className="h-3 w-3 flex-none text-emerald-500 mt-0.5" />}
                {log.level === "error" && <XCircle className="h-3 w-3 flex-none text-danger mt-0.5" />}
                {log.level === "info" && <span className="h-3 w-3 flex-none text-muted-foreground/40 mt-0.5">›</span>}
                <span className={
                  log.level === "error" ? "text-danger" :
                  log.level === "success" ? "text-emerald-600 dark:text-emerald-400" :
                  "text-foreground"
                }>
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>{/* ── close main area ── */}

      {/* ── Context Menu ─────────────────────────────────── */}
      {contextMenu && (
        <div
          role="menu"
          aria-label="画布右键菜单"
          className="fixed z-[9999] min-w-[160px] rounded-md border border-border bg-surface-raised py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Escape") setContextMenu(null);
          }}
        >
          {contextMenu.type === "canvas" ? (
            <>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={() => { addNode("skill"); setContextMenu(null); }}
              >
                <Sparkles className="h-3.5 w-3.5" />
                添加 Skill 节点
              </button>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={() => { addNode("prompt"); setContextMenu(null); }}
              >
                <MessageSquare className="h-3.5 w-3.5" />
                添加 Prompt 节点
              </button>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={() => { addNode("agent"); setContextMenu(null); }}
              >
                <Bot className="h-3.5 w-3.5" />
                添加 Agent 节点
              </button>
              <div className="my-1 border-t border-border" />
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={() => { fitView({ padding: 0.2 }); setContextMenu(null); }}
              >
                <Maximize2 className="h-3.5 w-3.5" />
                适应画布
              </button>
            </>
          ) : (
            <>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={ctxEditNode}
              >
                <MousePointerClick className="h-3.5 w-3.5" />
                编辑节点
              </button>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-surface"
                onClick={ctxCopyNode}
              >
                <Copy className="h-3.5 w-3.5" />
                复制节点
              </button>
              <div className="my-1 border-t border-border" />
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-danger transition-colors hover:bg-surface"
                onClick={ctxDeleteNode}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除节点
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
