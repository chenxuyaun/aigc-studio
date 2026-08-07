import { memo } from "react";

import { Bot, MessageSquare, Sparkles } from "lucide-react";

import { DraggableNode } from "./DraggableNode";

interface NodePaletteProps {
  /** Called when a palette item is clicked (fallback for drag). */
  onAddNode?: (type: "skill" | "prompt" | "agent") => void;
}

/**
 * Sidebar palette of draggable node types.
 * Each item can be dragged onto the ReactFlow canvas or clicked to add.
 */
export const NodePalette = memo(function NodePalette({
  onAddNode,
}: NodePaletteProps) {
  const items: { type: "skill" | "prompt" | "agent"; label: string; icon: React.ReactNode }[] = [
    { type: "skill", label: "Skill", icon: <Sparkles className="h-4 w-4" /> },
    { type: "prompt", label: "Prompt", icon: <MessageSquare className="h-4 w-4" /> },
    { type: "agent", label: "Agent", icon: <Bot className="h-4 w-4" /> },
  ];

  return (
    <div className="border-b border-border p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        添加节点
      </p>
      <div className="flex gap-2">
        {items.map((item) => (
          <div
            key={item.type}
            onClick={() => onAddNode?.(item.type)}
            className="flex-1"
          >
            <DraggableNode
              type={item.type}
              label={item.label}
              icon={item.icon}
              className="w-full"
            />
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        拖拽到画布或点击添加
      </p>
    </div>
  );
});
