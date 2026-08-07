/**
 * Workflow Graph Adapter
 * Bidirectional converter between backend AppGraph format and React Flow format.
 */
import { MarkerType, type Node, type Edge } from "@xyflow/react";
import type {
  WorkflowGraphNode,
  WorkflowGraphEdge,
  WorkflowGraph,
} from "@aigc/shared-types";

// ── Backend graph types (re-exported from shared-types) ────────────

export type AppGraphNode = WorkflowGraphNode;
export type AppGraphEdge = WorkflowGraphEdge;
export type AppGraph = WorkflowGraph;

/** Type guard: checks whether a value looks like a valid WorkflowGraph. */
export function isValidWorkflowGraph(value: unknown): value is WorkflowGraph {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  return Array.isArray(obj.nodes) && Array.isArray(obj.edges);
}

// ── React Flow aliases ─────────────────────────────────────────────

type RFNode = Node;
type RFEdge = Edge;

// ── Layout constants ───────────────────────────────────────────────

const H_GAP = 250; // horizontal gap between layers
const V_GAP = 120; // vertical gap between nodes in the same layer
const START_X = 0;
const START_Y = 0;

// ── Auto-layout (longest-path layering) ────────────────────────────

interface PositionedNode {
  id: string;
  x: number;
  y: number;
}

/**
 * Compute a simple topological layered layout.
 *
 * 1. Nodes with in-degree 0 → layer 0
 * 2. Every other node → max(predecessor layers) + 1
 * 3. Layers are placed horizontally; nodes within a layer are stacked vertically.
 */
export function autoLayout(
  nodes: AppGraphNode[],
  edges: AppGraphEdge[],
): PositionedNode[] {
  if (nodes.length === 0) return [];

  const nodeIds = new Set(nodes.map((n) => n.id));

  // Build adjacency & in-degree maps
  const successors = new Map<string, string[]>();
  const predecessors = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  for (const id of nodeIds) {
    successors.set(id, []);
    predecessors.set(id, []);
    inDegree.set(id, 0);
  }

  for (const e of edges) {
    if (!nodeIds.has(e.from) || !nodeIds.has(e.to)) continue;
    successors.get(e.from)!.push(e.to);
    predecessors.get(e.to)!.push(e.from);
    inDegree.set(e.to, inDegree.get(e.to)! + 1);
  }

  // Longest-path layering via topological order (Kahn's algorithm)
  const layer = new Map<string, number>();
  const queue: string[] = [];

  for (const [id, deg] of inDegree) {
    if (deg === 0) {
      queue.push(id);
      layer.set(id, 0);
    }
  }

  // For nodes not reachable from roots, handle after topo sort
  let head = 0;
  while (head < queue.length) {
    const cur = queue[head++];
    if (cur === undefined) continue;
    const curLayer = layer.get(cur) ?? 0;
    const curSuccessors = successors.get(cur);
    if (!curSuccessors) continue;
    for (const succ of curSuccessors) {
      const existing = layer.get(succ);
      const newLayer = curLayer + 1;
      if (existing === undefined || newLayer > existing) {
        layer.set(succ, newLayer);
      }
      const curDeg = inDegree.get(succ) ?? 1;
      inDegree.set(succ, curDeg - 1);
      if (curDeg - 1 === 0) {
        queue.push(succ);
      }
    }
  }

  // Assign layer 0 to any remaining nodes (disconnected / cycles)
  for (const n of nodes) {
    if (!layer.has(n.id)) {
      layer.set(n.id, 0);
    }
  }

  // Group nodes by layer
  const layers = new Map<number, string[]>();
  for (const [id, l] of layer) {
    let bucket = layers.get(l);
    if (!bucket) {
      bucket = [];
      layers.set(l, bucket);
    }
    bucket.push(id);
  }

  // Assign positions
  const posMap = new Map<string, { x: number; y: number }>();
  const sortedLayerKeys = [...layers.keys()].sort((a, b) => a - b);

  for (const l of sortedLayerKeys) {
    const ids = layers.get(l);
    if (!ids) continue;
    const x = START_X + l * H_GAP;
    const totalHeight = (ids.length - 1) * V_GAP;
    const offsetY = START_Y - totalHeight / 2; // centre vertically

    for (let i = 0; i < ids.length; i++) {
      const nodeId = ids[i];
      if (nodeId !== undefined) {
        posMap.set(nodeId, { x, y: offsetY + i * V_GAP });
      }
    }
  }

  return nodes.map((n) => {
    const pos = posMap.get(n.id) ?? { x: START_X, y: START_Y };
    return { id: n.id, x: pos.x, y: pos.y };
  });
}

// ── Converters ─────────────────────────────────────────────────────

/**
 * Convert an AppGraph to React Flow nodes & edges.
 * Nodes with existing position data keep their positions;
 * nodes without positions receive auto-layout positions.
 */
export function toReactFlow(graph: AppGraph): { nodes: RFNode[]; edges: RFEdge[] } {
  const hasPositions = graph.nodes.length > 0 && graph.nodes.every((n) => n.position);

  let posMap: Map<string, { x: number; y: number }>;

  if (hasPositions) {
    posMap = new Map(graph.nodes.map((n) => [n.id, n.position!]));
  } else {
    const positions = autoLayout(graph.nodes, graph.edges);
    posMap = new Map(positions.map((p) => [p.id, { x: p.x, y: p.y }]));
  }

  const rfNodes: RFNode[] = graph.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: posMap.get(node.id) ?? { x: 0, y: 0 },
    data: {
      name: node.name,
      nodeType: node.type,
      ...(node.data ?? {}),
    },
  }));

  const rfEdges: RFEdge[] = graph.edges.map((edge, i) => ({
    id: `${edge.from}-${edge.to}-${i}`,
    source: edge.from,
    target: edge.to,
    type: "smoothstep",
    style: { strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));

  return { nodes: rfNodes, edges: rfEdges };
}

/**
 * Convert React Flow nodes & edges back to the backend AppGraph format.
 * Position data is preserved from the React Flow nodes.
 */
export function toAppGraph(rfNodes: RFNode[], rfEdges: RFEdge[]): AppGraph {
  const nodes: AppGraphNode[] = rfNodes.map((n) => {
    // Extract known fields, rest goes into data
    const { name, nodeType, ...configData } = n.data ?? {};
    return {
      id: n.id,
      type: ((nodeType as AppGraphNode["type"]) ??
        (n.type as AppGraphNode["type"]) ??
        "skill"),
      name: (name as string) ?? "",
      position: { x: n.position.x, y: n.position.y },
      // Preserve node-specific config (model, temperature, promptContent, etc.)
      ...(Object.keys(configData).length > 0 ? { data: configData } : {}),
    };
  });

  const edges: AppGraphEdge[] = rfEdges.map((e) => ({
    from: e.source,
    to: e.target,
  }));

  return { nodes, edges };
}

// ── Helpers ────────────────────────────────────────────────────────

let _counter = 0;

/** Generate a unique node ID. */
export function generateNodeId(): string {
  return `node-${Date.now()}-${++_counter}`;
}

/** Create an empty AppGraph. */
export function createEmptyGraph(): AppGraph {
  return { nodes: [], edges: [] };
}
