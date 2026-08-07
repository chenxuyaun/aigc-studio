import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";

import { cn } from "@/lib/cn";

interface FieldProps {
  label: string;
  required?: boolean;
  error?: string | undefined;
  hint?: string | undefined;
  children: (props: { id: string; describedBy: string | undefined }) => ReactNode;
}

/** 表单字段容器：统一 Label、必填标记、帮助文本、错误信息与 aria 关联。 */
export function Field({ label, required = false, error, hint, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </label>
      {children({ id, describedBy })}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-xl border border-input bg-surface px-3.5 text-[16px] text-foreground",
        "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-ring disabled:opacity-50 sm:text-sm",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "w-full rounded-xl border border-input bg-surface px-3.5 py-2.5 text-[16px] text-foreground",
        "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-ring disabled:opacity-50 sm:text-sm",
        className,
      )}
      {...props}
    />
  );
}
