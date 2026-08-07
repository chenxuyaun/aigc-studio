import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { SerialSchedule } from "@aigc/shared-types";

interface Props {
  projectId: string;
}

/** 自动连载：定时生成下一章（celery beat 每分钟 tick）。 */
export function SerialPanel({ projectId }: Props) {
  const toast = useToast();
  const notifiedRef = useRef<Set<string>>(new Set());
  const [items, setItems] = useState<SerialSchedule[]>([]);
  const [form, setForm] = useState({ interval_minutes: 30, batch_size: 1, mode: "narrative", status: "active" });

  const load = async () => {
    try {
      const r = await apiClient.get<{ items: SerialSchedule[] }>(
        `/story/projects/${projectId}/schedules`,
      );
      setItems(r.items);
      // 连载失败 → 浏览器通知（只对新出现的错误提示一次）
      const newError = r.items.find(
        (s) => s.error_message && !notifiedRef.current.has(s.id),
      );
      if (newError) {
        notifiedRef.current.add(newError.id);
        if (typeof Notification !== "undefined") {
          if (Notification.permission === "granted") {
            new Notification("连载失败", { body: newError.error_message });
          } else if (Notification.permission !== "denied") {
            void Notification.requestPermission();
          }
        }
        toast.error(`连载失败：${newError.error_message}`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const create = async () => {
    try {
      await apiClient.post(`/story/projects/${projectId}/schedules`, form);
      await load();
      toast.success("连载已启动");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "启动失败");
    }
  };

  const toggle = async (s: SerialSchedule) => {
    try {
      await apiClient.put(`/story/schedules/${s.id}`, {
        interval_minutes: s.interval_minutes,
        batch_size: s.batch_size,
        mode: s.mode,
        status: s.status === "active" ? "paused" : "active",
      });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    }
  };

  const remove = async (s: SerialSchedule) => {
    if (!window.confirm("停止并删除该连载调度？")) return;
    try {
      await apiClient.del(`/story/schedules/${s.id}`);
      await load();
      toast.success("已停止");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <h3 className="text-sm font-semibold">自动连载</h3>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        按设定间隔自动生成下一章（后台任务化，可在任务中心查看进度）。上一章未完成时自动跳过，避免并发。
      </p>
      <div className="flex-1 space-y-2 overflow-y-auto">
        {items.length === 0 && (
          <p className="pt-6 text-center text-xs text-muted-foreground">尚未启动连载</p>
        )}
        {items.map((s) => (
          <div key={s.id} className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className={`text-sm font-medium ${s.status === "active" ? "text-success" : "text-muted-foreground"}`}>
                {s.status === "active" ? "连载中" : "已暂停"}
              </span>
              <div className="flex gap-2 text-xs">
                <button className="text-muted-foreground hover:text-foreground" onClick={() => toggle(s)}>
                  {s.status === "active" ? "暂停" : "恢复"}
                </button>
                <button className="text-danger/70 hover:text-danger" onClick={() => remove(s)}>删除</button>
              </div>
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              每 {s.interval_minutes} 分钟 · 每次 {s.batch_size} 章 · {s.mode === "narrative" ? "叙事模式" : "剧本模式"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              已生成 {s.chapter_count} 章 · 下次 {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}
            </p>
            {(s.fail_count > 0 || s.error_message) && (
              <p className="mt-1 text-xs text-danger/80">
                {s.fail_count > 0 && <span className="mr-2 font-medium">连续失败 {s.fail_count} 次</span>}
                {s.error_message ? `最近错误：${s.error_message}` : ""}
                {s.status === "paused" && "（已自动暂停）"}
              </p>
            )}
          </div>
        ))}
      </div>
      <div className="space-y-2 border-t border-border pt-3">
        <div className="grid grid-cols-2 gap-2">
          <Field label="间隔（分钟）">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="number" min={1}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.interval_minutes}
                onChange={(e) => setForm({ ...form, interval_minutes: Number(e.target.value) })}
              />
            )}
          </Field>
          <Field label="每批章节数">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="number" min={1} max={5}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.batch_size}
                onChange={(e) => setForm({ ...form, batch_size: Number(e.target.value) })}
              />
            )}
          </Field>
        </div>
        <Field label="生成模式">
          {({ id, describedBy }) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              value={form.mode}
              onChange={(e) => setForm({ ...form, mode: e.target.value })}
            >
              <option value="narrative">叙事模式（小说正文）</option>
              <option value="script">剧本模式（群聊对话流）</option>
            </select>
          )}
        </Field>
        <Button size="sm" className="w-full" onClick={create}>启动连载</Button>
      </div>
    </div>
  );
}
