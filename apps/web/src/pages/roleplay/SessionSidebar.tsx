/** 会话侧栏：列表 / 新建 / 切换 / 重命名 / 删除 / 导入导出。 */

import { useEffect, useState } from "react";

import { FolderPlus, MessageSquare, Upload } from "lucide-react";

import { Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { ChatSession } from "./types";

interface Props {
  activeId: string | null;
  refreshKey: number;
  onSelect: (session: ChatSession) => void;
  onCreated: (session: ChatSession) => void;
  onDeleted: (id: string) => void;
}

export function SessionSidebar({ activeId, refreshKey, onSelect, onCreated, onDeleted }: Props) {
  const toast = useToast();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const load = async () => {
    try {
      const res = await apiClient.get<{ items: ChatSession[] }>("/roleplay/chats");
      setSessions(res.items);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "会话列表加载失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const create = async () => {
    try {
      const res = await apiClient.post<{ ok: boolean; chat: ChatSession }>("/roleplay/chats", {
        character_asset_ids: [],
      });
      setSessions((prev) => [res.chat, ...prev]);
      onCreated(res.chat);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "新建会话失败");
    }
  };

  const rename = async (id: string) => {
    if (!renameValue.trim()) return;
    try {
      await apiClient.put(`/roleplay/chats/${id}`, { title: renameValue.trim() });
      setRenaming(null);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "重命名失败");
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.del(`/roleplay/chats/${id}`);
      onDeleted(id);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const exportChat = async (id: string, title: string) => {
    try {
      const blob = await apiClient.getBlob(`/roleplay/chats/${id}/export`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.replace(/[\\/:*?"<>|]/g, "_").slice(0, 40) || "chat"}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    }
  };

  const importChat = async (file: File) => {
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiClient.postForm<{ ok: boolean; chat: ChatSession }>(
        "/roleplay/chats/import",
        form,
      );
      setSessions((prev) => [res.chat, ...prev]);
      onCreated(res.chat);
      toast.success("会话导入成功");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    }
  };

  return (
    <div className="flex h-full flex-col gap-1.5 overflow-y-auto p-2">
      <div className="mb-1 flex items-center justify-between px-1">
        <span className="text-xs font-semibold text-muted-foreground">会话</span>
        <div className="flex gap-1">
          <label className="cursor-pointer text-muted-foreground hover:text-foreground" title="导入 JSONL">
            <Upload className="h-3.5 w-3.5" aria-hidden />
            <input
              type="file"
              accept=".jsonl,.json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importChat(f);
                e.target.value = "";
              }}
            />
          </label>
          <button
            className="text-muted-foreground hover:text-foreground"
            title="新建会话"
            onClick={() => void create()}
          >
            <FolderPlus className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>
      {sessions.length === 0 && (
        <p className="px-1 py-3 text-center text-xs text-muted-foreground">
          暂无会话 —— 点击右上角新建
        </p>
      )}
      {sessions.map((s) => (
        <div
          key={s.id}
          className={`group flex items-center gap-1 rounded-lg border px-2 py-1.5 text-xs transition-colors ${
            activeId === s.id
              ? "border-primary bg-primary/10"
              : "border-border hover:border-border-strong"
          }`}
        >
          {renaming === s.id ? (
            <Input
              autoFocus
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void rename(s.id);
                if (e.key === "Escape") setRenaming(null);
              }}
              className="h-6 flex-1 px-1.5 text-xs"
            />
          ) : (
            <button
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
              onClick={() => onSelect(s)}
            >
              <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">
                {s.title}
                {s.is_room && (
                  <span className="ml-1 rounded bg-primary/12 px-1 py-0.5 text-[9px] font-semibold text-primary-text">
                    房间
                  </span>
                )}
              </span>
            </button>
          )}
          <span className="hidden shrink-0 gap-0.5 group-hover:flex">
            <button
              className="text-muted-foreground hover:text-foreground"
              title="重命名"
              onClick={() => {
                setRenaming(s.id);
                setRenameValue(s.title);
              }}
            >
              ✎
            </button>
            <button
              className="text-muted-foreground hover:text-foreground"
              title="导出 JSONL"
              onClick={() => void exportChat(s.id, s.title)}
            >
              ⤓
            </button>
            <button
              className="text-muted-foreground hover:text-danger"
              title="删除"
              onClick={() => void remove(s.id)}
            >
              ×
            </button>
          </span>
        </div>
      ))}
    </div>
  );
}
