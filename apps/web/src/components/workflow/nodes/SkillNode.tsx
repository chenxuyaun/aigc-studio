import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Zap } from "lucide-react";
import { cn } from "@/lib/cn";

const SKILL_TYPE_LABELS: Record<string, string> = {
  "image-gen": "图片生成",
  "text-process": "文本处理",
  "data-analysis": "数据分析",
  "code-exec": "代码执行",
  "image-edit": "图像编辑",
};

const SkillNodeInner = memo(function SkillNode({ data, selected }: NodeProps) {
  const skillType = data.skillType as string | undefined;
  const skillLabel = skillType ? SKILL_TYPE_LABELS[skillType] ?? skillType : null;
  const params = data.params as Record<string, unknown> | undefined;
  const hasParams = params && Object.keys(params).length > 0;

  return (
    <div
      className={cn(
        "rounded-xl border bg-background p-3 shadow-sm min-w-[160px] max-w-[220px] transition-all hover:shadow-md",
        "border-blue-200 dark:border-blue-800",
        selected && "ring-2 ring-blue-500 shadow-lg shadow-blue-500/20",
        Boolean(data.executionActive) && "ring-2 ring-amber-400 shadow-lg shadow-amber-400/30 animate-pulse",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-blue-400"
      />
      <div className="flex items-center gap-2">
        <div className="rounded-lg bg-blue-100 dark:bg-blue-900 p-1.5 flex-none">
          <Zap className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-sm truncate block">
            {String(data.name)}
          </span>
        </div>
      </div>
      <div className="mt-1.5 space-y-0.5">
        {skillLabel && (
          <div className="text-[11px] font-medium text-blue-600 dark:text-blue-400 truncate">
            {skillLabel}
          </div>
        )}
        {hasParams && (
          <div className="text-[10px] text-muted-foreground/70 truncate">
            {Object.keys(params).length} 个参数
          </div>
        )}
        {!skillLabel && !hasParams && (
          <span className="text-[10px] text-muted-foreground">Skill</span>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-blue-400"
      />
    </div>
  );
});

export const SkillNode = SkillNodeInner;
