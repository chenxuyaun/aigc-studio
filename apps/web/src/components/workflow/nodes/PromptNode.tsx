import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { FileText } from "lucide-react";
import { cn } from "@/lib/cn";

const MODEL_LABELS: Record<string, string> = {
  "gpt-4o": "GPT-4o",
  "claude-3.5-sonnet": "Claude 3.5",
  "gemini-pro": "Gemini Pro",
};

const PromptNodeInner = memo(function PromptNode({ data, selected }: NodeProps) {
  const model = data.model as string | undefined;
  const modelLabel = model ? MODEL_LABELS[model] ?? model : null;
  const promptContent = data.promptContent as string | undefined;
  const temperature = data.temperature as number | undefined;

  return (
    <div
      className={cn(
        "rounded-xl border bg-background p-3 shadow-sm min-w-[160px] max-w-[220px] transition-all hover:shadow-md",
        "border-green-200 dark:border-green-800",
        selected && "ring-2 ring-green-500 shadow-lg shadow-green-500/20",
        Boolean(data.executionActive) && "ring-2 ring-amber-400 shadow-lg shadow-amber-400/30 animate-pulse",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-green-400"
      />
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-green-100 dark:bg-green-900 p-1.5 flex-none">
          <FileText className="h-4 w-4 text-green-600 dark:text-green-400" />
        </div>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-sm truncate block">
            {String(data.name)}
          </span>
        </div>
      </div>
      <div className="mt-1.5 space-y-0.5">
        {modelLabel && (
          <div className="text-[11px] font-medium text-green-600 dark:text-green-400 truncate">
            {modelLabel}
          </div>
        )}
        {promptContent && (
          <p className="text-[10px] text-muted-foreground line-clamp-2 leading-tight">
            {promptContent}
          </p>
        )}
        {!promptContent && !modelLabel && (
          <span className="text-[10px] text-muted-foreground">Prompt</span>
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
        className="!w-2 !h-2 !bg-green-400"
      />
    </div>
  );
});

export const PromptNode = PromptNodeInner;
