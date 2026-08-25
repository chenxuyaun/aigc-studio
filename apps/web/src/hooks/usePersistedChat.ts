import { useCallback, useEffect, useState } from "react";

const MAX_MESSAGES = 200;

export interface PersistedChatMessage {
  role: "user" | "assistant";
  content: string;
  mood?: string;
  /** 工具生成结果（如生图 asset_url），用于对话内图片回显 */
  image?: string;
  /** 媒体类型：image | audio | comic（用于多媒体消息渲染） */
  media?: "image" | "audio" | "comic";
  /** v2 P1 结构化命令卡：/image /music 等解析结果，可推送 Studio 带参执行 */
  dispatch?: { kind: "image" | "music" | "tts" | "comic"; args: string; target: string };
  /** v2 批7：思维链（上游 reasoning），折叠展示、随消息持久化 */
  thinking?: string;
  /** v2 批7：本轮工具调用留痕——回答结束后不再被清空，刷新可回看 */
  toolCalls?: { name: string; status: "running" | "done" }[];
}

/**
 * 对话历史本地持久化：刷新/关闭页面后保留，清空时移除。
 * 恢复时过滤掉空消息（流式中断残留的占位气泡）。
 */
export function usePersistedChat(key: string) {
  const [messages, setMessages] = useState<PersistedChatMessage[]>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(
        (m): m is PersistedChatMessage =>
          !!m &&
          typeof m === "object" &&
          (m as PersistedChatMessage).role !== undefined &&
          typeof (m as PersistedChatMessage).content === "string" &&
          (m as PersistedChatMessage).content.length > 0,
      );
    } catch {
      return [];
    }
  });

  // 消息上限：超限丢弃最旧（防止长对话撑爆 localStorage 5MB 配额）
  const trimmed = messages.length > MAX_MESSAGES ? messages.slice(-MAX_MESSAGES) : messages;

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(trimmed));
    } catch {
      // 存储满/隐私模式：静默降级为内存会话
    }
  }, [key, trimmed]);

  const clearChat = useCallback(() => {
    setMessages([]);
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  }, [key]);

  return { messages, setMessages, clearChat } as const;
}
