/** 正则脚本管理：user_input 发送前 / ai_output 展示前 的查找替换。 */

import { useEffect, useState } from "react";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { RegexScript } from "./types";

interface Props {
  characterName: string;
}

const emptyScript = (characterName: string) => ({
  name: "",
  pattern: "",
  replacement: "",
  placement: "ai_output",
  enabled: true,
  scope: (characterName ? "character" : "global") as "global" | "character",
  character_name: characterName || null,
});

export function RegexPanel({ characterName }: Props) {
  const toast = useToast();
  const [items, setItems] = useState<RegexScript[]>([]);
  const [draft, setDraft] = useState(emptyScript(characterName));
  const [editingId, setEditingId] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await apiClient.get<{ items: RegexScript[] }>("/roleplay/regex-scripts");
      const filtered = characterName
        ? res.items.filter(
            (r) => r.scope === "global" || r.character_name === characterName,
          )
        : res.items.filter((r) => r.scope === "global");
      setItems(filtered);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "正则脚本加载失败");
    }
  };

  useEffect(() => {
    setDraft(emptyScript(characterName));
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterName]);

  const save = async () => {
    if (!draft.pattern) {
      toast.error("请填写正则表达式");
      return;
    }
    try {
      const body = { ...draft, scope: draft.scope === "character" ? "character" : "global" };
      if (editingId) {
        await apiClient.put(`/roleplay/regex-scripts/${editingId}`, body);
      } else {
        await apiClient.post("/roleplay/regex-scripts", body);
      }
      setDraft(emptyScript(characterName));
      setEditingId(null);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.del(`/roleplay/regex-scripts/${id}`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const toggle = async (r: RegexScript) => {
    try {
      await apiClient.put(`/roleplay/regex-scripts/${r.id}`, {
        ...r,
        enabled: !r.enabled,
      });
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "更新失败");
    }
  };

  // 调试：本地测试 pattern/replacement 效果
  const [testInput, setTestInput] = useState("");
  const testResult = (() => {
    if (!testInput || !draft.pattern) return "";
    try {
      return testInput.replace(new RegExp(draft.pattern, "g"), draft.replacement);
    } catch {
      return "（正则语法错误）";
    }
  })();

  return (
    <div className="space-y-3">
      {/* 调试器 */}
      <div className="rounded-xl border border-border bg-surface p-3">
        <h4 className="mb-1.5 text-xs font-semibold text-muted-foreground">调试器（本地测试）</h4>
        <textarea
          value={testInput}
          onChange={(e) => setTestInput(e.target.value)}
          placeholder="输入测试文本，实时预览替换效果"
          className="mb-1.5 min-h-[48px] w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs outline-none focus:border-primary"
        />
        <div className="rounded-lg bg-background px-2 py-1.5 text-xs">
          <span className="mr-1 text-[10px] text-muted-foreground">结果：</span>
          <span className={testResult.startsWith("（正则语法错误）") ? "text-danger" : ""}>
            {testInput ? (testResult || "（替换为空）") : "—"}
          </span>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <Input
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="脚本名"
            className="h-7 w-28"
          />
          <select
            value={draft.placement}
            onChange={(e) => setDraft((d) => ({ ...d, placement: e.target.value }))}
            className="h-7 rounded-lg border border-border bg-background px-2"
          >
            <option value="ai_output">AI 回复后</option>
            <option value="user_input">用户消息前</option>
          </select>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
            />
            启用
          </label>
          <select
            value={draft.scope}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                scope: e.target.value as "global" | "character",
                character_name: e.target.value === "character" ? characterName || null : null,
              }))
            }
            className="h-7 rounded-lg border border-border bg-background px-2"
          >
            <option value="global">全局</option>
            <option value="character">仅当前角色</option>
          </select>
        </div>
        <Input
          value={draft.pattern}
          onChange={(e) => setDraft((d) => ({ ...d, pattern: e.target.value }))}
          placeholder="正则表达式（如：\\(\\*\\*行动\\*\\*\\)）"
          className="mb-2 h-7 text-xs"
        />
        <Textarea
          value={draft.replacement}
          onChange={(e) => setDraft((d) => ({ ...d, replacement: e.target.value }))}
          placeholder="替换为（支持 $1 分组引用）"
          className="mb-2 min-h-[40px] text-xs"
        />
        <Button variant="outline" size="sm" onClick={() => void save()}>
          {editingId ? "保存修改" : "添加脚本"}
        </Button>
      </div>

      {items.length === 0 && (
        <p className="py-2 text-center text-xs text-muted-foreground">
          暂无脚本 —— 例如把回复中的（*行动*）替换为「行动」
        </p>
      )}
      <div className="space-y-1.5">
        {items.map((r) => (
          <div
            key={r.id}
            className={`rounded-lg border border-border px-3 py-2 text-xs ${r.enabled ? "" : "opacity-50"}`}
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <button className="flex items-center gap-2 text-left" onClick={() => void toggle(r)}>
                <input type="checkbox" checked={r.enabled} readOnly />
                <span className="font-medium">{r.name || r.pattern.slice(0, 24)}</span>
                <span className="text-[10px] text-muted-foreground">
                  {r.placement === "user_input" ? "用户前" : "AI后"} · {r.scope}
                </span>
              </button>
              <button className="text-muted-foreground hover:text-danger" onClick={() => void remove(r.id)}>
                <Trash2 className="h-3 w-3" aria-hidden />
              </button>
            </div>
            <code className="block truncate text-[10px] text-muted-foreground">
              {r.pattern} → {r.replacement}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}
