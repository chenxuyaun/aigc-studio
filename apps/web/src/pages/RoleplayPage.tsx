import { useEffect, useState } from "react";

import {
  BookOpen,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  GitBranch,
  PenLine,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  SlidersHorizontal,
  Trash2,
  Users,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Dialog } from "@/components/ui/Dialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { useAuthStore } from "@/stores/auth";
import { apiClient } from "@/lib/apiClient";
import { useToast } from "@/components/ui/Toast";
import { copyText } from "@/lib/clipboard";

import { useRoleplayEngine } from "@/pages/roleplay/useRoleplayEngine";
import { CharacterPanel } from "@/pages/roleplay/CharacterPanel";
import { LorePanel } from "@/pages/roleplay/LorePanel";
import { CardMarketPanel } from "@/pages/roleplay/CardMarketPanel";
import { RegexPanel } from "@/pages/roleplay/RegexPanel";
import { SettingsPanel } from "@/pages/roleplay/SettingsPanel";
import { MemoryPanel } from "@/pages/roleplay/MemoryPanel";
import { StatusBookPanel } from "@/pages/roleplay/StatusBookPanel";
import { DEFAULT_MODEL } from "@/lib/constants";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { SessionSidebar } from "@/pages/roleplay/SessionSidebar";
import { estimateTokens } from "@/pages/roleplay/types";

interface GroupMember {
  user_id: string;
  username: string;
  role: string;
}
interface GroupInfo {
  chat_id: string;
  name: string;
  description: string;
  invite_code: string;
  owner_id: string;
  members: GroupMember[];
}

export function RoleplayPage() {
  useEffect(
    () => () => {
      if (roomPollRef.current != null) window.clearInterval(roomPollRef.current);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const authUser = useAuthStore((s) => s.user);
  const { error: toastError, success: toastSuccess } = useToast();

  const {
    characters, selected, groupMode, isRoom, authorName, groupIds, groupStrategy,
    groupModeType, affinity, input, model, modelCatalog, busy, streamingText,
    sessionId, refreshTick, messages, temperature, maxTokens, personas, personaId,
    quickReplies, noteContent, noteInterval, promptTokens, msgSearch, autoMode,
    autoInterval, rightTab, charSearch, bottomRef, roomPollRef,
    setGroupIds, setCharSearch, setIsRoom, setAuthorName, setGroupStrategy, setGroupModeType,
    setPersonaId, setNoteContent, setNoteInterval, setMsgSearch, setAutoMode,
    setAutoInterval, setRightTab, setInput, setGroupMode, setModel,
    groupName, setGroupName, groupDesc, setGroupDesc,
    setTemperature, setMaxTokens, setSelected, setPersonas, setQuickReplies,
    loadCharacters, toggleShare, openSession, selectCharacter, toggleGroupMember,
    send, swipeReply, switchSwipe, continueReply, removeMessage, branchChat,
    clearChat, newSession, deleteSession, charsForBinding, expandQuickMacros,
  } = useRoleplayEngine();
  const charDisplayName = selected?.name ?? "";
  const [groupInfo, setGroupInfo] = useState<GroupInfo | null>(null);
  const [groupInfoOpen, setGroupInfoOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  // v2 高级抽屉（世界书/正则/记忆/设置）
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedTab, setAdvancedTab] = useState<"lore" | "regex" | "memory" | "settings">("lore");
  const [stOpen, setStOpen] = useState(false);

  const kickMember = async (uid: string) => {
    if (!groupInfo) return;
    try {
      await apiClient.del(`/roleplay/groups/${groupInfo.chat_id}/members/${uid}`);
      setGroupInfo({
        ...groupInfo,
        members: groupInfo.members.filter((m) => m.user_id !== uid),
      });
    } catch (e) {
      toastError(e instanceof Error ? e.message : "操作失败");
    }
  };

  const publishWork = async () => {
    if (!groupInfo || publishing) return;
    setPublishing(true);
    try {
      const res = await apiClient.post<{
        project_id: string;
        chapter_id: string;
        project_title: string;
        error?: string;
      }>("/creation/publish", { chat_id: groupInfo.chat_id });
      if (res.error) {
        toastError(res.error);
        return;
      }
      toastSuccess(`《${res.project_title}》已存入创作工作室`);
      setGroupInfoOpen(false);
    } catch (e) {
      toastError(e instanceof Error ? e.message : "存档失败");
    } finally {
      setPublishing(false);
    }
  };

  const openGroupInfo = async (cid: string) => {
    try {
      const res = await apiClient.get<GroupInfo>(`/roleplay/groups/${cid}`);
      setGroupInfo(res);
      setGroupInfoOpen(true);
    } catch {
      /* 非群会话忽略 */
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="角色扮演"
        description="角色卡 / 世界书 / 会话 / 宏 / 情绪 / 好感度 · 兼容 SillyTavern"
        actions={
          <Button variant="outline" onClick={() => setStOpen((v) => !v)}>
            <ExternalLink className="h-4 w-4" aria-hidden />
            SillyTavern 接入
          </Button>
        }
      />

      {/* v2：SillyTavern 独立页并入此引导卡（环境自适应地址 + 网关 token） */}
      {stOpen && <StGuideCard />}

      <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)_300px]">
        {/* 左栏：角色卡 + 会话 */}
        <div className="space-y-5">
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-zen">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Bot className="h-4 w-4 text-primary-text" aria-hidden />
                角色卡
              </h3>
              <a
                href="/create/character-card"
                className="inline-flex min-h-[32px] items-center gap-1 rounded-lg px-1.5 text-xs text-primary-text transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden />
                生成新卡
              </a>
            </div>
            <label className="flex min-h-[32px] cursor-pointer items-center gap-2 px-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={groupMode}
                onChange={(e) => setGroupMode(e.target.checked)}
              />
              群聊模式（多选角色同场）
            </label>
            <label className="flex min-h-[32px] cursor-pointer items-center gap-2 px-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={isRoom}
                onChange={(e) => setIsRoom(e.target.checked)}
              />
              多人房间（全员可见可加入）
            </label>
            {isRoom && (
              <div className="mb-2 flex flex-col gap-2">
                <input
                  value={authorName}
                  onChange={(e) => setAuthorName(e.target.value)}
                  placeholder="你的身份名（如：陈满堂）"
                  className="h-10 w-full rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <input
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  placeholder="群名（如：双城之夜剧组）"
                  className="h-10 w-full rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <input
                  value={groupDesc}
                  onChange={(e) => setGroupDesc(e.target.value)}
                  placeholder="群简介（可选）"
                  className="h-10 w-full rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            )}
            {groupMode && (
              <div className="mb-2 flex flex-wrap items-center gap-1.5 px-1 text-[11px] text-muted-foreground">
                轮流
                <select
                  value={groupStrategy}
                  onChange={(e) => setGroupStrategy(e.target.value as typeof groupStrategy)}
                  className="h-10 min-w-0 flex-1 rounded-xl border border-input bg-surface px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="natural">自然（模型自选）</option>
                  <option value="list">按序轮流</option>
                  <option value="random">随机指定</option>
                </select>
                注入
                <select
                  value={groupModeType}
                  onChange={(e) => setGroupModeType(e.target.value as typeof groupModeType)}
                  className="h-10 min-w-0 flex-1 rounded-xl border border-input bg-surface px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="append">全员卡片</option>
                  <option value="swap">仅说话者</option>
                </select>
              </div>
            )}
            {groupMode && (
              <label className="flex min-h-[32px] cursor-pointer flex-wrap items-center gap-1.5 px-1 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={autoMode}
                  onChange={(e) => setAutoMode(e.target.checked)}
                />
                自动模式（角色定时接话）
                {autoMode && (
                  <input
                    type="number"
                    min={3}
                    max={60}
                    value={autoInterval}
                    onChange={(e) => setAutoInterval(Math.max(3, Number(e.target.value) || 8))}
                    className="h-8 w-14 rounded-lg border border-input bg-surface px-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                )}
                {autoMode && <span>秒/轮</span>}
              </label>
            )}
            <Input
              value={charSearch}
              onChange={(e) => setCharSearch(e.target.value)}
              placeholder="搜索角色…"
              className="mb-2"
            />
            <div className="max-h-72 space-y-1.5 overflow-y-auto">
              {characters
                .filter((c) => {
                  const q = charSearch.trim().toLowerCase();
                  if (!q) return true;
                  return `${c.name ?? ""} ${c.filename}`.toLowerCase().includes(q);
                })
                .map((c) => (
                <div
                  key={c.asset_id}
                  className={`flex items-center gap-2 rounded-xl border p-2 transition-colors ${
                    selected?.asset_id === c.asset_id
                      ? "border-primary/30 bg-primary/10"
                      : "border-line hover:border-border-strong"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={groupIds.includes(c.asset_id)}
                    onChange={() => toggleGroupMember(c.asset_id)}
                  />
                  <button
                    onClick={() => selectCharacter(c)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <img
                      src={c.url}
                      alt=""
                      className="h-9 w-9 rounded-lg border border-border object-cover"
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {c.name || c.filename}
                        {c.is_shared && (
                          <span className="ml-1.5 inline-block rounded-full bg-primary/10 px-1.5 align-middle text-[11px] text-primary-text">
                            共享
                          </span>
                        )}
                      </span>
                      {authUser?.role === "admin" && (
                        <button
                          type="button"
                          onClick={() => void toggleShare(c)}
                          className="mt-0.5 inline-block rounded-lg border border-line px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/60 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          title={c.is_shared ? "取消共享（仅自己可见）" : "共享给所有用户"}
                        >
                          {c.is_shared ? "取消共享" : "共享"}
                        </button>
                      )}
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {c.filename}
                      </span>
                    </span>
                  </button>
                </div>
              ))}
              {characters.length === 0 && (
                <div className="px-3 py-6 text-center">
                  <p className="text-sm text-muted-foreground">还没有角色卡</p>
                  <a
                    href="/create/character-card"
                    className="mt-2 inline-flex h-10 items-center rounded-xl border border-primary/30 px-4 text-sm text-primary-text transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    去生成第一张角色卡
                  </a>
                </div>
              )}
              {characters.length > 0 &&
                characters.filter((c) => {
                  const q = charSearch.trim().toLowerCase();
                  return !q || `${c.name ?? ""} ${c.filename}`.toLowerCase().includes(q);
                }).length === 0 && (
                  <div className="px-3 py-6 text-center">
                    <p className="text-sm text-muted-foreground">没有匹配「{charSearch.trim()}」的角色</p>
                    <button
                      type="button"
                      onClick={() => setCharSearch("")}
                      className="mt-2 inline-flex h-10 items-center rounded-xl px-4 text-sm text-primary-text transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      清除搜索
                    </button>
                  </div>
                )}
            </div>
          </div>

          <div className="h-72 overflow-hidden rounded-2xl border border-line bg-surface shadow-zen">
            <SessionSidebar
              activeId={sessionId}
              refreshKey={refreshTick}
              onSelect={(s) => void openSession(s)}
              onCreated={newSession}
              onDeleted={deleteSession}
            />
          </div>
        </div>

        {/* 中栏：对话场 —— 气泡纸卡 */}
        <div className="flex min-h-[560px] flex-col rounded-2xl border border-line bg-surface shadow-zen">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <span className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-semibold">
              <span className="truncate">
                {selected ? `与 ${charDisplayName || selected.filename} 聊天` : "请选择角色"}
              </span>
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary-text">
                好感度 {affinity}
              </span>
              {sessionId && (
                <button
                  type="button"
                  className="inline-flex min-h-[32px] items-center gap-1 rounded-full bg-primary/10 px-2.5 text-xs text-primary-text transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => void openGroupInfo(sessionId)}
                >
                  <Users className="h-3.5 w-3.5" aria-hidden />
                  群信息
                </button>
              )}
            </span>
            <div className="flex items-center gap-3 text-xs">
              {messages.length > 0 && (
                <button
                  className="inline-flex min-h-[32px] items-center rounded-lg px-2 text-muted-foreground transition-colors hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => void clearChat()}
                >
                  清空对话
                </button>
              )}
              {busy && (
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <span
                    className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
                    aria-hidden
                  />
                  生成中…
                </span>
              )}
              <span className="text-[11px] text-muted-foreground">
                {promptTokens != null
                  ? `最近上下文 ${promptTokens} tok`
                  : `上下文 ≈ ${estimateTokens(messages.map((m) => m.content).join("\n"))} tok`}
              </span>
            </div>
          </div>

          {messages.length > 5 && (
            <div className="flex items-center gap-2 border-b border-line px-4 py-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <input
                value={msgSearch}
                onChange={(e) => setMsgSearch(e.target.value)}
                placeholder="搜索对话…"
                className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {msgSearch && (
                <button
                  className="inline-flex min-h-[32px] items-center rounded-lg px-2 text-[11px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setMsgSearch("")}
                >
                  清除
                </button>
              )}
            </div>
          )}
          <div className="bg-muted/30 flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && !streamingText && (
              <div className="py-14 text-center">
                <p className="text-sm text-muted-foreground">还没有对话</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  在下方说第一句话，会话会自动创建
                </p>
              </div>
            )}
            {messages
              .map((m, i) => ({ m, i }))
              .filter(({ m }) => {
                const q = msgSearch.trim().toLowerCase();
                if (!q) return true;
                return m.content.toLowerCase().includes(q);
              })
              .map(({ m, i }) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className="group min-w-0 max-w-[75%]">
                  <div
                    className={`break-words rounded-2xl px-4 py-3 text-sm ${
                      m.role === "user"
                        ? "border border-primary/30 bg-primary/10"
                        : "border border-line bg-surface shadow-zen"
                    }`}
                  >
                    {m.role === "assistant" && m.mood && (
                      <span className="mb-2 mr-1.5 inline-block rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {m.mood}
                      </span>
                    )}
                    {m.role === "assistant" ? (
                      <MarkdownContent content={m.content} />
                    ) : (
                      <span className="whitespace-pre-wrap">{m.content}</span>
                    )}
                  </div>
                  {/* 回复操作：swipe 切换 / 换一个 / 继续写 */}
                  {m.role === "assistant" && !busy && (
                    <div className="mt-1 flex flex-wrap items-center gap-1 px-1 opacity-100 md:opacity-0 md:group-hover:opacity-100">
                      {m.swipes && m.swipes.length > 1 && (
                        <span className="flex items-center text-[11px] text-muted-foreground">
                          <button
                            className="inline-flex h-8 items-center rounded-lg px-1.5 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            title="上一个"
                            onClick={() => switchSwipe(i, -1)}
                          >
                            <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                          </button>
                          {(m.swipeIndex ?? m.swipes.length - 1) + 1}/{m.swipes.length}
                          <button
                            className="inline-flex h-8 items-center rounded-lg px-1.5 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            title="下一个"
                            onClick={() => switchSwipe(i, 1)}
                          >
                            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </span>
                      )}
                      <button
                        className="inline-flex h-8 items-center gap-1 rounded-lg px-1.5 text-[11px] text-muted-foreground hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        title="生成另一个回复"
                        onClick={() => void swipeReply(i)}
                      >
                        <RefreshCw className="h-3 w-3" aria-hidden />
                        换一个
                      </button>
                      <button
                        className="inline-flex h-8 items-center gap-1 rounded-lg px-1.5 text-[11px] text-muted-foreground hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        title="继续写下去"
                        onClick={() => void continueReply(i)}
                      >
                        <PenLine className="h-3 w-3" aria-hidden />
                        继续写
                      </button>
                    </div>
                  )}
                  {m.role === "assistant" && !busy && (
                    <button
                      className="inline-flex h-8 items-center gap-1 rounded-lg px-1.5 text-[11px] text-muted-foreground opacity-100 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:opacity-0 md:group-hover:opacity-100"
                      title="删除这条消息"
                      onClick={() => void removeMessage(i)}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden />
                      删除
                    </button>
                  )}
                  <button
                    className="inline-flex h-8 items-center rounded-lg px-1.5 text-[11px] text-muted-foreground opacity-100 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:opacity-0 md:group-hover:opacity-100"
                    title="复制消息"
                    onClick={() => void copyText(m.content)}
                  >
                    复制
                  </button>
                  <button
                    className="inline-flex h-8 items-center gap-1 rounded-lg px-1.5 text-[11px] text-muted-foreground opacity-100 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:opacity-0 md:group-hover:opacity-100"
                    title="从这里分叉新会话"
                    onClick={() => void branchChat(i)}
                  >
                    <GitBranch className="h-3 w-3" aria-hidden />
                    分支
                  </button>
                </div>
              </div>
              ))}
            {streamingText && (
              <div className="flex justify-start">
                <div className="max-w-[75%] rounded-2xl border border-line bg-surface px-4 py-3 text-sm shadow-zen">
                  <MarkdownContent content={streamingText} />
                  <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-middle" aria-hidden />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* 快捷回复行 */}
          {quickReplies.length > 0 && (
            <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
              {quickReplies.map((q) => (
                <button
                  key={q.id}
                  disabled={busy || !selected}
                  onClick={() => setInput(expandQuickMacros(q.message, charDisplayName, personas.find((p) => p.id === personaId)?.name ?? "用户"))}
                  className="inline-flex min-h-[32px] items-center rounded-full border border-line px-3 text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:text-primary-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
                >
                  {q.label}
                </button>
              ))}
            </div>
          )}

          <div className="border-t border-line p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <label htmlFor="rp-model" className="shrink-0">
                模型
              </label>
              <select
                id="rp-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-10 min-w-0 flex-1 rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {modelCatalog.length > 0 ? (
                  modelCatalog.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))
                ) : (
                  <>
                    <option value={DEFAULT_MODEL}>GPT-OSS 120B（推荐，本地可用）</option>
                    <option value="grok-chat-fast">Grok 快模型（需 grok2api 账号配额）</option>
                  </>
                )}
              </select>
              <label className="shrink-0" htmlFor="rp-persona">
                身份
              </label>
              <select
                id="rp-persona"
                value={personaId}
                onChange={(e) => setPersonaId(e.target.value)}
                className="h-10 rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">默认（用户）</option>
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <details className="relative">
                <summary className="inline-flex min-h-[32px] cursor-pointer list-none items-center gap-1 rounded-lg px-2 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                  <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
                  参数
                </summary>
                <div className="absolute right-0 top-9 z-10 w-60 space-y-3 rounded-2xl border border-line bg-surface p-4 shadow-zen">
                  <label className="block text-sm">
                    温度 {temperature.toFixed(1)}
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={0.1}
                      value={temperature}
                      onChange={(e) => setTemperature(Number(e.target.value))}
                      className="mt-1 w-full accent-primary"
                    />
                  </label>
                  <label className="block text-sm">
                    最大回复 token
                    <input
                      type="number"
                      min={64}
                      max={8192}
                      step={64}
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(Number(e.target.value) || 1024)}
                      className="mt-1 h-10 w-full rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </label>
                </div>
              </details>
            </div>
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder={isRoom ? "@AI 写歌：主题 [风格]，群里一起写歌…" : "对角色说点什么…（{{char}}/{{user}} 宏可用）"}
                disabled={busy || !selected}
              />
              <Button onClick={() => void send()} disabled={busy || !selected} aria-label="发送">
                <Send className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
        </div>

        {/* 右栏：常用三页（角色卡/状态账本/卡库）；高级项收「高级」抽屉 */}
        <div className="rounded-2xl border border-line bg-surface p-4 shadow-zen">
          <div className="mb-3 flex flex-wrap items-center gap-1 text-xs">
            {(
              [
                ["character", "角色卡"],
                ["book", "状态账本"],
                ["market", "卡库"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setRightTab(key)}
                className={`min-h-[40px] rounded-full px-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  rightTab === key ? "bg-primary/10 text-primary-text" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
            <button
              onClick={() => setAdvancedOpen(true)}
              className={`ml-auto inline-flex min-h-[40px] items-center gap-1 rounded-full px-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                advancedOpen
                  ? "bg-primary/10 text-primary-text"
                  : "border border-line text-muted-foreground hover:border-primary/60 hover:text-foreground"
              }`}
              title="世界书 / 正则 / 记忆 / 设置"
            >
              <Settings2 className="h-3.5 w-3.5" aria-hidden />
              高级
            </button>
          </div>

          <div className="max-h-[540px] overflow-y-auto">
            {rightTab === "character" &&
              (selected ? (
                <CharacterPanel
                  assetId={selected.asset_id}
                  onSaved={() => void loadCharacters()}
                  onDeleted={() => {
                    setSelected(null);
                    setGroupIds([]);
                    void loadCharacters();
                  }}
                />
              ) : (
                <div className="py-8 text-center">
                  <p className="text-sm text-muted-foreground">还没有选择角色</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    在左侧角色卡列表里挑一张，这里就能编辑
                  </p>
                </div>
              ))}
            {rightTab === "book" && <StatusBookPanel chatId={sessionId} />}
            {rightTab === "market" && <CardMarketPanel />}
          </div>

          <div className="mt-4 border-t border-line pt-3">
            <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              宏：{"{{char}}"} {"{{user}}"} {"{{random::A::B}}"} {"{{roll::1d20}}"} {"{{time}}"}
            </p>
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <Wand2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              会话可导出为 SillyTavern JSONL，也可导入回放 · 世界书/正则/记忆在「高级」抽屉
            </p>
          </div>
        </div>
      </div>

      {/* v2 高级抽屉：世界书 / 正则 / 记忆 / 设置（从右栏七 tab 收敛） */}
      <Dialog open={advancedOpen} onClose={() => setAdvancedOpen(false)} title="高级设置" className="max-w-2xl">
        <div className="mb-3 flex flex-wrap gap-1 text-xs">
          {(
            [
              ["lore", "世界书"],
              ["regex", "正则"],
              ["memory", "记忆"],
              ["settings", "设置"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setAdvancedTab(key)}
              className={`min-h-[40px] rounded-full px-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                advancedTab === key
                  ? "bg-primary/10 text-primary-text"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="max-h-[60vh] overflow-y-auto pr-1">
          {advancedTab === "lore" && <LorePanel characterName={charsForBinding} />}
          {advancedTab === "regex" && <RegexPanel characterName={charsForBinding} />}
          {advancedTab === "memory" &&
            (selected ? (
              <MemoryPanel assetId={selected.asset_id} />
            ) : (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">还没有选择角色</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  在左侧角色卡列表里挑一张，再回来管理记忆
                </p>
              </div>
            ))}
          {advancedTab === "settings" && (
            <SettingsPanel
              noteContent={noteContent}
              noteInterval={noteInterval}
              onNoteChange={setNoteContent}
              onNoteIntervalChange={setNoteInterval}
              onPersonasChanged={setPersonas}
              onQuickRepliesChanged={setQuickReplies}
            />
          )}
        </div>
      </Dialog>
      <Dialog open={groupInfoOpen} onClose={() => setGroupInfoOpen(false)} title={groupInfo?.name ?? "群信息"}>
        {groupInfo && (
          <div className="space-y-4">
            {groupInfo.description && (
              <p className="text-sm text-muted-foreground">{groupInfo.description}</p>
            )}
            <div className="flex items-center gap-2 rounded-xl bg-muted/40 p-3">
              <span className="text-xs text-muted-foreground">邀请码</span>
              <code className="font-mono text-sm font-semibold">{groupInfo.invite_code}</code>
              <button
                type="button"
                className="ml-auto inline-flex min-h-[32px] items-center rounded-lg px-2 text-xs text-primary-text transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => void copyText(groupInfo.invite_code)}
              >
                复制
              </button>
            </div>
            <div>
              <p className="mb-2 text-sm font-semibold text-foreground">
                成员（{groupInfo.members.length}）
              </p>
              <ul className="space-y-1.5">
                {groupInfo.members.map((m: GroupMember) => (
                  <li key={m.user_id} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm">
                    <span className="min-w-0 truncate">{m.username}</span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                      {m.role === "owner" ? "群主" : "成员"}
                    </span>
                    {m.role !== "owner" && authUser?.id === groupInfo.owner_id && (
                      <button
                        type="button"
                        className="ml-auto inline-flex min-h-[32px] items-center rounded-lg px-2 text-xs text-danger transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => void kickMember(m.user_id)}
                      >
                        移出
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            <div className="border-t border-line pt-4">
              <Button
                className="w-full"
                loading={publishing}
                disabled={publishing}
                onClick={() => void publishWork()}
              >
                <BookOpen className="h-4 w-4" aria-hidden />
                存入创作工作室（群演剧本存档）
              </Button>
              <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
                把群演出整理成完整剧本，存进「创作工作室」继续连载或导出
              </p>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}

/* v2：SillyTavern 接入引导卡（原独立 /sillytavern 页并入，环境自适应地址） */
function StGuideCard() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const [copied, setCopied] = useState(false);

  const isPublic = (() => {
    const h = window.location.hostname;
    return !/^(\d{1,3}\.){3}\d{1,3}$/.test(h) && h !== "localhost" && h !== "127.0.0.1";
  })();
  const stUrl = isPublic
    ? `${window.location.origin}/silly`
    : `http://${window.location.hostname}:8001`;
  const gatewayUrl = isPublic
    ? `${window.location.origin}/model-hub/proxy/v1`
    : `http://${window.location.hostname}:8511/proxy/v1`;

  async function copyToken() {
    if (!accessToken) return;
    await copyText(accessToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="grid gap-5 rounded-2xl border border-line bg-surface p-4 text-sm shadow-zen md:grid-cols-3 md:p-5">
      <div>
        <p className="text-sm font-semibold">① 打开 SillyTavern</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          独立应用新窗口打开，首次访问按引导设置管理员密码。
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a href={stUrl} target="_blank" rel="noreferrer">
            <Button size="sm">
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              打开
            </Button>
          </a>
          <code className="min-w-0 truncate rounded-lg border border-line bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground">
            {stUrl}
          </code>
        </div>
      </div>
      <div>
        <p className="text-sm font-semibold">② 复制网关 API Key</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          即工作台登录凭证。粘贴到 ST 的 API Key 栏。
        </p>
        <div className="mt-3 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground select-none">
            {accessToken ? "••••••••（点击复制）" : "（未登录）"}
          </code>
          <Button variant="outline" size="sm" onClick={() => void copyToken()} disabled={!accessToken}>
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? "已复制" : "复制"}
          </Button>
        </div>
      </div>
      <div>
        <p className="text-sm font-semibold">③ ST 内配置连接</p>
        <ol className="mt-1 list-decimal space-y-1 pl-4 text-[11px] leading-relaxed text-muted-foreground">
          <li>设置 → API 连接 → Custom (OpenAI)</li>
          <li>
            源填 <code className="font-mono text-[11px]">{gatewayUrl}</code>
          </li>
          <li>
            Key 粘贴第②步 · 模型 <code className="font-mono text-[11px]">gpt-oss-120b-medium</code>
          </li>
        </ol>
      </div>
    </div>
  );
}
