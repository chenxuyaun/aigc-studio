import { useCallback, useEffect, useState } from "react";

import type { PersistedChatMessage } from "./usePersistedChat";

export interface ChatSession {
  id: string;
  name: string;
  messages: PersistedChatMessage[];
  updatedAt: number;
}

const STORAGE_KEY = "aigc-chat-sessions-v1";
const MAX_SESSIONS = 30;

function newId(): string {
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function sessionName(messages: PersistedChatMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "新会话";
  const text = first.content.replace(/\s+/g, " ").trim();
  return text.length > 20 ? `${text.slice(0, 20)}…` : text || "新会话";
}

/**
 * 多会话管理（localStorage）：新建/切换/删除/自动命名/自动保存。
 * 单个会话上限 30 个，超出丢弃最旧。
 */
export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter(
          (s): s is ChatSession =>
            !!s &&
            typeof s === "object" &&
            typeof (s as ChatSession).id === "string" &&
            Array.isArray((s as ChatSession).messages),
        )
        .slice(-MAX_SESSIONS);
    } catch {
      return [];
    }
  });
  const [currentId, setCurrentId] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(-MAX_SESSIONS)));
    } catch {
      // 存储满/隐私模式：静默降级
    }
  }, [sessions]);

  const current = sessions.find((s) => s.id === currentId) ?? null;

  const createSession = useCallback(() => {
    const session: ChatSession = {
      id: newId(),
      name: "新会话",
      messages: [],
      updatedAt: Date.now(),
    };
    setSessions((prev) => [...prev, session].slice(-MAX_SESSIONS));
    setCurrentId(session.id);
    return session.id;
  }, []);

  const switchSession = useCallback((id: string) => {
    setCurrentId(id);
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        if (next.length === 0) {
          setCurrentId(null);
        } else if (currentId === id) {
          const last = next[next.length - 1];
          if (last) setCurrentId(last.id);
        }
        return next;
      });
    },
    [currentId],
  );

  const renameSession = useCallback((id: string, name: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, name: name.slice(0, 40) || "新会话" } : s)),
    );
  }, []);

  /** 追加/替换当前会话消息（流式回调调用）。 */
  const setCurrentMessages = useCallback(
    (messages: PersistedChatMessage[]) => {
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentId
            ? {
                ...s,
                messages,
                name: s.name !== "新会话" ? s.name : sessionName(messages),
                updatedAt: Date.now(),
              }
            : s,
        ),
      );
    },
    [currentId],
  );

  /** 会话首次使用时确保存在（进入页面自动建一个）。 */
  const ensureSession = useCallback(() => {
    if (!currentId && sessions.length === 0) {
      createSession();
    } else if (!currentId && sessions.length > 0) {
      const last = sessions[sessions.length - 1];
      if (last) setCurrentId(last.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, sessions.length]);

  return {
    sessions,
    currentId,
    current,
    messages: current?.messages ?? [],
    createSession,
    switchSession,
    deleteSession,
    renameSession,
    setCurrentMessages,
    ensureSession,
  };
}
