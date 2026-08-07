/** 设置面板：用户形象（persona）/ 快捷回复 / 作者注 管理。 */

import { useEffect, useState } from "react";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { Persona, QuickReply } from "./types";

interface Props {
  noteContent: string;
  noteInterval: number;
  onNoteChange: (content: string) => void;
  onNoteIntervalChange: (interval: number) => void;
  onPersonasChanged?: (personas: Persona[]) => void;
  onQuickRepliesChanged?: (replies: QuickReply[]) => void;
}

export function SettingsPanel({
  noteContent,
  noteInterval,
  onNoteChange,
  onNoteIntervalChange,
  onPersonasChanged,
  onQuickRepliesChanged,
}: Props) {
  const toast = useToast();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [personaDraft, setPersonaDraft] = useState({ name: "", description: "" });
  const [qrDraft, setQrDraft] = useState({ label: "", message: "", auto: false });

  const load = async () => {
    try {
      const [p, q] = await Promise.all([
        apiClient.get<{ items: Persona[] }>("/roleplay/personas"),
        apiClient.get<{ items: QuickReply[] }>("/roleplay/quick-replies"),
      ]);
      setPersonas(p.items);
      setQuickReplies(q.items);
      onPersonasChanged?.(p.items);
      onQuickRepliesChanged?.(q.items);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "设置加载失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addPersona = async () => {
    if (!personaDraft.name.trim()) {
      toast.error("请填写身份名称");
      return;
    }
    try {
      await apiClient.post("/roleplay/personas", {
        name: personaDraft.name.trim(),
        description: personaDraft.description,
      });
      setPersonaDraft({ name: "", description: "" });
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    }
  };

  const removePersona = async (id: string) => {
    try {
      await apiClient.del(`/roleplay/personas/${id}`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const addQuickReply = async () => {
    if (!qrDraft.label.trim()) {
      toast.error("请填写按钮文字");
      return;
    }
    try {
      await apiClient.post("/roleplay/quick-replies", {
        label: qrDraft.label.trim(),
        message: qrDraft.message,
        scope: "global",
        sort_order: quickReplies.length,
        auto: qrDraft.auto,
      });
      setQrDraft({ label: "", message: "", auto: false });
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    }
  };

  const removeQuickReply = async (id: string) => {
    try {
      await apiClient.del(`/roleplay/quick-replies/${id}`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  return (
    <div className="space-y-4">
      {/* 用户形象 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">用户形象（persona）</h4>
        <div className="space-y-1.5">
          {personas.map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs">
              <div className="min-w-0">
                <span className="font-medium">{p.name}</span>
                <p className="truncate text-muted-foreground">{p.description || "（无描述）"}</p>
              </div>
              <button className="shrink-0 text-muted-foreground hover:text-danger" onClick={() => void removePersona(p.id)}>
                <Trash2 className="h-3 w-3" aria-hidden />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-2 space-y-1.5">
          <Input
            value={personaDraft.name}
            onChange={(e) => setPersonaDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="身份名（将替换 {{user}}）"
            className="h-7 text-xs"
          />
          <Input
            value={personaDraft.description}
            onChange={(e) => setPersonaDraft((d) => ({ ...d, description: e.target.value }))}
            placeholder="身份描述（注入 system prompt）"
            className="h-7 text-xs"
          />
          <Button variant="outline" size="sm" className="w-full" onClick={() => void addPersona()}>
            <Plus className="mr-1 h-3 w-3" aria-hidden />
            添加身份
          </Button>
        </div>
      </section>

      {/* 快捷回复 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">快捷回复（聊天区按钮行）</h4>
        <div className="space-y-1.5">
          {quickReplies.map((q) => (
            <div key={q.id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs">
              <div className="min-w-0">
                <span className="font-medium">
                  {q.label}
                  {"auto" in q && q.auto === true && (
                    <span className="ml-1.5 rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] text-primary">
                      自动
                    </span>
                  )}
                </span>
                <p className="truncate text-muted-foreground">{q.message || "（空消息）"}</p>
              </div>
              <button className="shrink-0 text-muted-foreground hover:text-danger" onClick={() => void removeQuickReply(q.id)}>
                <Trash2 className="h-3 w-3" aria-hidden />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="flex gap-1.5">
            <Input
              value={qrDraft.label}
              onChange={(e) => setQrDraft((d) => ({ ...d, label: e.target.value }))}
              placeholder="按钮文字"
              className="h-7 w-24 text-xs"
            />
            <Input
              value={qrDraft.message}
              onChange={(e) => setQrDraft((d) => ({ ...d, message: e.target.value }))}
              placeholder="消息内容（支持 {{char}}/{{random::A::B}}）"
              className="h-7 flex-1 text-xs"
            />
          </div>
          <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <input
              type="checkbox"
              checked={qrDraft.auto}
              onChange={(e) => setQrDraft((d) => ({ ...d, auto: e.target.checked }))}
            />
            自动触发（每次你发消息后自动建议）
          </label>
          <Button variant="outline" size="sm" className="w-full" onClick={() => void addQuickReply()}>
            <Plus className="mr-1 h-3 w-3" aria-hidden />
            添加快捷回复
          </Button>
        </div>
      </section>

      {/* 作者注 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">作者注（持续注入的提示）</h4>
        <Textarea
          value={noteContent}
          onChange={(e) => onNoteChange(e.target.value)}
          placeholder="例如：故事基调是温馨治愈的，角色说话要温柔。（每次对话都会注入，支持 {{char}} 宏）"
          className="min-h-[72px] text-xs"
        />
        <label className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          注入频率：每
          <input
            type="number"
            min={1}
            max={20}
            value={noteInterval}
            onChange={(e) => onNoteIntervalChange(Math.max(1, Number(e.target.value) || 1))}
            className="h-6 w-14 rounded border border-border bg-background px-1.5 text-xs"
          />
          条用户消息注入一次
        </label>
      </section>
    </div>
  );
}
