import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient } from "@/lib/apiClient";
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

interface CloudSession {
  id: string;
  name: string;
  messages: PersistedChatMessage[];
  group?: string | null;
  archived?: boolean;
  updated_at?: number;
}

const STORAGE_KEY = "aigc-chat-sessions-v1";
/** 自定义分组名列表（与会话本体分开存储，独立管理）。 */
const GROUP_NAMES_KEY = "aigc-chat-group-names-v1";
const MAX_SESSIONS = 30;
/** 云端写穿透防抖窗口（ms）。流式期间高频更新被合并成一次 PUT。 */
const SYNC_DEBOUNCE_MS = 1500;

function newId(): string {
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function sessionName(messages: PersistedChatMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "新会话";
  const text = first.content.replace(/\s+/g, " ").trim();
  return text.length > 20 ? `${text.slice(0, 20)}…` : text || "新会话";
}

function readLocal(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (s): s is ChatSession =>
        !!s &&
        typeof s === "object" &&
        typeof (s as ChatSession).id === "string" &&
        Array.isArray((s as ChatSession).messages),
    );
  } catch {
    return [];
  }
}

/**
 * 多会话管理（v2 P1：localStorage 即时层 + 云端写穿同步）。
 * - 新建/切换/删除/自动命名/自动保存（行为与 v1 完全一致）
 * - 挂载时拉取云端会话合并（updatedAt 新者胜）；此后变更防抖 PUT 上行
 * - 单设备离线照常工作（localStorage 兜底），恢复联网后下次打开补同步
 */
export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(readLocal);
  const [currentId, setCurrentId] = useState<string | null>(null);

  // 自定义分组名列表（独立 localStorage key，与会话解耦）
  const [sessionGroupNames, setSessionGroupNames] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(GROUP_NAMES_KEY);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((n): n is string => typeof n === "string" && n.trim().length > 0).slice(-50);
    } catch {
      return [];
    }
  });

  // ── 云同步状态机 ────────────────────────────────
  const cloudLoadedRef = useRef(false); // 云端首拉完成前不写穿（防止空数据覆盖）
  const [cloudReady, setCloudReady] = useState(false); // 供调用方延迟 ensureSession（避免首拉前误建新会话）
  const dirtyRef = useRef<Set<string>>(new Set()); // 待上行会话 id
  const deletedRef = useRef<Set<string>>(new Set()); // 待删除会话 id
  const timerRef = useRef<number | null>(null);
  const sessionsRef = useRef<ChatSession[]>(sessions);
  sessionsRef.current = sessions;

  const flushSync = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const ids = [...dirtyRef.current];
    dirtyRef.current.clear();
    const dels = [...deletedRef.current];
    deletedRef.current.clear();
    if (ids.length === 0 && dels.length === 0) return;
    const byId = new Map(sessionsRef.current.map((x) => [x.id, x]));
    for (const id of ids) {
      if (dels.includes(id)) continue;
      const s = byId.get(id);
      if (!s) continue; // 已被删除（DELETE 分支处理）
      void apiClient
        .put(`/chat/sessions/${encodeURIComponent(id)}`, {
          name: s.name,
          messages: s.messages.slice(-200),
          group: s.group ?? null,
          archived: !!s.archived,
          updated_at: s.updatedAt,
        })
        .catch(() => {});
    }
    for (const id of dels) {
      void apiClient.del(`/chat/sessions/${encodeURIComponent(id)}`).catch(() => {});
    }
  }, []);

  // 页面隐藏/关闭时立即上行（不等防抖），降低刷新丢同步窗口
  useEffect(() => {
    function onHide() {
      if (document.visibilityState === "hidden") flushSync();
    }
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", flushSync);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", flushSync);
    };
  }, [flushSync]);

  // 首拉：GET 云端全量 → 与本地合并（新者胜），本地独有会话补传
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const cloud = await apiClient.get<CloudSession[]>("/chat/sessions");
        if (!alive || !Array.isArray(cloud)) {
          cloudLoadedRef.current = true;
          return;
        }
        const localMap = new Map(readLocal().map((s) => [s.id, s]));
        for (const c of cloud) {
          if (!c?.id || !Array.isArray(c.messages)) continue;
          const cs: ChatSession = {
            id: c.id,
            name: c.name || "新会话",
            messages: c.messages,
            updatedAt: c.updated_at ?? 0,
            ...(c.group ? { group: c.group } : {}),
            ...(c.archived ? { archived: true } : {}),
          };
          const l = localMap.get(c.id);
          // 云端不存在或本地更新 → 保留本地版本待上传；否则采用云端
          if (!l || l.updatedAt <= cs.updatedAt) localMap.set(c.id, cs);
        }
        const merged = [...localMap.values()].sort((a, b) => a.updatedAt - b.updatedAt).slice(-MAX_SESSIONS);
        setSessions(merged);
        // 本地比云端新的会话标记待上行
        const cloudIds = new Set(cloud.map((c) => c.id));
        for (const s of merged) {
          if (cloudIds.has(s.id) || s.messages.length > 0) dirtyRef.current.add(s.id);
        }
      } catch {
        // 未登录/离线：纯本地模式
      } finally {
        if (alive) {
          cloudLoadedRef.current = true;
          setCloudReady(true);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(-MAX_SESSIONS)));
    } catch {
      // 存储满/隐私模式：静默降级
    }
    // 写穿：云端就绪后，把变化的会话防抖上行
    if (!cloudLoadedRef.current) return;
    for (const s of sessions.slice(-MAX_SESSIONS)) dirtyRef.current.add(s.id);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(flushSync, SYNC_DEBOUNCE_MS);
  }, [sessions, flushSync]);

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
      deletedRef.current.add(id);
      dirtyRef.current.delete(id);
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
      setSessionGroupNames((prev) => (prev.includes(name) ? prev : [...prev, name]));
    }
  }, []);

  /** 归档/取消归档会话。 */
  const archiveSession = useCallback((id: string, archived: boolean) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, archived } : s)));
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
    /** 云端首拉是否完成（调用方应等它为 true 再 ensureSession，避免误建新会话）。 */
    cloudReady,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
    setCurrentMessages,
    updateCurrentMessages,
    ensureSession,
    // 自定义分组 + 归档（向后兼容，既有导出不变）
    sessionGroupNames,
    setSessionGroup,
    addSessionGroup,
    removeSessionGroup,
    archiveSession,
  };
}
