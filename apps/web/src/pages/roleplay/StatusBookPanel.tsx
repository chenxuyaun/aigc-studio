import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface Props {
  chatId: string | null;
}

/**
 * 状态账本（会话级）：显示对话中通过 //**角色[类别]：旧 -> 新** 批注登记的
 * 角色状态（伤势/心情/关系等），可手动校正。跨对话保持一致。
 */
export function StatusBookPanel({ chatId }: Props) {
  const toast = useToast();
  const [book, setBook] = useState<Record<string, Record<string, string>>>({});
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!chatId) {
      setBook({});
      return;
    }
    setLoading(true);
    try {
      const r = await apiClient.get<{ book: Record<string, Record<string, string>> }>(
        `/roleplay/chats/${chatId}/status-book`,
      );
      setBook(r.book ?? {});
    } catch {
      /* 忽略 */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  async function save() {
    if (!chatId) return;
    try {
      // 支持两种输入：JSON 或「角色：类别=值」逐行
      let parsed: Record<string, Record<string, string>> = {};
      const text = draft.trim();
      if (text.startsWith("{")) {
        parsed = JSON.parse(text) as Record<string, Record<string, string>>;
      } else {
        for (const line of text.split("\n")) {
          const m = /^\s*([^：:]+)[：:]\s*([^=]+)=(.+)$/.exec(line);
          if (m) {
            const ch = (m[1] ?? "").trim();
            const cat = (m[2] ?? "").trim();
            const val = (m[3] ?? "").trim();
            if (ch && cat && val) {
              parsed[ch] = { ...(parsed[ch] ?? {}), [cat]: val };
            }
          }
        }
      }
      await apiClient.put(`/roleplay/chats/${chatId}/status-book`, { book: parsed });
      toast.success("账本已保存（后续对话会保持一致）");
      setDraft("");
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败（格式：角色：类别=值 每行一条）");
    }
  }

  if (!chatId) {
    return <p className="p-3 text-xs text-muted-foreground">先选择/新建一个会话</p>;
  }

  const entries = Object.entries(book);
  return (
    <div className="flex flex-col gap-2 p-3 text-xs">
      <p className="leading-relaxed text-muted-foreground">
        📒 角色状态账本——对话中写{" "}
        <code className="rounded bg-muted px-1">//**角色[类别]：旧 -&gt; 新**</code>{" "}
        即可登记（批注不显示在消息里）。
      </p>
      {loading ? (
        <p className="text-muted-foreground">加载中…</p>
      ) : entries.length === 0 ? (
        <p className="rounded-lg bg-muted/40 px-3 py-2 text-muted-foreground">
          账本为空。在对话里带批注发言，角色状态会自动登记到这里。
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {entries.map(([ch, cats]) => (
            <div key={ch} className="rounded-lg border border-border bg-surface px-3 py-2">
              <p className="font-medium">{ch}</p>
              {Object.entries(cats).map(([cat, val]) => (
                <p key={cat} className="text-muted-foreground">
                  · {cat} = {val}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        placeholder={"手动校正，每行一条：\n老周：伤势=已恢复\n老周：心情=平静"}
        className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs outline-none focus:border-primary"
      />
      <Button size="sm" variant="outline" className="self-end" onClick={() => void save()}>
        保存校正
      </Button>
    </div>
  );
}
