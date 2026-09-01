import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import type { SseEvent } from "@/lib/apiClient";
import {
  Archive,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Ellipsis,
  Eraser,
  FolderKanban,
  FolderPlus,
  Home,
  Inbox,
  MessageSquare,
  Plus,
  RotateCcw,
  Search,
  Send,
  Sparkles,
  Square,
  Trash2,
  Wand2,
  Wrench,
  X,
} from "lucide-react";

import { Textarea } from "@/components/ui/Field";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { useChatSessions } from "@/hooks/useChatSessions";
import { AppError, apiClient, streamSse } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { copyText } from "@/lib/clipboard";
import { useNavigate } from "react-router-dom";

/**
 * 对话中枢首页 —— AI 助手
 * 中央对话框 + 侧栏最近会话，自然语言驱动多模态创作（生图/写文/音频/小说…）。
 * 视觉：saiOS 深色玻璃霓虹 AI 助手（设计稿落地，功能全部保真）。
 */

// 能力卡分组：让用户一眼知道 AI 可以做什么（对应 MCP 工具），点击即发
const CAPABILITY_GROUPS: {
  title: string;
  icon: string;
  accent: string;
  items: { icon: string; label: string; prompt: string }[];
}[] = [
  {
    title: "画图",
    icon: "🎨",
    accent: "cyan",
    items: [
      { icon: "🌆", label: "赛博朋克城市夜景", prompt: "帮我画一张赛博朋克风格的城市夜景，霓虹灯、雨夜、高楼" },
      { icon: "🐱", label: "一只可爱的猫", prompt: "画一只可爱的猫，插画风" },
      { icon: "🎭", label: "漫画分镜", prompt: "帮我做一个 4 格日式漫画，题材你来定" },
    ],
  },
  {
    title: "写文",
    icon: "✍️",
    accent: "purple",
    items: [
      { icon: "🌙", label: "科幻短篇开头", prompt: "写一小段科幻小说开头，关于记忆可被买卖的世界" },
      { icon: "📖", label: "故事大纲", prompt: "帮我写一个故事大纲，可以边聊边细化" },
    ],
  },
  {
    title: "写歌 & 语音",
    icon: "🎵",
    accent: "emerald",
    items: [
      { icon: "☀️", label: "夏天的民谣", prompt: "写一首关于夏天的歌，轻快民谣风" },
      { icon: "🔊", label: "把这句话转语音", prompt: "请把「你好，我是你的 AI 助手」合成语音" },
    ],
  },
  {
    title: "角色",
    icon: "🎭",
    accent: "amber",
    items: [
      { icon: "🧬", label: "创建角色卡", prompt: "帮我创建一个性格鲜明的角色卡" },
    ],
  },
];

// 资源库入口（收纳进能力中心，避免侧栏平铺；功能不删只收敛）
const RESOURCE_LINKS: { to: string; icon: string; label: string; desc: string }[] = [
  { to: "/prompts", icon: "📚", label: "提示词库", desc: "1.3 万 + 提示词" },
  { to: "/knowledge", icon: "📖", label: "知识库", desc: "创作知识沉淀" },
  { to: "/assets", icon: "🗂️", label: "素材库", desc: "图片 / 音频素材" },
  { to: "/asmr", icon: "🎧", label: "ASMR 库", desc: "助眠音源" },
  { to: "/agents", icon: "🤖", label: "Agent 库", desc: "智能体目录" },
  { to: "/roleplay", icon: "🎭", label: "角色扮演", desc: "角色对话" },
];

// 斜杠命令面板：输入 / 触发，映射 MCP 能力（对应 agent_chat 工具）
const COMMANDS: { cmd: string; label: string; desc: string; prompt: string }[] = [
  { cmd: "/画图", label: "画一张图", desc: "文生图（grok-imagine-image-lite）", prompt: "帮我画一张：____" },
  { cmd: "/写文", label: "写一段文字", desc: "短文 / 故事 / 大纲", prompt: "帮我写：____" },
  { cmd: "/写歌", label: "写一首歌", desc: "歌词 + 风格/情感", prompt: "帮我写一首歌，关于：____" },
  { cmd: "/语音", label: "合成语音", desc: "文本转语音", prompt: "请把这句话合成语音：「____」" },
  { cmd: "/漫画", label: "生成漫画", desc: "分镜漫画（grok-imagine-image）", prompt: "帮我做一部日式分镜漫画，题材：____" },
  { cmd: "/角色", label: "创建角色卡", desc: "设计一个角色", prompt: "帮我创建一个角色卡：____" },
  { cmd: "/故事", label: "续写故事", desc: "承接故事大纲 / 章节", prompt: "帮我续写故事：____" },
];

// @ 资源引用：静态分类入口 + 动态搜索（统一搜索 /search?q=&scope=all&limit=8）
const AT_RESOURCES: { icon: string; label: string; kind: string; desc: string; to?: string }[] = [
  { icon: "📚", label: "提示词库", kind: "prompts", desc: "1.3 万 + 精选提示词，可搜索引用", to: "/prompts" },
  { icon: "📖", label: "知识库", kind: "knowledge", desc: "创作知识沉淀文档", to: "/knowledge" },
  { icon: "🗂️", label: "素材库", kind: "assets", desc: "图片 / 音频素材", to: "/assets" },
  { icon: "🎧", label: "ASMR 库", kind: "asmr", desc: "助眠音源合集", to: "/asmr" },
  { icon: "🎭", label: "角色卡", kind: "agents", desc: "智能体 / 角色扮演", to: "/roleplay" },
];

// /search 动态搜索结果条目（与后端 SearchResult 对齐）
interface AtSearchItem {
  scope: string;
  id: string;
  title: string;
  snippet: string;
  score: number;
}

const AT_SCOPE_LABEL: Record<string, string> = {
  knowledge: "知识库",
  story: "故事",
  prompts: "提示词",
  agents: "角色",
  assets: "素材",
  asmr: "ASMR",
};

export function AssistantHomePage() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const {
    sessions,
    currentId,
    messages,
    createSession,
    branchSession,
    switchSession,
    deleteSession,
    updateCurrentMessages,
    ensureSession,
    cloudReady,
    // 自定义分组 + 归档
    sessionGroupNames,
    setSessionGroup,
    addSessionGroup,
    removeSessionGroup,
    archiveSession,
  } = useChatSessions();
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 斜杠命令面板开关
  const [showCmds, setShowCmds] = useState(false);
  // @ 资源引用面板开关
  const [showAt, setShowAt] = useState(false);
  // @ 后的过滤词（同时用于动态搜索）
  const [atQuery, setAtQuery] = useState("");
  // /search 动态搜索结果
  const [atResults, setAtResults] = useState<AtSearchItem[]>([]);
  const [atBusy, setAtBusy] = useState(false);
  // v2 P1：@ 引用真注入——已挂载的引用实体（发送时拉取内容进 context_blocks）
  const [atRefs, setAtRefs] = useState<AtSearchItem[]>([]);
  // Prompt Magic Polish 进行中
  const [polishing, setPolishing] = useState(false);
  // v2 P1：模型选择器（catalog 直连，替代硬编码）
  const [chatModel, setChatModel] = useState(
    () => localStorage.getItem("aigc-chat-model") || "gpt-oss-120b-medium",
  );
  const [modelList, setModelList] = useState<{ id: string; label: string; healthy?: boolean }[]>([]);
  // 工具调用过程日志（流式中展示 AI 正在干什么）
  const [toolLog, setToolLog] = useState<{ name: string; status: "running" | "done" }[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // 编辑历史消息：editingIdx 为正在编辑的用户消息下标
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  // 能力中心抽屉开关
  const [showCaps, setShowCaps] = useState(false);
  // 生成画廊（本会话产出）开关
  const [showGallery, setShowGallery] = useState(false);
  // 是否显示工具调用过程（顶部开关真实控制）
  const [showTools, setShowTools] = useState(true);
  // 本会话所有生成媒体（图/漫画/音频），供画廊展示
  const mediaItems = messages.filter(
    (m): m is typeof m & { image: string } => !!m && typeof m.image === "string",
  );
  // 侧栏会话搜索
  const [searchTerm, setSearchTerm] = useState("");
  // 侧栏会话「⋯」菜单：记录展开菜单的会话 id 与锚点坐标（fixed 定位避免被滚动容器裁剪）
  const [menuPos, setMenuPos] = useState<{ id: string; left: number; top: number } | null>(null);
  // 自定义分组小节折叠状态（默认展开）
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  // 归档折叠区开关
  const [archivedOpen, setArchivedOpen] = useState(false);
  // 输入框 ref（@ 插入到光标处需要拿到真实 textarea；Textarea 组件不透传 ref，用容器 querySelector）
  const inputWrapRef = useRef<HTMLDivElement | null>(null);
  const [editVal, setEditVal] = useState("");

  // —— 派生列表：归档会话不进正常列表与搜索结果；有分组的按分组小节，无分组的按时间 ——
  const archivedSessions = sessions.filter((s) => s.archived);
  const visibleSessions = sessions.filter((s) => !s.archived);
  const filteredSessions = searchTerm.trim()
    ? visibleSessions.filter((s) => (s.name || "").toLowerCase().includes(searchTerm.trim().toLowerCase()))
    : visibleSessions;
  // 有自定义分组的会话（按分组小节展示）
  const groupedSessions = filteredSessions.filter((s) => s.group && s.group.trim());
  // 无分组的会话（仍按时间分组展示在最前）
  const ungroupedSessions = filteredSessions.filter((s) => !s.group || !s.group.trim());
  // 分组名列表：已登记的分组名（无会话分组但登记过的也列出，供「新建分组」菜单选择）
  const allGroupNames = useMemo(() => {
    const set = new Set<string>();
    for (const n of sessionGroupNames) set.add(n);
    // 兜底：直接从会话数据里收集（兼容旧数据/未登记但已使用的分组）
    for (const s of groupedSessions) {
      if (s.group && s.group.trim()) set.add(s.group.trim());
    }
    return [...set];
  }, [sessionGroupNames, groupedSessions]);
  // 分组小节的组装：按分组名 → 该组会话列表（保持登记顺序）
  const customGroups = useMemo(() => {
    const map = new Map<string, typeof sessions>();
    for (const s of groupedSessions) {
      const g = (s.group ?? "").trim();
      if (!g) continue;
      const arr = map.get(g);
      if (arr) arr.push(s);
      else map.set(g, [s]);
    }
    const list: { group: string; items: typeof sessions }[] = [];
    for (const g of allGroupNames) {
      const items = map.get(g);
      if (items && items.length > 0) list.push({ group: g, items });
    }
    // 兜底：未登记但被使用的分组也展示
    for (const [g, items] of map) {
      if (!list.some((l) => l.group === g)) list.push({ group: g, items });
    }
    return list;
  }, [allGroupNames, groupedSessions]);
  // 自定义分组折叠状态默认展开
  const toggleGroupCollapse = (g: string) =>
    setCollapsedGroups((prev) => ({ ...prev, [g]: !prev[g] }));

  /** 打开会话「⋯」菜单：记录锚点（按钮右下角），菜单用 fixed 定位展示。 */
  function openSessionMenu(e: ReactMouseEvent<HTMLButtonElement>, id: string) {
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    setMenuPos((prev) =>
      prev && prev.id === id
        ? null
        : { id, left: Math.round(rect.left), top: Math.round(rect.bottom + 4) },
    );
  }

  // —— 最近作品预览（首页欢迎态）——
  interface RecentWork {
    id: string;
    task_type: string;
    status: string;
    asset_url?: string;
    cover_url?: string;
    title?: string;
    prompt?: string | null;
    panel_count?: number;
    created_at?: string | null;
  }
  const [recentWorks, setRecentWorks] = useState<RecentWork[]>([]);

  useEffect(() => {
    let alive = true;
    apiClient
      .get<{ success?: boolean; items?: RecentWork[] }>("/generations/recent?limit=12")
      .then((res) => {
        if (!alive) return;
        setRecentWorks((res && Array.isArray(res.items) ? res.items : []) as RecentWork[]);
      })
      .catch(() => {
        /* 静默：预览区是可选的，加载失败不影响对话 */
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 会话就绪：等云端首拉完成再 ensureSession（否则刷新时会先误建新空会话、丢失当前会话指向）
  useEffect(() => {
    if (!cloudReady) return;
    ensureSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloudReady]);

  // v2 P2：接收统一 Studio 的「推送助手」——带 prompt 回大厅继续对话式创作
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search).get("studio_prompt");
    if (sp && sp.trim()) {
      setInput(sp.trim());
      // 清掉 query 参数避免刷新重复注入
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  // v2 P1：模型列表直连 catalog（裸数组），选中值持久化
  useEffect(() => {
    let alive = true;
    apiClient
      .get<
        { id: string; name?: string; default_model?: string; healthy?: boolean }[] | { items?: { id: string; name?: string; default_model?: string; healthy?: boolean }[] }
      >(
        "/providers/catalog",
      )
      .then((r) => {
        if (!alive) return;
        const raw = Array.isArray(r) ? r : (r.items ?? []);
        // catalog 条目：{id: uuid, name: "cpa·GPT-OSS", default_model: "gpt-oss-120b-medium"}
        const list = raw
          .filter((p) => (p.default_model || p.id) && p.id !== "mock")
          .map((p) => ({ id: p.default_model || p.id, label: p.name || p.default_model || p.id, healthy: p.healthy ?? true }));
        setModelList(list);
        // 当前选择不在列表中 → 自动切到第一个可用模型
        setChatModel((cur) => {
          // 2026-09-01 一次性迁移：旧默认 gpt-oss-120b-medium（内容偏弱，用户反馈）
          // → claude-sonnet-4-6（cpa 旗舰）；此后尊重用户手动选择
          const migrated =
            cur === "gpt-oss-120b-medium" &&
            list.some((p) => p.id === "claude-sonnet-4-6")
              ? "claude-sonnet-4-6"
              : cur;
          const valid = list.some((p) => p.id === migrated);
          const next = valid ? migrated : (list[0]?.id ?? migrated);
          localStorage.setItem("aigc-chat-model", next);
          return next;
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolLog]);

  /** v2 P1 结构化斜杠命令：/image /music /tts /comic <参数> → 派发卡（推送 Studio）。 */
  const SLASH_RE = /^\/(image|music|tts|comic)\s+(.{2,})$/i;
  const SLASH_TARGET: Record<string, { kind: "image" | "music" | "tts" | "comic"; target: string; label: string }> = {
    image: { kind: "image", target: "/create/image", label: "图像引擎" },
    comic: { kind: "comic", target: "/create/comic", label: "漫画引擎" },
    music: { kind: "music", target: "/create/music", label: "音乐引擎" },
    tts: { kind: "tts", target: "/create/audio", label: "语音引擎" },
  };

  async function send(textOverride?: string, editIdx?: number) {
    const text = (textOverride ?? input).trim();
    if (!text || streaming) return;
    // 发送时关闭所有建议面板
    setShowAt(false);
    setAtQuery("");
    setShowCmds(false);
    setError(null);

    // ── 结构化斜杠命令：不进 LLM，直接生成派发卡 ──
    const slash = text.match(SLASH_RE);
    if (slash && !editIdx) {
      const meta = SLASH_TARGET[slash[1]!.toLowerCase()]!;
      const args = slash[2]!.trim();
      setInput("");
      updateCurrentMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: "", dispatch: { kind: meta.kind, args, target: meta.target } },
      ]);
      return;
    }

    // 编辑重发：history 只保留到该条用户消息之前的上下文（不含它），新 text 作为新的最后 user
    const history =
      editIdx !== undefined ? messages.slice(0, editIdx) : messages;

    // v2 P1 @ 引用真注入：收集本条消息中实际 @ 到的实体，拉取内容组装 context_blocks
    const usedRefs = atRefs.filter((r) => text.includes(`@${r.title}`));
    let contextBlocks: { type: string; title: string; content: string }[] | undefined;
    if (usedRefs.length > 0) {
      const blocks = await Promise.all(
        usedRefs.map(async (r): Promise<{ type: string; title: string; content: string }> => {
          try {
            if (r.scope === "knowledge") {
              const d = await apiClient.get<{ title?: string; content?: string }>(
                `/knowledge/documents/${r.id}`,
              );
              return { type: "知识库", title: r.title, content: (d.content ?? "").slice(0, 6000) };
            }
            if (r.scope === "prompts") {
              const p = await apiClient.get<{ title?: string; content?: string }>(`/prompts/${r.id}`);
              return { type: "提示词", title: r.title, content: (p.content ?? "").slice(0, 3000) };
            }
          } catch {
            /* 引用内容取不到时降级为描述块 */
          }
          return { type: AT_SCOPE_LABEL[r.scope] ?? r.scope, title: r.title, content: r.snippet };
        }),
      );
      contextBlocks = blocks;
      // 已使用的引用发送后清掉；未使用的保留
      setAtRefs((prev) => prev.filter((r) => !text.includes(`@${r.title}`)));
    }

    if (editIdx !== undefined) {
      updateCurrentMessages((prev) => {
        const before = prev.slice(0, editIdx);
        return [...before, { role: "user" as const, content: text }];
      });
    } else {
      updateCurrentMessages((prev) => [...prev, { role: "user", content: text }]);
    }
    setInput("");
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantText = "";
    let thinkingText = "";
    setToolLog([]);
    updateCurrentMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    try {
      const payload: Record<string, unknown> = {
        // v2 P1：模型来自 catalog 选择器（默认仍 gpt-oss-120b-medium，走 cpa 链）
        model: chatModel,
        messages: [
          {
            role: "system" as const,
            content:
              "你是云彩平台的 AI 助手。你可以用自然语言帮用户完成多模态创作：生图、写文、写歌、语音合成、故事创作等。" +
              "写歌词/写文案/写故事/写祝福这类**纯文本创作直接用文字回答**，绝不调用生图或音频工具。" +
              "只有用户**明确要求生成图片、音频、语音**时，才调用对应工具完成；否则用对话回答。回答简洁、贴心、用中文。" +
              "\n\n创作格式规范（重要）：\n" +
              "- 歌词必须用标准段落结构：用《歌名》开头，段落间空一行；每段不超过 4-6 行，每行一个完整短语/意象\n" +
              "- 副歌用【副歌】标注，主歌用【主歌一】【主歌二】标注（方便用户谱曲对位）\n" +
              "- 输出使用 Markdown：段落间必须空行，需要强调时用粗体，绝不用 HTML\n" +
              "\n文风要求：\n" +
              "- 意象要具体、有画面感，避免堆砌陈词（大量\"闪闪的光/眨呀眨/叮当\"这类空泛意象）\n" +
              "- 结尾收束自然，**不要**对用户说教、不要主动追问\"需要我再调整吗\"之类的话；作品完成即止\n" +
              "- 用户偏好（颜色/风格）可自然融入，不必刻意点破",
          },
          ...history.map((m) => ({ role: m.role, content: m.content })),
          { role: "user" as const, content: text },
        ],
        ...(contextBlocks ? { context_blocks: contextBlocks } : {}),
        // 批8+9：带会话 id——后端流结束自动反思（成长日记 + 长期记忆）
        session_id: currentId ?? "",
      };
      await streamSse(
        "/generations/text/agent/chat",
        payload,
        (event: SseEvent) => {
          if (event.type === "tool") {
            const toolName = typeof event.name === "string" ? event.name : "工具";
            if (event.status === "running") {
              // 记录正在执行的工具（去重同 name 的 running）
              setToolLog((prev) => {
                if (prev.some((t) => t.name === toolName && t.status === "running")) return prev;
                return [...prev, { name: toolName, status: "running" }];
              });
            } else {
              // 工具完成 → 标记 done
              setToolLog((prev) =>
                prev.map((t) =>
                  t.name === toolName ? { ...t, status: "done" as const } : t,
                ),
              );
              // v2 批7：工具留痕持久进消息（回答结束后仍可回看）
              updateCurrentMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last && last.role === "assistant") {
                  next[next.length - 1] = {
                    ...last,
                    toolCalls: [
                      ...(last.toolCalls ?? []),
                      { name: toolName, status: "done" as const },
                    ],
                  };
                }
                return next;
              });
              // 工具返回多模态结果（生图/音频/漫画）→ 追加媒体消息回显
              const rd = (event as { result_data?: unknown }).result_data;
              const data =
                rd && typeof rd === "object" ? (rd as Record<string, unknown>) : undefined;
              const resourceUrl =
                typeof data?.asset_url === "string" ? data.asset_url : undefined;
              const taskType = typeof data?.task_type === "string" ? data.task_type : "";
              // 漫画：封面图优先；其余媒体用 asset_url
              const coverUrl =
                typeof data?.cover_url === "string" ? data.cover_url : undefined;
              if (taskType === "comic") {
                const cover = coverUrl ?? resourceUrl;
                if (cover) {
                  updateCurrentMessages((prev) => [
                    ...prev,
                    { role: "assistant", content: "", image: cover, media: "comic" },
                  ]);
                }
              } else if (resourceUrl) {
                const media = taskType === "audio" ? "audio" : "image";
                updateCurrentMessages((prev) => [
                  ...prev,
                  { role: "assistant", content: "", image: resourceUrl, media },
                ]);
              }
            }
          } else if (event.type === "reasoning" && typeof event.content === "string") {
            // v2 批7：思维链流式累积（上游 reasoning → Think 折叠行）
            thinkingText += event.content;
            updateCurrentMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                next[next.length - 1] = { ...last, thinking: thinkingText };
              }
              return next;
            });
          } else if (event.type === "chunk" && typeof event.content === "string") {
            assistantText += event.content;
            updateCurrentMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                // spread 旧值：保留已累积的 thinking / toolCalls
                next[next.length - 1] = { ...last, content: assistantText };
              }
              return next;
            });
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof AppError ? err.message : "生成失败，请重试");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setToolLog([]);
    }
  }

  function stop() {
    abortRef.current?.abort();
    setStreaming(false);
  }

  /** v2 P1 Prompt Magic Polish：AI 把输入框里的创作需求改写得更清晰具体。 */
  async function polishInput() {
    const t = input.trim();
    if (!t || polishing || streaming) return;
    setPolishing(true);
    setError(null);
    try {
      const r = await apiClient.post<{ data?: { content?: string } }>(
        "/generations/text/generate",
        {
          prompt:
            "你是提示词润色助手。请把下面这段创作需求改写成清晰、具体、有画面感的中文提示词：保留原意，补全风格、构图、光影、氛围等要素，但不新增无关主题。直接输出改写结果，不要任何解释或前后缀。\n\n原文：" +
            t,
          model: chatModel,
          stream: false,
        },
      );
      const out = r?.data?.content?.trim();
      if (out) setInput(out);
      else setError("润色结果为空，请重试");
    } catch (e) {
      setError(e instanceof AppError ? e.message : "润色失败，请重试");
    } finally {
      setPolishing(false);
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setError(null);
    setToolLog([]);
    setInput("");
    setShowAt(false);
    setAtQuery("");
    setShowCmds(false);
    createSession();
  }

  function useSuggestion(prompt: string) {
    setInput(prompt);
    setShowAt(false);
    setAtQuery("");
    setShowCmds(false);
  }

  /** 纯文本 @token 插入（常用分类入口用——无具体实体，不登记引用）。 */
  function insertToken(name: string) {
    const ta = inputWrapRef.current?.querySelector<HTMLTextAreaElement>("textarea");
    const start = ta ? ta.selectionStart ?? input.length : input.length;
    const end = ta ? ta.selectionEnd ?? start : start;
    const token = `@${name} `;
    setInput(input.slice(0, start) + token + input.slice(end));
    setShowAt(false);
    setAtQuery("");
  }

  /**
   * @ 资源引用（v2 P1 真注入）：把 `@资源名 ` 插入输入框光标处，同时登记引用实体。
   * 发送时按实体类型拉取原文，结构化注入 context_blocks——模型能真正读到内容。
   */
  function insertAt(item: AtSearchItem) {
    setAtRefs((prev) => (prev.some((r) => r.id === item.id) ? prev : [...prev, item]));
    const name = item.title;
    const ta = inputWrapRef.current?.querySelector<HTMLTextAreaElement>("textarea");
    const start = ta ? ta.selectionStart ?? input.length : input.length;
    const end = ta ? ta.selectionEnd ?? start : start;
    const token = `@${name} `;
    const next = input.slice(0, start) + token + input.slice(end);
    setInput(next);
    setShowAt(false);
    setAtQuery("");
    // 恢复焦点并把光标放到插入内容之后（React 受控组件需要异步 setSelectionRange）
    requestAnimationFrame(() => {
      const el = inputWrapRef.current?.querySelector<HTMLTextAreaElement>("textarea");
      if (el) {
        el.focus();
        const caret = Math.min(start + token.length, next.length);
        el.setSelectionRange(caret, caret);
      }
    });
  }

  /** 输入变化：同时驱动 / 命令面板、@ 资源面板与普通输入。 */
  function handleInputChange(v: string) {
    setInput(v);
    // / 面板：输入以 / 开头时显示
    const atIdx = v.lastIndexOf("@");
    const showAtPanel = atIdx >= 0 && (atIdx === 0 || /\s/.test(v[atIdx - 1] ?? ""));
    setShowAt(showAtPanel);
    setAtQuery(showAtPanel ? v.slice(atIdx + 1) : "");
    setShowCmds(v.startsWith("/") && v.length > 0 && !showAtPanel);
  }

  // 会话按时间分组（今天/昨天/近 7 天/更早），只用于「无自定义分组」的会话
  const sessionGroups: { label: string; items: typeof sessions }[] = (() => {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const day = 86400000;
    const groups: { label: string; items: (typeof sessions)[number][] }[] = [
      { label: "今天", items: [] },
      { label: "昨天", items: [] },
      { label: "近 7 天", items: [] },
      { label: "更早", items: [] },
    ];
    for (const s of ungroupedSessions) {
      const t = typeof s.updatedAt === "number" ? s.updatedAt : now.getTime();
      if (t >= startOfDay) groups[0]!.items.push(s);
      else if (t >= startOfDay - day) groups[1]!.items.push(s);
      else if (t >= startOfDay - 7 * day) groups[2]!.items.push(s);
      else groups[3]!.items.push(s);
    }
    return groups.filter((g) => g.items.length > 0);
  })();

  // @ 资源动态搜索：防抖 300ms，取前 8 条（统一搜索 /search，覆盖 knowledge/prompts/assets/asmr/agents/story）
  useEffect(() => {
    const q = atQuery.trim();
    if (!showAt || !q) {
      setAtResults([]);
      setAtBusy(false);
      return;
    }
    const timer = window.setTimeout(() => {
      let alive = true;
      setAtBusy(true);
      apiClient
        .get<{ items?: AtSearchItem[]; total?: number }>(
          `/search?q=${encodeURIComponent(q)}&scope=all&limit=8`,
        )
        .then((res) => {
          if (!alive) return;
          setAtResults(Array.isArray(res.items) ? res.items.slice(0, 8) : []);
        })
        .catch(() => {
          if (alive) setAtResults([]);
        })
        .finally(() => {
          if (alive) setAtBusy(false);
        });
      return () => {
        alive = false;
      };
    }, 300);
    return () => window.clearTimeout(timer);
  }, [showAt, atQuery]);

  // @ 资源面板：点击输入区外部关闭（配合 Escape 键）
  useEffect(() => {
    if (!showAt) return;
    function onDocMouseDown(e: MouseEvent) {
      const wrap = inputWrapRef.current;
      if (wrap && wrap.contains(e.target as Node)) return;
      setShowAt(false);
      setAtQuery("");
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [showAt]);

  const empty = messages.length === 0;
  const qCount = messages.filter((x) => x.role === "user").length;

  const capAccent = (a: string) =>
    a === "purple"
      ? "text-purple-300 border-purple-500/30"
      : a === "emerald"
        ? "text-emerald-300 border-emerald-500/30"
        : a === "amber"
          ? "text-amber-300 border-amber-500/30"
          : "text-cyan-300 border-cyan-500/30";

  return (
    <div className="ai-page absolute inset-0 flex min-h-0 overflow-hidden">
      {/* 粒子背景 + 环境光晕 */}
      <canvas id="ai-bg-canvas" className="pointer-events-none fixed inset-0 z-0 opacity-40" aria-hidden />
      <div className="ai-glow-cyan -left-24 -top-24 animate-pulse-slow" />
      <div className="ai-glow-purple -bottom-32 -right-24 animate-pulse-slow" />

      {/* ============ 能力中心抽屉 ============ */}
      {showCaps && (
        <div className="ai-glass absolute inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-white/10">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <span className="text-sm font-semibold text-slate-100">🧭 能力中心</span>
            <button type="button" aria-label="关闭能力中心" onClick={() => setShowCaps(false)} className="text-slate-400 hover:text-white">
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <div className="flex-1 space-y-4 overflow-y-auto p-3">
            {CAPABILITY_GROUPS.map((g) => (
              <div key={g.title}>
                <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  <span>{g.icon}</span> {g.title}
                </p>
                <div className="space-y-1.5">
                  {g.items.map((s) => (
                    <button
                      key={s.prompt}
                      type="button"
                      onClick={() => {
                        setInput(s.prompt);
                        setShowCaps(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-left text-sm text-slate-400 transition-colors hover:border-cyan-500/40 hover:text-slate-100"
                    >
                      <span>{s.icon}</span>
                      <span className="truncate">{s.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {/* 资源库（原侧栏资源/角色入口收纳于此） */}
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                <span>🗂️</span> 资源库
              </p>
              <div className="space-y-1.5">
                {RESOURCE_LINKS.map((r) => (
                  <a
                    key={r.to}
                    href={r.to}
                    onClick={() => setShowCaps(false)}
                    className="flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-left text-sm text-slate-400 transition-colors hover:border-cyan-500/40 hover:text-slate-100"
                  >
                    <span>{r.icon}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{r.label}</span>
                      <span className="block truncate text-[11px] text-slate-500">{r.desc}</span>
                    </span>
                    <span className="text-[11px] text-slate-600">→</span>
                  </a>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-dashed border-white/15 px-3 py-2.5 text-[11px] leading-relaxed text-slate-500">
              提示：在输入框输入 <span className="font-mono text-cyan-400">/</span> 也能快速打开命令面板。
            </div>
          </div>
        </div>
      )}

      {/* ============ 生成画廊覆盖层 ============ */}
      {showGallery && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-md"
          onClick={() => setShowGallery(false)}
        >
          <div
            className="ai-glass flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
              <span className="text-sm font-semibold text-slate-100">🖼️ 本会话产出（{mediaItems.length}）</span>
              <button type="button" aria-label="关闭画廊" onClick={() => setShowGallery(false)} className="text-slate-400 hover:text-white">
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            <div className="grid flex-1 grid-cols-2 gap-3 overflow-y-auto p-4 sm:grid-cols-3">
              {mediaItems.map((m, idx) => (
                <div key={idx} className="overflow-hidden rounded-xl border border-white/10 bg-slate-900/60">
                  {m.media === "audio" ? (
                    <audio controls src={m.image} className="w-full" />
                  ) : (
                    <img
                      src={m.image}
                      alt={m.media === "comic" ? "AI 漫画" : "AI 生成"}
                      className="aspect-square w-full object-cover"
                    />
                  )}
                  <p className="px-2 py-1.5 text-[11px] text-slate-400">
                    {m.media === "comic" ? "🎴 漫画" : m.media === "audio" ? "🔊 语音" : "🖼️ 图片"}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ============ 侧栏会话「⋯」菜单（fixed 定位，页面级渲染） ============ */}
      {menuPos && (() => {
        const s = sessions.find((x) => x.id === menuPos.id);
        if (!s) return null;
        return (
          <SessionMenu
            left={menuPos.left}
            top={menuPos.top}
            sessionId={s.id}
            currentGroup={s.group}
            groupNames={allGroupNames}
            onClose={() => setMenuPos(null)}
            onSetGroup={(g) => {
              setSessionGroup(s.id, g);
              setMenuPos(null);
            }}
            onNewGroup={() => {
              const name = window.prompt("新建分组名：", "");
              if (name && name.trim()) {
                addSessionGroup(name.trim());
                setSessionGroup(s.id, name.trim());
              }
              setMenuPos(null);
            }}
            onRemoveGroup={() => {
              setSessionGroup(s.id, null);
              setMenuPos(null);
            }}
            onArchive={() => {
              archiveSession(s.id, true);
              setMenuPos(null);
            }}
          />
        );
      })()}

      {/* ============ 左侧会话栏 ============ */}
      <aside className="z-10 hidden w-64 shrink-0 flex-col border-r border-white/10 bg-slate-950/90 backdrop-blur-2xl md:flex">
        <div className="space-y-2.5 border-b border-white/10 p-3.5">
          <button
            onClick={newChat}
            className="ai-glow-btn flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-semibold text-slate-950 shadow-[0_0_20px_rgba(0,242,254,0.3)] transition-all hover:-translate-y-0.5"
          >
            <Plus className="h-4 w-4" aria-hidden /> 开启新创作对话
          </button>
          <button
            onClick={() => setShowCaps(true)}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 py-2 text-xs text-slate-300 transition-colors hover:border-cyan-500/40 hover:text-cyan-300"
          >
            <Wand2 className="h-4 w-4 text-cyan-400" aria-hidden /> 能力中心
          </button>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
            <input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="搜索历史对话…"
              className="ai-glass-input w-full rounded-lg py-1.5 pl-8 pr-3 text-xs text-slate-200 placeholder:text-slate-500 outline-none"
            />
          </div>
        </div>

        <nav className="flex-1 space-y-3 overflow-y-auto p-3 text-xs">
          {/* —— 无分组会话：仍按时间分组（今天/昨天/近 7 天/更早），显示在最前 —— */}
          {sessionGroups.length > 0 ? (
            sessionGroups.map((g) => (
              <div key={g.label} className="space-y-1">
                <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  {g.label}
                </p>
                {g.items.map((s) => (
                  <div
                    key={s.id}
                    className={cn(
                      "group relative flex cursor-pointer items-center gap-2 rounded-xl border p-2.5 transition-all",
                      s.id === currentId
                        ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-200"
                        : "border-transparent text-slate-400 hover:border-white/10 hover:bg-white/5 hover:text-slate-200",
                    )}
                    onClick={() => {
                      abortRef.current?.abort();
                      setStreaming(false);
                      setError(null);
                      setToolLog([]);
                      switchSession(s.id);
                    }}
                  >
                    <MessageSquare className="h-3.5 w-3.5 shrink-0 text-cyan-400/70" aria-hidden />
                    <span className="flex-1 truncate font-medium">{s.name || "新对话"}</span>
                    <button
                      type="button"
                      aria-label="会话菜单"
                      className="opacity-0 transition-opacity hover:text-cyan-300 group-hover:opacity-100"
                      onClick={(e) => openSessionMenu(e, s.id)}
                    >
                      <Ellipsis className="h-3.5 w-3.5" aria-hidden />
                    </button>
                    <button
                      type="button"
                      aria-label="删除会话"
                      className="opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (s.id === currentId) abortRef.current?.abort();
                        deleteSession(s.id);
                      }}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
            ))
          ) : (
            customGroups.length === 0 && (
              <p className="px-2.5 py-2 text-[11px] text-slate-500">
                {searchTerm ? "没有匹配的会话" : "还没有会话，点击「新对话」开始"}
              </p>
            )
          )}

          {/* —— 自定义分组小节（默认展开，点击标题折叠） —— */}
          {customGroups.map((g) => {
            const collapsed = !!collapsedGroups[g.group];
            return (
              <div key={g.group} className="space-y-1">
                <div className="group/title flex w-full items-center gap-1.5 rounded-lg px-2 py-1">
                  <button
                    type="button"
                    onClick={() => toggleGroupCollapse(g.group)}
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-cyan-300/80 transition-colors hover:text-cyan-200"
                  >
                    {collapsed ? (
                      <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
                    ) : (
                      <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
                    )}
                    <span className="truncate">{g.group}</span>
                    <span className="ml-auto shrink-0 rounded bg-cyan-500/15 px-1 py-px font-mono text-[9px] text-cyan-300">
                      {g.items.length}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`删除分组 ${g.group}`}
                    title="删除分组（清空该组会话的分组）"
                    className="shrink-0 rounded p-0.5 text-slate-600 opacity-0 transition-opacity hover:text-rose-400 group-hover/title:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`删除分组「${g.group}」？该组 ${g.items.length} 个会话将移回时间分组。`)) {
                        removeSessionGroup(g.group);
                      }
                    }}
                  >
                    <Trash2 className="h-3 w-3" aria-hidden />
                  </button>
                </div>
                {!collapsed &&
                  g.items.map((s) => (
                    <div
                      key={s.id}
                      className={cn(
                        "group relative flex cursor-pointer items-center gap-2 rounded-xl border p-2.5 transition-all",
                        s.id === currentId
                          ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-200"
                          : "border-transparent text-slate-400 hover:border-white/10 hover:bg-white/5 hover:text-slate-200",
                      )}
                      onClick={() => {
                        abortRef.current?.abort();
                        setStreaming(false);
                        setError(null);
                        setToolLog([]);
                        switchSession(s.id);
                      }}
                    >
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-cyan-400/70" aria-hidden />
                      <span className="flex-1 truncate font-medium">{s.name || "新对话"}</span>
                      <button
                        type="button"
                        aria-label="会话菜单"
                        className="opacity-0 transition-opacity hover:text-cyan-300 group-hover:opacity-100"
                        onClick={(e) => openSessionMenu(e, s.id)}
                      >
                        <Ellipsis className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      <button
                        type="button"
                        aria-label="删除会话"
                        className="opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (s.id === currentId) abortRef.current?.abort();
                          deleteSession(s.id);
                        }}
                      >
                        <Trash2 className="h-3 w-3" aria-hidden />
                      </button>
                    </div>
                  ))}
              </div>
            );
          })}
        </nav>

        {/* 归档折叠区 */}
        {archivedSessions.length > 0 && (
          <div className="border-t border-white/10">
            <button
              type="button"
              onClick={() => setArchivedOpen((v) => !v)}
              className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-xs text-slate-400 transition-colors hover:text-amber-300"
            >
              {archivedOpen ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
              )}
              <Archive className="h-3.5 w-3.5 shrink-0 text-amber-400/70" aria-hidden />
              <span className="flex-1 truncate">归档（{archivedSessions.length}）</span>
            </button>
            {archivedOpen && (
              <div className="max-h-44 space-y-1 overflow-y-auto px-3 pb-2.5 text-xs">
                {archivedSessions.map((s) => (
                  <div
                    key={s.id}
                    className={cn(
                      "group flex cursor-pointer items-center gap-2 rounded-xl border p-2 transition-all",
                      s.id === currentId
                        ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                        : "border-transparent text-slate-500 hover:border-white/10 hover:bg-white/5 hover:text-slate-300",
                    )}
                    onClick={() => {
                      abortRef.current?.abort();
                      setStreaming(false);
                      setError(null);
                      setToolLog([]);
                      switchSession(s.id);
                    }}
                  >
                    <Inbox className="h-3.5 w-3.5 shrink-0 text-amber-400/60" aria-hidden />
                    <span className="flex-1 truncate font-medium">{s.name || "新对话"}</span>
                    <button
                      type="button"
                      aria-label="恢复会话"
                      title="取消归档"
                      className="opacity-0 transition-opacity hover:text-cyan-300 group-hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation();
                        archiveSession(s.id, false);
                      }}
                    >
                      <RotateCcw className="h-3 w-3" aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 底部画廊 & 会话数 */}
        <div className="space-y-2 border-t border-white/10 bg-slate-950/60 p-3">
          <button
            onClick={() => setShowGallery(true)}
            className="flex w-full items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 transition-colors hover:border-cyan-500/40 hover:text-cyan-300"
          >
            <span className="flex items-center gap-2">
              <FolderKanban className="h-4 w-4 text-cyan-400" aria-hidden /> 本次会话产出画廊
            </span>
            <span className="rounded-md bg-cyan-500/20 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
              {mediaItems.length} 项
            </span>
          </button>
          <p className="px-1 text-[10px] text-slate-500">共 {sessions.length} 个会话 · 本地保存</p>
        </div>
      </aside>

      {/* ============ 中央对话区 ============ */}
      <section className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col">
        {/* 顶部系统栏 */}
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-white/10 bg-slate-950/60 px-4 text-xs backdrop-blur">
          <div className="flex items-center gap-3">
            {/* v2 P1：模型选择器（catalog 直连，全局生效） */}
            <div className="flex items-center gap-1.5 rounded-xl border border-cyan-500/30 bg-slate-900 px-2.5 py-1 text-cyan-300">
              <Wrench className="h-3.5 w-3.5 text-cyan-400" aria-hidden />
              <span className="hidden font-medium sm:inline">模型:</span>
              <select
                value={chatModel}
                onChange={(e) => {
                  setChatModel(e.target.value);
                  localStorage.setItem("aigc-chat-model", e.target.value);
                }}
                className="max-w-[180px] cursor-pointer truncate bg-transparent font-mono text-[11px] font-semibold text-white outline-none [&>option]:bg-slate-900"
                title="切换对话模型（来自模型中心 catalog）"
              >
                {modelList.length === 0 && <option value={chatModel}>{chatModel}</option>}
                {modelList.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.healthy === false ? "（不可用）" : ""}
                  </option>
                ))}
              </select>
            </div>
            {/* 显示工具调用开关（真实控制） */}
            <div className="hidden items-center gap-2 sm:flex">
              <label
                className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-slate-900/80 px-2.5 py-1 text-[11px] text-cyan-300 transition-colors hover:bg-cyan-500/10"
              >
                <input
                  type="checkbox"
                  checked={showTools}
                  onChange={(e) => setShowTools(e.target.checked)}
                  className="h-3 w-3 rounded border-cyan-500 bg-slate-950 text-cyan-500 focus:ring-0"
                />
                <Wrench className="h-3 w-3 text-cyan-400" aria-hidden /> 显示工具调用
              </label>
            </div>
            <div className="hidden items-center gap-3 border-l border-white/10 pl-3 font-mono text-[11px] text-slate-400 md:flex">
              <span>提问: <strong className="text-slate-200">{qCount}</strong></span>
              <span>产出: <strong className="text-cyan-400">{mediaItems.length}</strong></span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {mediaItems.length > 0 && (
              <button
                onClick={() => setShowGallery(true)}
                className="rounded-lg px-2 py-1 text-[11px] text-cyan-400 transition-colors hover:bg-cyan-500/10"
              >
                🖼️ 查看产出（{mediaItems.length}）
              </button>
            )}
            {messages.length > 0 && (
              <button
                onClick={() => {
                  if (confirm("清空当前对话？此操作不可撤销。")) {
                    if (currentId) {
                      deleteSession(currentId);
                      createSession();
                    }
                  }
                }}
                title="清空对话"
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-rose-500/20 hover:text-rose-300"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              </button>
            )}
            <a
              href={`${window.location.pathname.startsWith("/saios") ? "/saios" : ""}/login`}
              title="返回首页"
              className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-slate-300 transition-all hover:border-cyan-500/40 hover:text-cyan-300"
            >
              <Home className="h-3.5 w-3.5" aria-hidden /> <span className="hidden lg:inline">返回首页</span>
            </a>
          </div>
        </div>

        {/* 消息滚动区 */}
        <div className="ai-scroll flex-1 space-y-6 overflow-y-auto px-4 pb-40 pt-4 lg:px-6">
          {empty ? (
            <div className="mx-auto max-w-3xl space-y-8 py-4">
              {/* 欢迎态 */}
              {/* v3 系统启动横幅 */}
              <div className="ai-glass flex items-start gap-3 rounded-2xl border border-cyan-500/20 p-4 text-xs text-slate-300 shadow-lg">
                <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-400">
                  <Sparkles className="h-4 w-4" aria-hidden />
                </div>
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-white">AI 调度大厅已就绪</span>
                    <span className="rounded bg-cyan-500/20 px-2 py-0.5 font-mono text-[10px] text-cyan-300">
                      工具调用 · 已启用
                    </span>
                  </div>
                  <p className="leading-relaxed text-slate-400">
                    直接输入想法派活；用 / 调命令、@ 引用资料。我可以帮你生图、写文、配音与创作故事。
                  </p>
                </div>
              </div>

              <div className="space-y-3 text-center">
                <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3.5 py-1.5 text-xs font-medium text-cyan-300">
                  <Sparkles className="h-4 w-4 animate-pulse" aria-hidden />
                  {sessions.length > 0
                    ? <>欢迎回来，上次在聊「{sessions[0] && !sessions[0].name?.startsWith("新") ? sessions[0].name : "新想法"}」</>
                    : "你好，我是你的 AI 助手"}
                </div>
                <h1 className="text-3xl font-black tracking-tight text-white sm:text-4xl">
                  今天你想<span className="ai-grad-text">创造什么</span>？
                </h1>
                <p className="mx-auto max-w-xl text-xs leading-relaxed text-slate-400 sm:text-sm">
                  输入自然语言，驱动生图、写文、写歌、连续漫画与角色演练。
                </p>
              </div>

              {/* 能力卡网格 */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {CAPABILITY_GROUPS.map((g) => (
                  <button
                    key={g.title}
                    onClick={() => useSuggestion(g.items[0]!.prompt)}
                    className={cn(
                      "ai-glass group rounded-2xl border p-4 text-left transition-all hover:-translate-y-0.5",
                      capAccent(g.accent),
                    )}
                  >
                    <div className="mb-2.5 flex h-8 w-8 items-center justify-center rounded-xl bg-white/10 text-lg transition-transform group-hover:scale-110">
                      {g.icon}
                    </div>
                    <div className={cn("text-xs font-bold text-white", capAccent(g.accent))}>{g.icon} {g.title}</div>
                    <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">
                      {g.items.map((it) => it.label).join(" · ")}
                    </p>
                  </button>
                ))}
              </div>

              {/* 最近作品 */}
              {recentWorks.length > 0 && (
                <div className="ai-glass space-y-3 rounded-2xl border border-white/10 p-4">
                  <div className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 font-bold text-white">
                      <Sparkles className="h-3.5 w-3.5 text-cyan-400" aria-hidden /> 最近生成
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-2.5">
                    {recentWorks.slice(0, 8).map((w) => {
                      const thumb = w.task_type === "comic" ? w.cover_url : w.asset_url;
                      const label = w.task_type === "comic" ? "漫画" : w.task_type === "audio" || w.task_type === "music" ? "音频" : "生图";
                      const grad = [
                        "linear-gradient(135deg,#0e7490,#1e3a8a)",
                        "linear-gradient(135deg,#7c3aed,#0e7490)",
                        "linear-gradient(135deg,#059669,#1e3a8a)",
                        "linear-gradient(135deg,#b45309,#7c3aed)",
                      ][w.task_type.length % 4];
                      return (
                        <a
                          key={w.id}
                          href="/assets"
                          title={w.title || w.prompt || "AI 作品"}
                          className="group relative h-20 cursor-pointer overflow-hidden rounded-xl border border-white/10 bg-slate-900"
                        >
                          <div className="absolute inset-0" style={{ background: grad }} />
                          {thumb && (
                            <img
                              src={thumb}
                              alt={w.title || "AI 生成"}
                              loading="lazy"
                              className="relative h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                              onError={(e) => {
                                e.currentTarget.style.opacity = "0";
                              }}
                            />
                          )}
                          <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 font-mono text-[9px] text-cyan-300 backdrop-blur">
                            {label}
                          </span>
                        </a>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* 消息流 */}
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex",
                    m.role === "user" ? "flex-col items-end" : "items-start gap-3",
                  )}
                >
                  {m.role === "assistant" && (
                    <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-500/40 bg-slate-900 text-cyan-400 shadow-[0_0_25px_rgba(0,242,254,0.25)]">
                      <Bot className="h-4 w-4" aria-hidden />
                    </div>
                  )}
                  <div
                    className={cn(
                      "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed sm:max-w-[75%]",
                      m.role === "user"
                        ? "ai-bubble-user rounded-tr-sm"
                        : "ai-bubble-ai rounded-tl-sm",
                    )}
                  >
                    {m.role === "assistant" && m.thinking && <ThinkBlock text={m.thinking} />}
                    {m.role === "user" && i === editingIdx ? (
                      <div className="max-w-md">
                        <textarea
                          value={editVal}
                          onChange={(e) => setEditVal(e.target.value)}
                          rows={Math.max(2, Math.ceil(editVal.length / 40))}
                          className="ai-glass-input w-full resize-y rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                        />
                        <div className="mt-2 flex gap-2">
                          <button
                            onClick={() => {
                              const v = editVal.trim();
                              setEditingIdx(null);
                              if (v) void send(v, i);
                            }}
                            disabled={!editVal.trim() || streaming}
                            className="ai-glow-btn rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-950"
                          >
                            编辑重发
                          </button>
                          <button
                            onClick={() => setEditingIdx(null)}
                            className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300"
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : m.dispatch ? (
                      <div className="w-full max-w-md rounded-2xl border border-cyan-500/30 bg-cyan-500/5 p-4">
                        <p className="flex items-center gap-2 text-xs font-bold text-cyan-300">
                          ⚡ 已解析派发指令 ·{" "}
                          {m.dispatch.kind === "image"
                            ? "图像引擎"
                            : m.dispatch.kind === "comic"
                              ? "漫画引擎"
                              : m.dispatch.kind === "music"
                                ? "音乐引擎"
                                : "语音引擎"}
                        </p>
                        <p className="mt-2 rounded-lg bg-slate-950/60 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-200">
                          {m.dispatch.args}
                        </p>
                        <button
                          onClick={() =>
                            navigate(
                              `${window.location.pathname.startsWith("/saios") ? "/saios" : ""}${m.dispatch!.target}?prompt=${encodeURIComponent(m.dispatch!.args)}`,
                            )
                          }
                          className="mt-3 w-full rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-600 py-2 text-xs font-bold text-slate-950 transition-transform hover:scale-[1.02] active:scale-95"
                        >
                          🚀 推送到引擎渲染
                        </button>
                      </div>
                    ) : m.image ? (
                      m.media === "audio" ? (
                        <div className="w-full max-w-sm">
                          <p className="mb-1.5 flex items-center gap-2 text-xs text-slate-400">
                            <span>🔊 AI 语音</span>
                            <button
                              onClick={() => {
                                const prompt = [...messages.slice(0, i)]
                                  .reverse()
                                  .find((x) => x.role === "user")?.content;
                                if (prompt) void send(prompt);
                              }}
                              className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-300 hover:bg-cyan-500/20"
                            >
                              🔄 再生成
                            </button>
                          </p>
                          <audio controls src={m.image} className="w-full" />
                        </div>
                      ) : (
                        <div className="max-w-full">
                          <img
                            src={m.image}
                            alt={m.media === "comic" ? "AI 漫画" : "AI 生成"}
                            className="max-h-96 w-full rounded-xl border border-white/10 object-cover"
                          />
                          <div className="mt-1.5 flex items-center gap-2">
                            <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] text-slate-300">
                              {m.media === "comic" ? "🎴 AI 漫画" : "🖼️ AI 生成"}
                            </span>
                            <a
                              href={m.image}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-300 hover:bg-cyan-500/20"
                            >
                              ⬇ 下载 / 查看
                            </a>
                            <button
                              onClick={() => {
                                const prompt = [...messages.slice(0, i)]
                                  .reverse()
                                  .find((x) => x.role === "user")?.content;
                                if (prompt) void send(prompt);
                              }}
                              className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-300 hover:bg-cyan-500/20"
                            >
                              🔄 再生成
                            </button>
                          </div>
                        </div>
                      )
                    ) : m.role === "assistant" && m.content ? (
                      <MarkdownContent content={m.content} />
                    ) : (
                      <span className="whitespace-pre-wrap text-slate-300">{m.content || "思考中…"}</span>
                    )}
                    {m.role === "assistant" && !!m.toolCalls?.length && (
                      <ToolCallsBlock calls={m.toolCalls} />
                    )}
                    {m.role === "assistant" && !!m.content && !(streaming && i === messages.length - 1) && (
                      <AssistantMsgActions
                        sessionId={currentId}
                        idx={i}
                        text={m.content}
                        onBranch={() => branchSession(messages, i)}
                      />
                    )}
                  </div>
                  {m.role === "user" && i !== editingIdx && (
                    <button
                      onClick={() => {
                        setEditingIdx(i);
                        setEditVal(m.content);
                      }}
                      className="mt-1 flex items-center gap-1 pr-1 text-[11px] text-slate-500 hover:text-slate-200"
                    >
                      ✏️ 编辑此问题
                    </button>
                  )}
                </div>
              ))}

              {/* 工具调用过程（受顶部开关控制） */}
              {showTools && toolLog.length > 0 && (
                <div className="flex flex-col items-start gap-2">
                  {toolLog.map((t) => (
                    <div
                      key={t.name + t.status}
                      className="ai-glass w-full max-w-2xl overflow-hidden rounded-xl border border-cyan-500/30 text-xs"
                      style={{ borderLeft: "2px solid rgba(0,242,254,.6)" }}
                    >
                      <div className="flex items-center justify-between bg-slate-950/80 px-3.5 py-2.5 font-mono text-cyan-300">
                        <div className="flex items-center gap-2">
                          {t.status === "done" ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-hidden />
                          ) : (
                            <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
                          )}
                          <span className="font-semibold">🛠️ 已调用工具: {t.name}</span>
                        </div>
                        <span
                          className={
                            t.status === "done"
                              ? "rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300"
                              : "rounded bg-cyan-500/20 px-2 py-0.5 text-[10px] text-cyan-300"
                          }
                        >
                          {t.status === "done" ? "✓ 完成" : "⏳ 执行中…"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* ============ 底部输入区 ============ */}
        <div className="absolute inset-x-0 bottom-0 z-20 px-4 pb-5 lg:px-6">
          <div className="ai-input-shell mx-auto max-w-3xl">
            <div className="ai-input-inner">
            {/* 斜杠命令建议面板 */}
            {showCmds && (
              <div className="ai-glass absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-xl border border-white/10">
                {COMMANDS.filter((c) => c.cmd.startsWith(input.toLowerCase()) || input === "/").map(
                  (c) => (
                    <button
                      key={c.cmd}
                      type="button"
                      onClick={() => {
                        setInput(c.prompt);
                        setShowCmds(false);
                      }}
                      className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-cyan-500/10"
                    >
                      <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 text-xs font-medium text-cyan-300">
                        {c.cmd}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-slate-100">{c.label}</span>
                        <span className="block truncate text-[11px] text-slate-500">{c.desc}</span>
                      </span>
                    </button>
                  ),
                )}
              </div>
            )}

            {error && (
              <p className="mb-2 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/15 px-3 py-2 text-sm text-rose-300" role="alert">
                <span>⚠️</span> {error}
              </p>
            )}

            {/* 能力快捷按钮排 */}
            <div className="flex flex-wrap items-center gap-1.5 px-2 pb-2">
              <span className="pr-1 text-[10px] uppercase tracking-wider text-slate-500">能力</span>
              {CAPABILITY_GROUPS.map((g) => (
                <button
                  key={g.title}
                  type="button"
                  onClick={() => useSuggestion(g.items[0]!.prompt)}
                  className={cn(
                    "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-all hover:-translate-y-0.5",
                    capAccent(g.accent),
                  )}
                >
                  <span>{g.icon}</span> {g.title}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setShowCaps(true)}
                className="flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-slate-400 transition-all hover:-translate-y-0.5 hover:border-cyan-500/40 hover:text-cyan-300"
              >
                <Wand2 className="h-3 w-3" aria-hidden /> 全部能力
              </button>
            </div>

            <div className="flex items-end gap-2 px-1 pb-1">
              <div className="relative flex-1" ref={inputWrapRef}>
                {/* @ 资源引用面板 */}
                {showAt && (
                  <div className="ai-glass absolute bottom-full left-0 right-0 z-20 mb-2 max-h-72 overflow-y-auto rounded-xl border border-white/10">
                    <p className="flex items-center gap-1.5 px-3.5 pt-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      <span>@</span> 引用资源
                      <span className="normal-case text-slate-600">
                        {atBusy ? " · 搜索中…" : atQuery.trim() ? ` · “${atQuery.trim()}”` : ""}
                      </span>
                    </p>
                    {/* 动态搜索结果（前 8 条） */}
                    {atQuery.trim() && !atBusy && atResults.length === 0 && (
                      <p className="px-3.5 py-2 text-[11px] text-slate-500">没有找到匹配的资源，可引用下方常用分类</p>
                    )}
                    {atResults.map((r) => (
                      <button
                        key={`${r.scope}-${r.id}`}
                        type="button"
                        onClick={() => insertAt(r)}
                        className="flex w-full items-start gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-cyan-500/10"
                      >
                        <span className="mt-0.5 shrink-0 rounded bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                          {AT_SCOPE_LABEL[r.scope] ?? r.scope}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-slate-100">{r.title}</span>
                          {r.snippet && (
                            <span className="block truncate text-[11px] text-slate-500">{r.snippet}</span>
                          )}
                        </span>
                        <span className="shrink-0 text-[10px] text-slate-600">@ 引用</span>
                      </button>
                    ))}
                    {/* 静态分类入口（支持输入过滤） */}
                    <p className="px-3.5 pt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      常用资源
                    </p>
                    {AT_RESOURCES.filter(
                      (r) =>
                        !atQuery.trim() ||
                        r.label.toLowerCase().includes(atQuery.trim().toLowerCase()) ||
                        r.desc.toLowerCase().includes(atQuery.trim().toLowerCase()),
                    ).map((r) => (
                      <button
                        key={r.kind}
                        type="button"
                        onClick={() => insertToken(r.label)}
                        className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left transition-colors hover:bg-cyan-500/10"
                      >
                        <span className="text-base">{r.icon}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-slate-100">{r.label}</span>
                          <span className="block truncate text-[11px] text-slate-500">{r.desc}</span>
                        </span>
                        <span className="shrink-0 text-[10px] text-slate-600">
                          {r.to ? "🔗" : "@ 引用"}
                        </span>
                      </button>
                    ))}
                  </div>
                )}

                {/* v2 P1：已挂载的 @ 引用 chips（发送时内容真注入 context_blocks，可移除） */}
                {atRefs.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 px-2 pb-1.5 pt-1">
                    {atRefs.map((r) => (
                      <span
                        key={`${r.scope}-${r.id}`}
                        className="flex items-center gap-1 rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200"
                        title={r.snippet}
                      >
                        <span className="opacity-70">{AT_SCOPE_LABEL[r.scope] ?? r.scope}</span>
                        <span className="max-w-[120px] truncate font-medium">@{r.title}</span>
                        <button
                          type="button"
                          aria-label={`移除引用 ${r.title}`}
                          onClick={() => setAtRefs((prev) => prev.filter((x) => x.id !== r.id))}
                          className="ml-0.5 text-cyan-400 hover:text-white"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500">💬</span>
                <Textarea
                  value={input}
                  onChange={(e) => handleInputChange(e.target.value)}
                  rows={1}
                  autoFocus={empty}
                  placeholder={
                    empty
                      ? "输入 / 选择能力 · @ 引用资源"
                      : "继续对话，或换一个想法…（/ 选择能力 · @ 引用资源）"
                  }
                  disabled={streaming}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setShowAt(false);
                      setShowCmds(false);
                      setAtQuery("");
                      return;
                    }
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      setShowAt(false);
                      setShowCmds(false);
                      setAtQuery("");
                      void send();
                    }
                  }}
                  className="max-h-40 min-h-[48px] w-full flex-1 resize-none border-none bg-transparent px-2 py-3 pl-9 text-sm text-slate-100 outline-none placeholder:text-slate-500"
                />
              </div>
              {streaming ? (
                <button
                  onClick={stop}
                  aria-label="停止"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-300 transition-all hover:bg-rose-500/20 hover:text-rose-300"
                >
                  <Square className="h-4 w-4" aria-hidden />
                </button>
              ) : (
                <>
                  {/* v2 P1：Prompt Magic Polish——AI 润色输入框中的创作需求 */}
                  <button
                    onClick={() => void polishInput()}
                    disabled={!input.trim() || polishing}
                    aria-label="AI 润色"
                    title="AI 润色：把当前输入改写得更清晰具体"
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-purple-500/30 bg-purple-500/10 text-purple-300 transition-all hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    <Wand2 className={cn("h-4 w-4", polishing && "animate-spin")} aria-hidden />
                  </button>
                  <button
                    onClick={() => void send()}
                    disabled={!input.trim()}
                    aria-label="发送"
                    className="ai-send-btn flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-slate-950 transition-all hover:-translate-y-0.5 hover:shadow-[0_0_25px_rgba(0,242,254,0.5)] disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:translate-y-0 disabled:hover:shadow-none"
                  >
                    <Send className="h-4 w-4" aria-hidden />
                  </button>
                </>
              )}
            </div>

            <div className="flex items-center justify-between px-2 pb-1 pt-1.5">
              <span className="text-[11px] text-slate-500">
                可以让我：生图 🎨 写文 ✍️ 写歌 🎵 语音 🔊 故事 📖
              </span>
              <div className="flex items-center gap-3">
                <span className="hidden font-mono text-[10px] text-slate-600 sm:inline">
                  Enter 发送 · Shift+Enter 换行
                </span>
                {messages.length > 0 && (
                  <button
                    onClick={newChat}
                    className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-200"
                  >
                    <Eraser className="mr-1 inline h-3.5 w-3.5" aria-hidden /> 新对话
                  </button>
                )}
              </div>
            </div>
          </div>
          </div>
        </div>
      </section>

      {/* 页面私有样式 */}
      <style>{`
        .ai-page{background:#05070c;background-image:
          linear-gradient(to right, rgba(255,255,255,0.02) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255,255,255,0.02) 1px, transparent 1px);
          background-size:40px 40px;}
        .ai-glass{background:rgba(10,15,26,0.7);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);box-shadow:0 16px 40px rgba(0,0,0,0.5)}
        .ai-glass-input{background:rgba(15,23,42,0.7);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);transition:all .25s cubic-bezier(.4,0,.2,1)}
        .ai-glass-input:focus-within{border-color:rgba(0,242,254,.6)!important;box-shadow:0 0 22px rgba(0,242,254,.25),inset 0 0 10px rgba(0,242,254,.05)}
        .ai-bubble-user{background:linear-gradient(135deg,rgba(0,242,254,.15) 0%,rgba(79,172,254,.1) 100%);border:1px solid rgba(0,242,254,.3);backdrop-filter:blur(16px);color:#f1f5f9}
        .ai-bubble-ai{background:rgba(15,23,42,.75);border:1px solid rgba(255,255,255,.09);backdrop-filter:blur(16px);color:#e2e8f0}
        .ai-glow-btn{background:linear-gradient(135deg,#00f2fe 0%,#4facfe 50%,#9d4edd 100%);background-size:200% 200%;animation:aiShift 4s ease infinite;transition:all .3s ease}
        .ai-glow-btn:hover{box-shadow:0 0 25px rgba(0,242,254,.5),0 0 10px rgba(157,78,221,.3)}
        .ai-send-btn{background:linear-gradient(135deg,#00f2fe 0%,#4facfe 50%,#9d4edd 100%);background-size:200% 200%;animation:aiShift 4s ease infinite;transition:all .3s ease}
        .ai-input-shell{position:relative;border-radius:18px;background:linear-gradient(135deg,rgba(0,242,254,.28),rgba(157,78,221,.22) 45%,rgba(0,242,254,.18)) padding-box,linear-gradient(135deg,rgba(0,242,254,.5),rgba(157,78,221,.4),rgba(0,242,254,.35)) border-box;border:1px solid transparent;padding:1px;box-shadow:0 0 24px rgba(0,242,254,.12),0 16px 40px rgba(0,0,0,.55);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
        .ai-input-shell:focus-within{box-shadow:0 0 34px rgba(0,242,254,.28),0 16px 44px rgba(0,0,0,.6)}
        .ai-input-shell > .ai-input-inner{background:rgba(10,15,26,.85);border-radius:17px;padding:2px}
        @keyframes aiShift{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
        .ai-grad-text{background:linear-gradient(90deg,#fff 0%,#00f2fe 35%,#a855f7 70%,#fff 100%);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;animation:aiShimmer 6s linear infinite}
        @keyframes aiShimmer{to{background-position:-200% center}}
        .ai-glow-cyan{position:fixed;width:600px;height:600px;background:radial-gradient(circle,rgba(0,242,254,.12) 0%,transparent 70%);border-radius:50%;pointer-events:none;z-index:0}
        .ai-glow-purple{position:fixed;width:700px;height:700px;background:radial-gradient(circle,rgba(157,78,221,.12) 0%,transparent 70%);border-radius:50%;pointer-events:none;z-index:0}
        .ai-scroll::-webkit-scrollbar{width:5px;height:5px}
        .ai-scroll::-webkit-scrollbar-track{background:rgba(5,7,12,.9)}
        .ai-scroll::-webkit-scrollbar-thumb{background:rgba(255,255,255,.15);border-radius:4px}
        .ai-scroll::-webkit-scrollbar-thumb:hover{background:rgba(0,242,254,.4)}
      `}</style>
    </div>
  );
}

/** v2 批7：思维链折叠行（🧠 思考过程 + 单行摘要，点击展开全文）。
 * 2026-09-01：摘要改取「倒数第一个 8-64 字的实质行」——gpt-oss 的思考首句常是
 * 需求复述（与用户输入重复），摘要取结论性短行信息量更高；展开态隐藏摘要避免复读观感。 */
function ThinkBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const lines = text.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  const summary =
    [...lines].reverse().find((l) => l.length >= 8 && l.length <= 64) ??
    lines[lines.length - 1] ??
    "";
  const trimmed = summary.length > 64 ? `${summary.slice(0, 64)}…` : summary;
  return (
    <div className="mb-2 rounded-xl border border-indigo-500/25 bg-indigo-500/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-indigo-300 hover:text-indigo-200"
      >
        <span aria-hidden>🧠</span>
        <span className="font-medium">思考过程</span>
        {!open && trimmed && (
          <span className="min-w-0 flex-1 truncate text-indigo-400/70">{trimmed}</span>
        )}
        <span className="shrink-0 text-indigo-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto whitespace-pre-wrap border-t border-indigo-500/20 px-3 py-2 text-xs leading-relaxed text-slate-300">
          {text}
        </div>
      )}
    </div>
  );
}

/** v2 批7：工具调用留痕折叠行（回答结束后仍可回看本轮用了哪些工具）。 */
function ToolCallsBlock({ calls }: { calls: { name: string; status: "running" | "done" }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] text-cyan-400/80 hover:text-cyan-300"
      >
        <span aria-hidden>🛠️</span>
        本轮调用了 {calls.length} 个工具
        <span className="text-cyan-500/60">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-0.5">
          {calls.map((t, k) => (
            <li key={`${t.name}-${k}`} className="font-mono text-[10px] text-cyan-300/70">
              {t.status === "done" ? "✓" : "⏳"} {t.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const RATING_KEY = "aigc-msg-rating-v1";

function readRating(sessionId: string | null, idx: number): "up" | "down" | null {
  if (!sessionId) return null;
  try {
    const raw = localStorage.getItem(RATING_KEY);
    if (!raw) return null;
    const map = JSON.parse(raw) as Record<string, string>;
    const v = map[`${sessionId}:${idx}`];
    return v === "up" || v === "down" ? v : null;
  } catch {
    return null;
  }
}

function writeRating(sessionId: string | null, idx: number, val: "up" | "down" | null) {
  if (!sessionId) return;
  try {
    const raw = localStorage.getItem(RATING_KEY);
    const map = (raw ? (JSON.parse(raw) as Record<string, string>) : {}) ?? {};
    const k = `${sessionId}:${idx}`;
    if (val === null) delete map[k];
    else map[k] = val;
    localStorage.setItem(RATING_KEY, JSON.stringify(map));
  } catch {
    /* 存储不可用静默降级 */
  }
}

/** v2 批7：AI 回答操作栏——复制 / 点赞点踩 / 在新会话中分支。 */
function AssistantMsgActions(props: {
  sessionId: string | null;
  idx: number;
  text: string;
  onBranch: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<"up" | "down" | null>(() =>
    readRating(props.sessionId, props.idx),
  );
  function toggleRate(val: "up" | "down") {
    const next = rating === val ? null : val;
    writeRating(props.sessionId, props.idx, next);
    setRating(next);
  }
  async function copy() {
    // 批14：统一走 lib/clipboard（http 公网直访 navigator.clipboard 为 undefined）
    const ok = await copyText(props.text);
    if (!ok) return; // 失败不给假反馈
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }
  const btn =
    "rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-200";
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <button type="button" onClick={() => void copy()} className={btn}>
        {copied ? "✓ 已复制" : "📋 复制"}
      </button>
      <button
        type="button"
        onClick={() => toggleRate("up")}
        title="好的回答"
        className={cn(btn, rating === "up" && "!bg-emerald-500/20 !text-emerald-300")}
      >
        👍 {rating === "up" ? "已赞" : ""}
      </button>
      <button
        type="button"
        onClick={() => toggleRate("down")}
        title="有问题的回答"
        className={cn(btn, rating === "down" && "!bg-rose-500/20 !text-rose-300")}
      >
        👎 {rating === "down" ? "已标记" : ""}
      </button>
      <button type="button" onClick={props.onBranch} className={btn} title="把到此为止的对话复制成一个新会话">
        🌿 分支新会话
      </button>
    </div>
  );
}

/** 侧栏会话「⋯」菜单：移动到分组 / 新建分组 / 取消分组 / 归档。fixed 定位 + 点击外部关闭。 */
function SessionMenu(props: {
  left: number;
  top: number;
  sessionId: string;
  currentGroup: string | undefined;
  groupNames: string[];
  onClose: () => void;
  onSetGroup: (group: string) => void;
  onNewGroup: () => void;
  onRemoveGroup: () => void;
  onArchive: () => void;
}) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  // 点击菜单外部关闭
  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        props.onClose();
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasGroup = !!props.currentGroup && props.currentGroup.trim().length > 0;
  return (
    <div
      ref={menuRef}
      onClick={(e) => e.stopPropagation()}
      className="ai-glass fixed z-50 w-44 overflow-hidden rounded-xl border border-white/10 py-1 text-left"
      style={{ left: props.left, top: props.top }}
    >
      {props.sessionId && (
        <>
          <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            移动到分组
          </p>
          <div className="max-h-36 overflow-y-auto">
            {props.groupNames.map((g) => {
              const active = props.currentGroup === g;
              return (
                <button
                  key={g}
                  type="button"
                  onClick={() => props.onSetGroup(g)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-cyan-500/10",
                    active ? "text-cyan-300" : "text-slate-300",
                  )}
                >
                  <span className={cn("text-[10px]", active ? "text-cyan-300" : "text-slate-600")}>
                    {active ? "●" : "○"}
                  </span>
                  <span className="truncate">{g}</span>
                </button>
              );
            })}
            {props.groupNames.length === 0 && (
              <p className="px-3 py-1 text-[11px] text-slate-600">还没有分组</p>
            )}
          </div>
          <button
            type="button"
            onClick={props.onNewGroup}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-cyan-300 transition-colors hover:bg-cyan-500/10"
          >
            <FolderPlus className="h-3.5 w-3.5" aria-hidden /> 新建分组
          </button>
          {hasGroup && (
            <button
              type="button"
              onClick={props.onRemoveGroup}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-slate-300 transition-colors hover:bg-white/5"
            >
              <X className="h-3.5 w-3.5 text-slate-500" aria-hidden /> 取消分组
            </button>
          )}
          <div className="my-1 border-t border-white/10" />
          <button
            type="button"
            onClick={props.onArchive}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-amber-300 transition-colors hover:bg-amber-500/10"
          >
            <Archive className="h-3.5 w-3.5" aria-hidden /> 归档会话
          </button>
        </>
      )}
    </div>
  );
}
