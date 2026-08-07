/* eslint-disable react-refresh/only-export-components -- 本文件同时导出 store/hook/组件，属通知设施约定 */
import { useCallback } from "react";

import { CheckCircle2, Info, XCircle } from "lucide-react";
import { create } from "zustand";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  items: ToastItem[];
  push: (kind: ToastKind, message: string) => void;
  remove: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set) => ({
  items: [],
  push: (kind, message) => {
    const id = nextId++;
    set((s) => ({ items: [...s.items.slice(-4), { id, kind, message }] }));
    setTimeout(() => {
      set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
    }, 3500);
  },
  remove: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));

/** 全局通知：toast.success("已保存") / toast.error("失败") */
export function useToast() {
  const push = useToastStore((s) => s.push);
  return {
    success: useCallback((message: string) => push("success", message), [push]),
    error: useCallback((message: string) => push("error", message), [push]),
    info: useCallback((message: string) => push("info", message), [push]),
  };
}

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

const STYLES: Record<ToastKind, string> = {
  success: "border-success/40 text-success",
  error: "border-danger/40 text-danger",
  info: "border-border-strong text-foreground",
};

/** 挂载在应用根部（AppShell 内）渲染 toast 列表。 */
export function ToastHost() {
  const items = useToastStore((s) => s.items);
  const remove = useToastStore((s) => s.remove);
  return (
    <div
      className="pointer-events-none fixed right-4 top-16 z-50 flex w-80 flex-col gap-2"
      role="region"
      aria-label="通知"
    >
      {items.map((t) => {
        const Icon = ICONS[t.kind];
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => remove(t.id)}
            className={`pointer-events-auto flex items-start gap-2 rounded-xl border bg-surface px-3 py-2.5 text-left text-sm shadow-lg ${STYLES[t.kind]}`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="break-all">{t.message}</span>
          </button>
        );
      })}
    </div>
  );
}
