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
        "rounded-xl border bg-background p-3 shadow-sm min-w-[160px] max-w-[220px] transition-all hover:shadow-md",
        "border-purple-200 dark:border-purple-800",
        selected && "ring-2 ring-purple-500 shadow-lg shadow-purple-500/20",
        Boolean(data.executionActive) && "ring-2 ring-amber-400 shadow-lg shadow-amber-400/30 animate-pulse",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-purple-400"
      />
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-purple-100 dark:bg-purple-900 p-1.5 flex-none">
          <Bot className="h-4 w-4 text-purple-600 dark:text-purple-400" />
        </div>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-sm truncate block">
            {String(data.name)}
          </span>
        </div>
      </div>
      <div className="mt-1.5 space-y-0.5">
        {modelLabel && (
          <div className="text-[11px] font-medium text-purple-600 dark:text-purple-400 truncate">
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
        className="!w-2 !h-2 !bg-purple-400"
      />
    </div>
  );
});

export const AgentNode = AgentNodeInner;
