import { useCallback, useEffect, useRef, useState } from "react";

import { useSearchParams } from "react-router-dom";

import { DEFAULT_MODEL } from "@/lib/constants";
import { apiClient, streamSse } from "@/lib/apiClient";
import { useToast } from "@/components/ui/Toast";
import type { ChatMsg, ChatSession, CharacterItem, Persona, QuickReply } from "./types";

/**
 * 角色扮演引擎：全部状态与聊天逻辑（发送/流式/群聊/自动模式/房间轮询/数据加载）。
 * 由 RoleplayPage 解构使用——JSX 保持纯展示。
 */
function expandQuickMacros(text: string, charName: string, userName: string): string {
  let out = text
    .replace(/\{\{char\}\}/g, charName)
    .replace(/\{\{user\}\}/g, userName)
    .replace(/<CHAR>/g, charName)
    .replace(/<USER>/g, userName);
  out = out.replace(/\{\{random::([^}]+)\}\}/g, (_m: string, opts: string) => {
    const parts = opts.split("::").filter(Boolean);
    return parts[Math.floor(Math.random() * parts.length)] ?? "";
  });
  return out;
}

export function useRoleplayEngine() {
  const toast = useToast();
  const [characters, setCharacters] = useState<CharacterItem[]>([]);
  const [charSearch, setCharSearch] = useState("");
  const [selected, setSelected] = useState<CharacterItem | null>(null);
  const [groupMode, setGroupMode] = useState(false);
  const [isRoom, setIsRoom] = useState(false); // 多人同场演出：全员可见可加入
  const [authorName, setAuthorName] = useState(""); // 房间内真人身份
  const [groupName, setGroupName] = useState(""); // 群名（建群时）
  const [groupDesc, setGroupDesc] = useState(""); // 群简介
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [groupStrategy, setGroupStrategy] = useState<"natural" | "list" | "random">("natural");
  const [groupModeType, setGroupModeType] = useState<"append" | "swap">("append");
  const [affinity, setAffinity] = useState(0);
  const [input, setInput] = useState("");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [modelCatalog, setModelCatalog] = useState<{ id: string; label: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [streamingText, setStreamingText] = useState("");

  // 服务端会话
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const roomPollRef = useRef<number | null>(null);

  // 参数 / persona / 快捷回复
  const [temperature, setTemperature] = useState(0.8);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState("");
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [noteContent, setNoteContent] = useState("");
  const [noteInterval, setNoteInterval] = useState(1);
  const [promptTokens, setPromptTokens] = useState<number | null>(null);
  const [msgSearch, setMsgSearch] = useState("");
  const [autoMode, setAutoMode] = useState(false);
  const [autoInterval, setAutoInterval] = useState(8);

  // 右侧标签
  const [rightTab, setRightTab] = useState<"lore" | "character" | "regex" | "settings" | "memory" | "book">("lore");

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;

  // 好感度持久化
  useEffect(() => {
    const saved = localStorage.getItem("aigc-roleplay-affinity");
    if (saved) setAffinity(Number(saved));
  }, []);
  useEffect(() => {
    localStorage.setItem("aigc-roleplay-affinity", String(affinity));
  }, [affinity]);

  // useToast 返回对象每次渲染新建：解构出稳定引用的 error，避免 useCallback 依赖变化触发请求循环
  const { error: toastError } = useToast();
  const loadCharacters = useCallback(async () => {
    try {
      const res = await apiClient.get<{ items: CharacterItem[] }>("/roleplay/characters");
      setCharacters(res.items);
    } catch (e) {
      toastError(e instanceof Error ? e.message : "角色列表加载失败");
    }
  }, [toastError]);

  const toggleShare = useCallback(
    async (c: CharacterItem) => {
      try {
        await apiClient.put(`/roleplay/characters/${c.asset_id}/share`);
        await loadCharacters();
      } catch {
        toastError("共享设置失败");
      }
    },
    [loadCharacters, toastError],
  );

  const loadPersonas = useCallback(async () => {
    try {
      const res = await apiClient.get<{ items: Persona[] }>("/roleplay/personas");
      setPersonas(res.items);
    } catch {
      // 忽略（无 persona 时正常）
    }
  }, []);

  const loadQuickReplies = useCallback(async () => {
    try {
      const res = await apiClient.get<{ items: QuickReply[] }>("/roleplay/quick-replies");
      setQuickReplies(res.items);
    } catch {
      // 忽略
    }
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const res = await apiClient.get<
        { id: string; default_model?: string; name?: string; healthy?: boolean }[]
      >("/providers/catalog");
      const items = (res as unknown as { items?: typeof res })
        .items ?? res;
      const list = (Array.isArray(items) ? items : [])
        .filter((m) => m.id && m.id !== "mock")
        .map((m) => ({
          id: m.default_model || m.id,
          label: `${m.name || m.id}（${m.default_model || m.id}）${m.healthy === false ? " · 维护中" : ""}`,
        }));
      setModelCatalog(list);
      if (list.length > 0 && !list.some((m) => m.id === model) && list[0]) {
        setModel(list[0].id);
      }
    } catch {
      // 目录不可用时保留默认
    }
  }, [model]);

  useEffect(() => {
    void loadCharacters();
    void loadPersonas();
    void loadQuickReplies();
    void loadModels();
  }, [loadCharacters, loadPersonas, loadQuickReplies, loadModels]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  // 群聊自动模式：定时自动发言
  useEffect(() => {
    if (!autoMode || !groupMode || groupIds.length < 2) return;
    const timer = setInterval(() => {
      void autoTurn();
    }, Math.max(3, autoInterval) * 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode, autoInterval, groupMode, groupIds, sessionId, busy]);

  const refreshSessions = useCallback(() => {
    setRefreshTick((t) => t + 1);
  }, []);

  const openSession = async (s: ChatSession) => {
    setSessionId(s.id);
    setModel(s.model || model);
    if (s.temperature != null) setTemperature(s.temperature);
    if (s.max_tokens != null) setMaxTokens(s.max_tokens);
    // 自动选中会话的角色卡（列表未加载完时先存目标，由 loadCharacters 完成后补选）
    if (s.character_asset_ids.length > 0) {
      const first = characters.find((c) => c.asset_id === s.character_asset_ids[0]);
      if (first) {
        setSelected(first);
        setGroupIds(s.character_asset_ids);
        setGroupMode(s.group && s.character_asset_ids.length > 1);
      }
    }
    try {
      const res = await apiClient.get<{ chat: ChatSession; messages: ChatMsg[] }>(
        `/roleplay/chats/${s.id}`,
      );
      setMessages(res.messages);
      // 多人房间：5s 轮询拉新消息（其他真人发言实时可见；离开会话自动停止）
      if (res.chat.is_room) {
        if (roomPollRef.current != null) window.clearInterval(roomPollRef.current);
        roomPollRef.current = window.setInterval(async () => {
          try {
            const poll = await apiClient.get<{ chat: ChatSession; messages: ChatMsg[] }>(
              `/roleplay/chats/${s.id}`,
            );
            setMessages(poll.messages);
          } catch {
            /* 轮询失败静默 */
          }
        }, 5000);
      } else if (roomPollRef.current != null) {
        window.clearInterval(roomPollRef.current);
        roomPollRef.current = null;
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "会话加载失败");
    }
  };

  const selectCharacter = (c: CharacterItem) => {
    setSelected(c);
    if (!groupMode) {
      setGroupIds([c.asset_id]);
    } else if (!groupIds.includes(c.asset_id)) {
      setGroupIds((prev) => [...prev, c.asset_id]);
    }
  };

  const toggleGroupMember = (id: string) => {
    setGroupIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const ids = groupMode && groupIds.length > 1 ? groupIds : [selected?.asset_id ?? ""];
    if (!ids[0]) {
      toast.error("请先选择角色");
      return;
    }
    const userName = personas.find((p) => p.id === personaId)?.name ?? "用户";
    const userMsg: ChatMsg = {
      role: "user",
      content: expandQuickMacros(text, selected?.name ?? "", userName),
    };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setBusy(true);
    setStreamingText("");
    try {
      let sid = sessionId;
      if (!sid) {
        const created = await apiClient.post<{ ok: boolean; chat: ChatSession; group?: { chat_id?: string } }>(
          isRoom
            ? "/roleplay/groups"
            : "/roleplay/chats",
          isRoom
            ? {
                title: groupName.trim() || "新群",
                description: groupDesc.trim(),
                character_asset_ids: ids,
                model,
                temperature,
                max_tokens: maxTokens,
              }
            : {
                character_asset_ids: ids,
                group: groupMode && ids.length > 1,
                model,
                temperature,
                max_tokens: maxTokens,
              },
        );
        sid = created.chat?.id ?? created.group?.chat_id;
        setSessionId(sid);
        void refreshSessions();
      }
      await streamSse(
        "/roleplay/chat/stream",
        {
          character_asset_ids: ids,
          messages: next,
          model,
          group: groupMode && ids.length > 1,
          session_id: sid,
          author: isRoom ? authorName.trim() : "",
          temperature,
          max_tokens: maxTokens,
          persona_id: personaId || null,
          note: noteContent.trim()
          ? { content: noteContent.trim(), interval: noteInterval }
          : null,
          group_strategy: groupStrategy,
          group_mode: groupModeType,
        },
        (ev) => {
          if (ev.type === "chunk" && typeof ev.content === "string") {
            setStreamingText((prev) => prev + ev.content);
          } else if (ev.type === "done") {
            setStreamingText(String(ev.reply ?? ""));
            const mood = String(ev.mood ?? "");
            const delta = ev.mood_delta;
            if (typeof delta === "number" && delta !== 0) {
              setAffinity((a) => a + delta);
            }
            setMessages((prev) => [...prev, { role: "assistant", content: String(ev.reply ?? ""), mood }]);
            setStreamingText("");
            const hits = ev.worldbook_hits;
            if (typeof hits === "number" && hits > 0) {
              toast.info(`世界书命中 ${hits} 条设定`);
            }
            const spk = ev.speaker;
            if (typeof spk === "string" && spk) {
              toast.info(`轮到 ${spk} 发言`);
            }
            const ar = ev.auto_replies;
            if (Array.isArray(ar) && ar.length > 0) {
              const first = ar[0] as { message?: string } | undefined;
              if (first?.message) {
                setInput(String(first.message));
                toast.info(`自动建议：${String((ar[0] as { label?: string })?.label ?? "快捷回复")}`);
              }
            }
            const pt = ev.prompt_tokens;
            if (typeof pt === "number") setPromptTokens(pt);
            if (ev.chat_id) void refreshSessions();
          } else if (ev.type === "error") {
            toast.error(String(ev.error ?? "生成失败"));
            setStreamingText("");
            setMessages((prev) => prev.slice(0, -1));
          }
        },
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "对话失败");
      setStreamingText("");
    } finally {
      setBusy(false);
    }
  };

  const swipeReply = async (msgIndex: number) => {
    if (busy || !sessionId || !selected) return;
    const ids = groupMode && groupIds.length > 1 ? groupIds : [selected.asset_id];
    const before = messages.slice(0, msgIndex + 1);
    setBusy(true);
    try {
      const res = await apiClient.post<{ reply: string; error?: string }>("/roleplay/chat", {
        character_asset_ids: ids,
        messages: before,
        model,
        group: groupMode && ids.length > 1,
        session_id: sessionId,
        temperature,
        max_tokens: maxTokens,
        persona_id: personaId || null,
        note: noteContent.trim()
          ? { content: noteContent.trim(), interval: noteInterval }
          : null,
        swipe: true,
      });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setMessages((prev) => {
        const copy = [...prev];
        const msg = copy[msgIndex];
        if (!msg || msg.role !== "assistant") return prev;
        const swipes = [...(msg.swipes ?? [msg.content]), res.reply];
        copy[msgIndex] = { ...msg, content: res.reply, swipes, swipeIndex: swipes.length - 1 };
        return copy;
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "换一个失败");
    } finally {
      setBusy(false);
    }
  };

  const switchSwipe = (msgIndex: number, delta: number) => {
    setMessages((prev) => {
      const copy = [...prev];
      const msg = copy[msgIndex];
      if (!msg || !msg.swipes || msg.swipes.length < 2) return prev;
      const cur = msg.swipeIndex ?? msg.swipes.length - 1;
      const next = Math.max(0, Math.min(msg.swipes.length - 1, cur + delta));
      copy[msgIndex] = { ...msg, content: msg.swipes[next] ?? "", swipeIndex: next };
      return copy;
    });
  };

  const continueReply = async (msgIndex: number) => {
    if (busy || !sessionId || !selected) return;
    const ids = groupMode && groupIds.length > 1 ? groupIds : [selected.asset_id];
    const before = messages.slice(0, msgIndex + 1);
    setBusy(true);
    try {
      const res = await apiClient.post<{ reply: string; error?: string }>("/roleplay/chat", {
        character_asset_ids: ids,
        messages: before,
        model,
        group: groupMode && ids.length > 1,
        session_id: sessionId,
        temperature,
        max_tokens: maxTokens,
        persona_id: personaId || null,
        note: noteContent.trim()
          ? { content: noteContent.trim(), interval: noteInterval }
          : null,
        mode: "continue",
      });
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setMessages((prev) => {
        const copy = [...prev];
        const msg = copy[msgIndex];
        if (!msg || msg.role !== "assistant") return prev;
        copy[msgIndex] = { ...msg, content: msg.content + res.reply };
        return copy;
      });
      void refreshSessions();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "续写失败");
    } finally {
      setBusy(false);
    }
  };

  const removeMessage = async (msgIndex: number) => {
    if (!sessionId) return;
    const before = messages.slice(0, msgIndex);
    const after = messages.slice(msgIndex + 1);
    setMessages([...before, ...after]);
    try {
      await apiClient.put(`/roleplay/chats/${sessionId}`, { remove_index: msgIndex });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
      void openSession({ id: sessionId } as ChatSession);
    }
  };

  /** 自动模式：无用户输入，让角色继续对话（群聊轮转） */
  const autoTurn = async () => {
    if (busy || !sessionId || !selected || messages.length === 0) return;
    const ids = groupMode && groupIds.length > 1 ? groupIds : [selected.asset_id];
    const userName = personas.find((p) => p.id === personaId)?.name ?? "用户";
    setBusy(true);
    setStreamingText("");
    try {
      await streamSse(
        "/roleplay/chat/stream",
        {
          character_asset_ids: ids,
          messages,
          model,
          group: groupMode && ids.length > 1,
          session_id: sessionId,
          temperature,
          max_tokens: maxTokens,
          persona_id: personaId || null,
          note: noteContent.trim() ? { content: noteContent.trim(), interval: noteInterval } : null,
          group_strategy: groupStrategy,
          group_mode: groupModeType,
        },
        (ev) => {
          if (ev.type === "chunk" && typeof ev.content === "string") {
            setStreamingText((prev) => prev + ev.content);
          } else if (ev.type === "done") {
            setStreamingText(String(ev.reply ?? ""));
            const mood = String(ev.mood ?? "");
            setMessages((prev) => [...prev, { role: "assistant", content: String(ev.reply ?? ""), mood }]);
            setStreamingText("");
            void refreshSessions();
          } else if (ev.type === "error") {
            toast.error(String(ev.error ?? "自动发言失败"));
            setStreamingText("");
          }
        },
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "自动发言失败");
      setStreamingText("");
    } finally {
      setBusy(false);
    }
    void userName;
  };

  const branchChat = async (msgIndex: number) => {
    if (!sessionId) return;
    try {
      const res = await apiClient.post<{ ok: boolean; chat: ChatSession; error?: string }>(
        `/roleplay/chats/${sessionId}/branch?index=${msgIndex}`,
      );
      if (res.error) {
        toast.error(res.error);
        return;
      }
      await openSession(res.chat);
      toast.success("已分叉新会话");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "分叉失败");
    }
  };

  const clearChat = async () => {
    if (sessionId) {
      try {
        await apiClient.put(`/roleplay/chats/${sessionId}`, { clear: true });
      } catch {
        // 忽略
      }
    }
    setMessages([]);
    setStreamingText("");
  };

  const newSession = (s: ChatSession) => {
    setSessionId(s.id);
    setMessages([]);
    void refreshSessions();
  };

  const deleteSession = (id: string) => {
    if (sessionId === id) {
      setSessionId(null);
      setMessages([]);
    }
    void refreshSessions();
  };

  const charsForBinding = selected?.filename ?? "";

  // 从创作工作台跳转：?chat=<id> 自动打开刚建好的群
  const [urlParams] = useSearchParams();
  useEffect(() => {
    const target = urlParams.get("chat");
    if (!target) return;
    void (async () => {
      try {
        const res = await apiClient.get<{ items: ChatSession[] }>("/roleplay/chats");
        const s = res.items.find((x) => x.id === target);
        if (s) await openSession(s);
      } catch {
        /* 会话不存在时静默 */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    characters, selected, groupMode, isRoom, authorName, groupIds, groupStrategy,
    groupModeType, affinity, input, model, modelCatalog, busy, streamingText,
    sessionId, refreshTick, messages, temperature, maxTokens, personas, personaId,
    quickReplies, noteContent, noteInterval, promptTokens, msgSearch, autoMode,
    autoInterval, rightTab, charSearch, bottomRef, roomPollRef,
    setGroupIds, setCharSearch, setIsRoom, setAuthorName, setGroupStrategy, setGroupModeType,
    setPersonaId, setNoteContent, setNoteInterval, setMsgSearch, setAutoMode,
    setAutoInterval, setRightTab, setInput, setAffinity, setGroupMode, setModel,
    groupName, setGroupName, groupDesc, setGroupDesc,
    setTemperature, setMaxTokens, setSelected, setPersonas, setQuickReplies,
    loadCharacters, toggleShare, openSession, selectCharacter, toggleGroupMember,
    send, swipeReply, switchSwipe, continueReply, removeMessage, branchChat,
    clearChat, newSession, deleteSession, charsForBinding, expandQuickMacros,
  };
}
