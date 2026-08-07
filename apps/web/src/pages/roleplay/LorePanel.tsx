/** 世界书高级管理：多关键词 / 常驻 / 选择性 / 位置 / 深度 / 概率 / 启用。 */

import { useEffect, useState } from "react";

import { Download, Trash2, Upload } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { LoreEntry } from "./types";

interface Props {
  characterName: string;
  onHit?: () => void;
}

const emptyLore = (characterName: string): Omit<LoreEntry, "id"> => ({
  character_name: characterName || null,
  keyword: "",
  keywords: [],
  keysecondary: [],
  content: "",
  constant: false,
  selective: true,
  selective_logic: "AND_ANY",
  position: "before",
  order_value: 100,
  depth: 4,
  role: "system",
  case_sensitive: false,
  match_whole_words: false,
  probability: 100,
  enabled: true,
});

export function LorePanel({ characterName }: Props) {
  const toast = useToast();
  const [items, setItems] = useState<LoreEntry[]>([]);
  const [draft, setDraft] = useState<Omit<LoreEntry, "id">>(emptyLore(characterName));
  const [editingId, setEditingId] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await apiClient.get<{ items: LoreEntry[] }>("/roleplay/lore");
      const filtered = characterName
        ? res.items.filter((e) => !e.character_name || e.character_name === characterName)
        : res.items;
      setItems(filtered);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "世界书加载失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characterName]);

  const exportLore = async () => {
    try {
      const blob = await apiClient.getBlob("/roleplay/lore/export");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "lorebook.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    }
  };

  const importLore = async (file: File) => {
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiClient.postForm<{ ok: boolean; imported?: number; error?: string }>(
        "/roleplay/lore/import",
        form,
      );
      if (res.error) {
        toast.error(res.error);
        return;
      }
      toast.success(`导入 ${res.imported ?? 0} 条世界书条目`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    }
  };

  const save = async () => {
    const body = {
      ...draft,
      character_name: characterName || draft.character_name || null,
      keywords: draft.keywords.length ? draft.keywords : draft.keyword ? [draft.keyword] : [],
    };
    try {
      if (editingId) {
        await apiClient.put(`/roleplay/lore/${editingId}`, body);
      } else {
        await apiClient.post("/roleplay/lore", body);
      }
      setDraft(emptyLore(characterName));
      setEditingId(null);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.del(`/roleplay/lore/${id}`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const edit = (e: LoreEntry) => {
    setEditingId(e.id);
    setDraft({
      character_name: e.character_name ?? null,
      keyword: e.keyword,
      keywords: e.keywords,
      keysecondary: e.keysecondary,
      content: e.content,
      constant: e.constant,
      selective: e.selective,
      selective_logic: e.selective_logic,
      position: e.position,
      order_value: e.order_value,
      depth: e.depth,
      role: e.role,
      case_sensitive: e.case_sensitive,
      match_whole_words: e.match_whole_words,
      probability: e.probability,
      enabled: e.enabled,
    });
  };

  return (
    <div className="space-y-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">
          SillyTavern lorebook JSON 互通
        </span>
        <div className="flex gap-1">
          <button
            className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary-text"
            onClick={() => void exportLore()}
            title="导出为 ST lorebook JSON"
          >
            <Download className="h-3 w-3" aria-hidden />
            导出
          </button>
          <label className="flex cursor-pointer items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary-text">
            <Upload className="h-3 w-3" aria-hidden />
            导入
            <input
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importLore(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>
      <div className="rounded-xl border border-border bg-surface p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <Input
            value={draft.keyword}
            onChange={(e) => {
              const kw = e.target.value;
              setDraft((d) => ({
                ...d,
                keyword: kw,
                keywords: kw ? [kw, ...d.keywords.filter((k) => k !== kw)].slice(0, 5) : [],
              }));
            }}
            placeholder="触发关键词（可用 /正则/，逗号分隔多词）"
            className="h-7 min-w-[200px] flex-1"
          />
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draft.constant}
              onChange={(e) => setDraft((d) => ({ ...d, constant: e.target.checked }))}
            />
            常驻
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
            />
            启用
          </label>
        </div>
        <Textarea
          value={draft.content}
          onChange={(e) => setDraft((d) => ({ ...d, content: e.target.value }))}
          placeholder="注入的设定内容（支持 {{char}}/{{user}}/{{random::A::B}} 宏）"
          className="mb-2 min-h-[64px] text-xs"
        />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={draft.position}
            onChange={(e) => setDraft((d) => ({ ...d, position: e.target.value }))}
            className="h-7 rounded-lg border border-border bg-background px-2"
          >
            <option value="before">提示词开头</option>
            <option value="after">提示词结尾</option>
            <option value="atDepth">聊天中部（深度）</option>
          </select>
          {draft.position === "atDepth" && (
            <label className="flex items-center gap-1">
              深度
              <input
                type="number"
                min={1}
                max={20}
                value={draft.depth}
                onChange={(e) => setDraft((d) => ({ ...d, depth: Number(e.target.value) || 4 }))}
                className="h-7 w-14 rounded-lg border border-border bg-background px-2"
              />
            </label>
          )}
          <label className="flex items-center gap-1">
            优先级
            <input
              type="number"
              value={draft.order_value}
              onChange={(e) =>
                setDraft((d) => ({ ...d, order_value: Number(e.target.value) || 100 }))
              }
              className="h-7 w-16 rounded-lg border border-border bg-background px-2"
            />
          </label>
          <label className="flex items-center gap-1">
            概率%
            <input
              type="number"
              min={0}
              max={100}
              value={draft.probability}
              onChange={(e) =>
                setDraft((d) => ({ ...d, probability: Number(e.target.value) || 100 }))
              }
              className="h-7 w-16 rounded-lg border border-border bg-background px-2"
            />
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draft.selective}
              onChange={(e) => setDraft((d) => ({ ...d, selective: e.target.checked }))}
            />
            选择性
          </label>
          {draft.selective && (
            <Input
              value={draft.keysecondary.join("，")}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  keysecondary: e.target.value
                    .split(/[，,]/)
                    .map((s) => s.trim())
                    .filter(Boolean),
                }))
              }
              placeholder="次关键词（逗号分隔）"
              className="h-7 w-40"
            />
          )}
          <Button variant="outline" size="sm" onClick={() => void save()}>
            {editingId ? "保存修改" : "添加"}
          </Button>
        </div>
      </div>

      {items.length === 0 && (
        <p className="py-2 text-center text-xs text-muted-foreground">
          暂无条目 —— 添加关键词设定后，对话中命中即自动注入
        </p>
      )}
      <div className="space-y-1.5">
        {items.map((e) => (
          <div
            key={e.id}
            className={`rounded-lg border px-3 py-2 text-xs ${
              e.enabled ? "border-border" : "border-border opacity-50"
            }`}
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-medium">
                {e.constant ? "🔒 " : ""}
                {e.keywords.join("、") || "(常驻)"}
                {!e.enabled && "（禁用）"}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {e.position === "atDepth" ? `深度${e.depth}` : e.position === "after" ? "结尾" : "开头"}
                {" · "}优先级{e.order_value}
                {" · "}概率{e.probability}%
              </span>
            </div>
            <p className="mb-1.5 whitespace-pre-wrap text-muted-foreground">{e.content}</p>
            <div className="flex gap-2">
              <button className="text-primary-text hover:underline" onClick={() => edit(e)}>
                编辑
              </button>
              <button className="text-muted-foreground hover:text-danger" onClick={() => void remove(e.id)}>
                <Trash2 className="h-3 w-3" aria-hidden />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
