import { useCallback, useEffect, useState } from "react";

import type { PersistedChatMessage } from "./usePersistedChat";

export interface ChatSession {
  id: string;
  name: string;
  messages: PersistedChatMessage[];
  updatedAt: number;
  /** 自定义分组名（可选）。有值时该会话按分组小节展示，不再按时间分。 */
  group?: string;
  /** 归档标记（可选）。归档会话只出现在侧栏底部归档区。 */
  archived?: boolean;
}

const STORAGE_KEY = "aigc-chat-sessions-v1";
/** 自定义分组名列表（与会话本体分开存储，独立管理）。 */
const GROUP_NAMES_KEY = "aigc-chat-group-names-v1";
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

  // 自定义分组名列表（独立 localStorage key，与会话解耦）
  const [sessionGroupNames, setSessionGroupNames] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(GROUP_NAMES_KEY);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((n): n is string => typeof n === "string" && n.trim().length > 0)
        .slice(-50);
    } catch {
      return [];
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(-MAX_SESSIONS)));
    } catch {
      // 存储满/隐私模式：静默降级
    }
  }, [sessions]);

  useEffect(() => {
    try {
      localStorage.setItem(GROUP_NAMES_KEY, JSON.stringify(sessionGroupNames));
    } catch {
      // 存储满/隐私模式：静默降级
    }
  }, [sessionGroupNames]);

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

  /** 设置/取消会话自定义分组（null 或空串 = 取消分组）。自动登记分组名。 */
  const setSessionGroup = useCallback((id: string, group: string | null) => {
    const name = group?.trim() || "";
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== id) return s;
        const next: ChatSession = { ...s };
        if (name) next.group = name;
        else delete next.group;
        return next;
      }),
    );
    if (name) {
      setSessionGroupNames((prev) =>
        prev.includes(name) ? prev : [...prev, name],
      );
    }
  }, []);

  /** 归档/取消归档会话。 */
  const archiveSession = useCallback((id: string, archived: boolean) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, archived } : s)),
    );
  }, []);

  /** 显式新增一个自定义分组名（不绑定具体会话）。 */
  const addSessionGroup = useCallback((name: string) => {
    const n = name.trim();
    if (!n) return;
    setSessionGroupNames((prev) => (prev.includes(n) ? prev : [...prev, n]));
  }, []);

  /** 删除分组名：从列表移除，并把引用它的会话取消分组。 */
  const removeSessionGroup = useCallback((name: string) => {
    setSessionGroupNames((prev) => prev.filter((n) => n !== name));
    setSessions((prev) =>
      prev.map((s) => {
        if (s.group !== name) return s;
        const next: ChatSession = { ...s };
        delete next.group;
        return next;
      }),
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

  /** 函数式更新当前会话消息（供流式多步追加用，避免闭包过期）。 */
  const updateCurrentMessages = useCallback(
    (fn: (prev: PersistedChatMessage[]) => PersistedChatMessage[]) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== currentId) return s;
          const next = fn(s.messages);
          return {
            ...s,
            messages: next,
            name: s.name !== "新会话" ? s.name : sessionName(next),
            updatedAt: Date.now(),
          };
        }),
      );
    },
    [currentId],
  );

  /** 会话首次使用时确保存在（进入页面自动建一个；兜底选中跳过硬编码的归档会话）。 */
  const ensureSession = useCallback(() => {
    if (!currentId && sessions.length === 0) {
      createSession();
    } else if (!currentId && sessions.length > 0) {
      // 优先选最后一个非归档会话；全是归档则退回任意最后一个
      const last = [...sessions].reverse().find((s) => !s.archived) ?? sessions[sessions.length - 1];
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
    updateCurrentMessages,
    ensureSession,
    // 自定义分组 + 归档（v2 新增，向后兼容，既有导出不变）
    sessionGroupNames,
    setSessionGroup,
    addSessionGroup,
    removeSessionGroup,
    archiveSession,
  };
}
