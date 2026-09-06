import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Bot } from "lucide-react";
import { cn } from "@/lib/cn";

const MODEL_LABELS: Record<string, string> = {
  "gpt-4o": "GPT-4o",
  "claude-3.5-sonnet": "Claude 3.5",
  "gemini-pro": "Gemini Pro",
};

const AgentNodeInner = memo(function AgentNode({ data, selected }: NodeProps) {
  const model = data.model as string | undefined;
  const modelLabel = model ? MODEL_LABELS[model] ?? model : null;
  const systemPrompt = data.systemPrompt as string | undefined;
  const temperature = data.temperature as number | undefined;

  return (
    <div
      className={cn(
        "rounded-xl border bg-background p-3 shadow-sm min-w-[160px] max-w-[220px] transition-[border-color,box-shadow] hover:shadow-md",
        "border-primary/40",
        selected && "ring-2 ring-primary",
        Boolean(data.executionActive) && "ring-2 ring-primary/70",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-primary"
      />
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-primary/10 p-1.5 flex-none">
          <Bot className="h-4 w-4 text-primary-text" />
        </div>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-sm truncate block">
            {String(data.name)}
          </span>
        </div>
      </div>
      <div className="mt-1.5 space-y-0.5">
        {modelLabel && (
          <div className="text-[11px] font-medium text-primary-text truncate">
            {modelLabel}
          </div>
        )}
        {systemPrompt && (
          <p className="text-[10px] text-muted-foreground line-clamp-2 leading-tight">
            {systemPrompt}
          </p>
        )}
        {!systemPrompt && !modelLabel && (
          <span className="text-[10px] text-muted-foreground">Agent</span>
        )}
        {temperature !== undefined && temperature !== null && (
          <div className="text-[10px] text-muted-foreground/70">
            T={temperature}
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-primary"
      />
    </div>
  );
});

export const AgentNode = AgentNodeInner;
