import { useEffect, useRef, type ReactNode } from "react";

import { X } from "lucide-react";

import { cn } from "@/lib/cn";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
}

/**
 * 无障碍模态：桌面居中，移动端底部抽屉。
 * Escape 关闭、点击遮罩关闭、锁定背景滚动。
 * 打开时聚焦内容区第一个可聚焦控件（输入框优先），避免每次重渲染抢焦点到关闭按钮。
 */
export function Dialog({ open, onClose, title, children, className }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }

    const justOpened = !wasOpenRef.current;
    wasOpenRef.current = true;

    if (justOpened) {
      returnFocusRef.current = document.activeElement as HTMLElement | null;
    }

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
      // 焦点陷阱：Tab 循环在面板内，不逃逸到背景页面
      if (e.key === "Tab") {
        const panel = panelRef.current;
        if (!panel) return;
        const focusables = panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0]!;
        const last = focusables[focusables.length - 1]!;
        const active = document.activeElement;
        if (e.shiftKey && (active === first || !panel.contains(active))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);

    // 仅在「从关到开」时移一次焦点；输入导致的父组件重渲染不得再抢焦点
    let raf = 0;
    if (justOpened) {
      raf = requestAnimationFrame(() => {
        const panel = panelRef.current;
        const preferred = panel?.querySelector<HTMLElement>(
          'input:not([type="hidden"]):not([disabled]), textarea:not([disabled]), select:not([disabled])',
        );
        const fallback = panel?.querySelector<HTMLElement>(
          'button:not([aria-label="关闭"]):not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        );
        (preferred ?? fallback ?? closeRef.current)?.focus();
      });
    }

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      if (!open) {
        // handled below when open flips
      }
    };
  }, [open]);

  // 关闭时归还焦点（与 open effect 分离，避免 onClose 引用变化触发）
  useEffect(() => {
    if (open) return;
    const el = returnFocusRef.current;
    returnFocusRef.current = null;
    // 延后一帧，避免与卸载竞态
    const t = requestAnimationFrame(() => el?.focus?.());
    return () => cancelAnimationFrame(t);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-end justify-center bg-black/60 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCloseRef.current();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "flex max-h-[92dvh] w-full flex-col overflow-hidden border border-border bg-surface-raised shadow-2xl",
          "rounded-t-2xl sm:max-w-2xl sm:rounded-2xl",
          className,
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="truncate pr-3 text-base font-semibold">{title}</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={() => onCloseRef.current()}
            aria-label="关闭"
            className="grid h-8 w-8 flex-none place-items-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4.5 w-4.5" aria-hidden />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
