import { memo, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export type NodeType = "skill" | "prompt" | "agent";

interface DraggableNodeProps {
  type: NodeType;
  label: string;
  icon: ReactNode;
  className?: string;
}

/**
 * A draggable sidebar item that can be dropped onto the ReactFlow canvas
 * to create a new node. Also supports click-to-add as a fallback.
 *
 * Sets `application/workflow-node-type` in dataTransfer so the canvas
 * drop handler can identify the node type.
 */
export const DraggableNode = memo(function DraggableNode({
  type,
  label,
  icon,
  className,
}: DraggableNodeProps) {
  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData("application/workflow-node-type", type);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      className={cn(
        "flex cursor-grab items-center justify-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-surface-hover active:cursor-grabbing",
        className,
      )}
    >
      {icon}
      <span>{label}</span>
    </div>
  );
});
