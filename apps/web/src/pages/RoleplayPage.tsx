import { useEffect, useState } from "react";

import { BookOpen, Bot, ExternalLink, Plus, Search, Send, SlidersHorizontal, Wand2 } from "lucide-react";

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
    <div className="space-y-4">
      <PageHeader
        title="角色扮演"
        description="SillyTavern 功能融入：角色卡 / 世界书 / 会话 / 宏 / 情绪 / 好感度"
        actions={
          <Button variant="outline" onClick={() => window.open("/sillytavern", "_blank", "noopener")}>
            <ExternalLink className="mr-1.5 h-4 w-4" />
            打开 SillyTavern 独立窗口
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)_300px]">
        {/* 左栏：角色卡 + 会话 */}
        <div className="space-y-4">
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-3">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Bot className="h-4 w-4" aria-hidden />
                角色卡
              </h3>
              <a
                href="/create/character-card"
                className="flex items-center gap-1 text-xs text-primary-text hover:underline"
              >
                <Plus className="h-3 w-3" aria-hidden />
                生成新卡
              </a>
            </div>
            <label className="flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={groupMode}
                onChange={(e) => setGroupMode(e.target.checked)}
              />
              群聊模式（多选角色同场）
            </label>
            <label className="flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={isRoom}
                onChange={(e) => setIsRoom(e.target.checked)}
              />
              多人房间（全员可见可加入）
            </label>
            {isRoom && (
              <div className="mb-1 flex flex-col gap-1">
                <input
                  value={authorName}
                  onChange={(e) => setAuthorName(e.target.value)}
                  placeholder="你的身份名（如：陈满堂）"
                  className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
                />
                <input
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  placeholder="群名（如：双城之夜剧组）"
                  className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
                />
                <input
                  value={groupDesc}
                  onChange={(e) => setGroupDesc(e.target.value)}
                  placeholder="群简介（可选）"
                  className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
                />
              </div>
            )}
            {groupMode && (
              <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[10px] text-muted-foreground">
                轮流
                <select
                  value={groupStrategy}
                  onChange={(e) => setGroupStrategy(e.target.value as typeof groupStrategy)}
                  className="h-6 flex-1 rounded border border-border bg-background px-1"
                >
                  <option value="natural">自然（模型自选）</option>
                  <option value="list">按序轮流</option>
                  <option value="random">随机指定</option>
                </select>
                注入
                <select
                  value={groupModeType}
                  onChange={(e) => setGroupModeType(e.target.value as typeof groupModeType)}
                  className="h-6 flex-1 rounded border border-border bg-background px-1"
                >
                  <option value="append">全员卡片</option>
                  <option value="swap">仅说话者</option>
                </select>
              </div>
            )}
            {groupMode && (
              <label className="flex items-center gap-1.5 px-1 py-1 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
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
                    className="h-5 w-12 rounded border border-border bg-background px-1"
                  />
                )}
                {autoMode && <span>秒/轮</span>}
              </label>
            )}
            <Input
              value={charSearch}
              onChange={(e) => setCharSearch(e.target.value)}
              placeholder="搜索角色…"
              className="mb-1.5 h-7 text-xs"
            />
            <div className="max-h-64 space-y-1 overflow-y-auto">
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
                      ? "border-primary bg-primary/10"
                      : "border-border hover:border-border-strong"
                  }`}
                >
                  <input
                    type="checkbox"
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
                      <span className="block truncate text-xs font-medium">
                        {c.name || c.filename}
                        {c.is_shared && (
                          <span className="ml-1 rounded bg-primary/12 px-1 py-0.5 text-[9px] font-semibold text-primary-text">
                            共享
                          </span>
                        )}
                      </span>
                      {authUser?.role === "admin" && (
                        <button
                          type="button"
                          onClick={() => void toggleShare(c)}
                          className="shrink-0 rounded-md border border-border px-1.5 py-0.5 text-[9px] text-muted-foreground transition-colors hover:border-primary hover:text-primary-text"
                          title={c.is_shared ? "取消共享（仅自己可见）" : "共享给所有用户"}
                        >
                          {c.is_shared ? "取消共享" : "共享"}
                        </button>
                      )}
                      <span className="block truncate text-[10px] text-muted-foreground">
                        {c.filename}
                      </span>
                    </span>
                  </button>
                </div>
              ))}
              {characters.length === 0 && (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  暂无角色卡 —— 去「生成新卡」创建或导入
                </p>
              )}
              {characters.length > 0 &&
                characters.filter((c) => {
                  const q = charSearch.trim().toLowerCase();
                  return !q || `${c.name ?? ""} ${c.filename}`.toLowerCase().includes(q);
                }).length === 0 && (
                  <p className="py-4 text-center text-xs text-muted-foreground">无匹配角色</p>
                )}
            </div>
          </div>

          <div className="h-72 rounded-[var(--radius-card)] border border-border bg-surface">
            <SessionSidebar
              activeId={sessionId}
              refreshKey={refreshTick}
              onSelect={(s) => void openSession(s)}
              onCreated={newSession}
              onDeleted={deleteSession}
            />
          </div>
        </div>

        {/* 中栏：聊天 */}
        <div className="flex min-h-[560px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <span className="text-sm font-semibold">
              {selected ? `与 ${charDisplayName || selected.filename} 聊天` : "请选择角色"}
              <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                好感度 {affinity}
              </span>
              {sessionId && (
                <button
                  type="button"
                  className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text hover:bg-primary/20"
                  onClick={() => void openGroupInfo(sessionId)}
                >
                  📋 群信息
                </button>
              )}
            </span>
            <div className="flex items-center gap-2 text-xs">
              {messages.length > 0 && (
                <button className="text-muted-foreground hover:text-danger" onClick={() => void clearChat()}>
                  清空对话
                </button>
              )}
              {busy && <span className="animate-pulse text-muted-foreground">生成中…</span>}
              <span className="text-[10px] text-muted-foreground">
                {promptTokens != null
                  ? `最近上下文 ${promptTokens} tok`
                  : `上下文 ≈ ${estimateTokens(messages.map((m) => m.content).join("\n"))} tok`}
              </span>
            </div>
          </div>

          {messages.length > 5 && (
            <div className="flex items-center gap-1.5 border-b border-border px-3 py-1.5">
              <Search className="h-3 w-3 text-muted-foreground" aria-hidden />
              <input
                value={msgSearch}
                onChange={(e) => setMsgSearch(e.target.value)}
                placeholder="搜索对话…"
                className="h-6 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
              />
              {msgSearch && (
                <button
                  className="text-[10px] text-muted-foreground hover:text-foreground"
                  onClick={() => setMsgSearch("")}
                >
                  清除
                </button>
              )}
            </div>
          )}
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && !streamingText && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                发送第一条消息开始角色扮演（自动创建会话）
              </p>
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
                <div className="group max-w-[75%]">
                  <div
                    className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm ${
                      m.role === "user"
                        ? "bg-primary/15 text-foreground"
                        : "border border-border bg-background"
                    }`}
                  >
                    {m.role === "assistant" && m.mood && (
                      <span className="mb-1.5 mr-1.5 inline-block rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
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
                    <div className="mt-1 flex items-center gap-2 px-1 opacity-0 transition-opacity group-hover:opacity-100">
                      {m.swipes && m.swipes.length > 1 && (
                        <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                          <button
                            className="hover:text-primary-text"
                            title="上一个"
                            onClick={() => switchSwipe(i, -1)}
                          >
                            ‹
                          </button>
                          {(m.swipeIndex ?? m.swipes.length - 1) + 1}/{m.swipes.length}
                          <button
                            className="hover:text-primary-text"
                            title="下一个"
                            onClick={() => switchSwipe(i, 1)}
                          >
                            ›
                          </button>
                        </span>
                      )}
                      <button
                        className="text-[10px] text-muted-foreground hover:text-primary-text"
                        title="生成另一个回复"
                        onClick={() => void swipeReply(i)}
                      >
                        ↻ 换一个
                      </button>
                      <button
                        className="text-[10px] text-muted-foreground hover:text-primary-text"
                        title="继续写下去"
                        onClick={() => void continueReply(i)}
                      >
                        ✎ 继续写
                      </button>
                    </div>
                  )}
                  {m.role === "assistant" && !busy && (
                    <button
                      className="mt-1 px-1 text-[10px] text-muted-foreground opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                      title="删除这条消息"
                      onClick={() => void removeMessage(i)}
                    >
                      ✕ 删除
                    </button>
                  )}
                  <button
                    className="mt-1 px-1 text-[10px] text-muted-foreground opacity-0 transition-opacity hover:text-primary-text group-hover:opacity-100"
                    title="复制消息"
                    onClick={() => void copyText(m.content)}
                  >
                    复制
                  </button>
                  <button
                    className="mt-1 px-1 text-[10px] text-muted-foreground opacity-0 transition-opacity hover:text-primary-text group-hover:opacity-100"
                    title="从这里分叉新会话"
                    onClick={() => void branchChat(i)}
                  >
                    ⑂ 分支
                  </button>
                </div>
              </div>
              ))}
            {streamingText && (
              <div className="flex justify-start">
                <div className="max-w-[75%] rounded-2xl border border-border bg-background px-3.5 py-2.5 text-sm">
                  <MarkdownContent content={streamingText} />
                  <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-middle" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* 快捷回复行 */}
          {quickReplies.length > 0 && (
            <div className="flex flex-wrap gap-1.5 border-t border-border px-3 py-2">
              {quickReplies.map((q) => (
                <button
                  key={q.id}
                  disabled={busy || !selected}
                  onClick={() => setInput(expandQuickMacros(q.message, charDisplayName, personas.find((p) => p.id === personaId)?.name ?? "用户"))}
                  className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-primary-text disabled:opacity-40"
                >
                  {q.label}
                </button>
              ))}
            </div>
          )}

          <div className="border-t border-border p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <label htmlFor="rp-model" className="shrink-0">
                模型
              </label>
              <select
                id="rp-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-7 flex-1 rounded-lg border border-border bg-background px-2 text-xs outline-none focus:border-primary"
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
                className="h-7 rounded-lg border border-border bg-background px-2 text-xs"
              >
                <option value="">默认（用户）</option>
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <details className="relative">
                <summary className="flex cursor-pointer items-center gap-1 text-muted-foreground hover:text-foreground">
                  <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
                  参数
                </summary>
                <div className="absolute right-0 top-6 z-10 w-56 space-y-2 rounded-xl border border-border bg-surface p-3 shadow-lg">
                  <label className="block text-xs">
                    温度 {temperature.toFixed(1)}
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={0.1}
                      value={temperature}
                      onChange={(e) => setTemperature(Number(e.target.value))}
                      className="w-full"
                    />
                  </label>
                  <label className="block text-xs">
                    最大回复 token
                    <input
                      type="number"
                      min={64}
                      max={8192}
                      step={64}
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(Number(e.target.value) || 1024)}
                      className="mt-1 h-7 w-full rounded-lg border border-border bg-background px-2"
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
              <Button onClick={() => void send()} disabled={busy || !selected}>
                <Send className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
        </div>

        {/* 右栏：世界书 / 角色卡 / 正则 */}
        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
          <div className="mb-3 flex gap-1 border-b border-border pb-2 text-xs">
            {(
              [
                ["lore", "世界书"],
                ["character", "角色卡"],
                ["regex", "正则"],
                ["settings", "设置"],
                ["memory", "记忆"],
                ["book", "状态账本"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setRightTab(key)}
                className={`rounded-lg px-2.5 py-1 transition-colors ${
                  rightTab === key ? "bg-primary/10 text-primary-text" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="max-h-[540px] overflow-y-auto">
            {rightTab === "lore" && <LorePanel characterName={charsForBinding} />}
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
                <p className="py-4 text-center text-xs text-muted-foreground">请先选择角色卡</p>
              ))}
            {rightTab === "regex" && <RegexPanel characterName={charsForBinding} />}
            {rightTab === "memory" &&
              (selected ? (
                <MemoryPanel assetId={selected.asset_id} />
              ) : (
                <p className="py-4 text-center text-xs text-muted-foreground">请先选择角色卡</p>
              ))}
            {rightTab === "settings" && (
              <SettingsPanel
                noteContent={noteContent}
                noteInterval={noteInterval}
                onNoteChange={setNoteContent}
                onNoteIntervalChange={setNoteInterval}
                onPersonasChanged={setPersonas}
                onQuickRepliesChanged={setQuickReplies}
              />
            )}
            {rightTab === "book" && <StatusBookPanel chatId={sessionId} />}
          </div>

          <div className="mt-3 border-t border-border pt-2">
            <p className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <BookOpen className="h-3 w-3" aria-hidden />
              宏：{"{{char}}"} {"{{user}}"} {"{{random::A::B}}"} {"{{roll::1d20}}"} {"{{time}}"}
            </p>
            <p className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
              <Wand2 className="h-3 w-3" aria-hidden />
              会话可导出为 SillyTavern JSONL，也可导入回放
            </p>
          </div>
        </div>
      </div>
      <Dialog open={groupInfoOpen} onClose={() => setGroupInfoOpen(false)} title={groupInfo?.name ?? "群信息"}>
        {groupInfo && (
          <div className="space-y-3">
            {groupInfo.description && (
              <p className="text-xs text-muted-foreground">{groupInfo.description}</p>
            )}
            <div className="flex items-center gap-2 rounded-lg bg-muted/40 p-2">
              <span className="text-xs text-muted-foreground">邀请码：</span>
              <code className="font-mono text-sm font-semibold">{groupInfo.invite_code}</code>
              <button
                type="button"
                className="ml-auto text-xs text-primary-text hover:underline"
                onClick={() => void navigator.clipboard?.writeText(groupInfo.invite_code)}
              >
                复制
              </button>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-semibold text-foreground">
                成员（{groupInfo.members.length}）
              </p>
              <ul className="space-y-1">
                {groupInfo.members.map((m: GroupMember) => (
                  <li key={m.user_id} className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-sm">
                    <span className="truncate">{m.username}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {m.role === "owner" ? "群主" : "成员"}
                    </span>
                    {m.role !== "owner" && authUser?.id === groupInfo.owner_id && (
                      <button
                        type="button"
                        className="ml-auto text-xs text-danger hover:underline"
                        onClick={() => void kickMember(m.user_id)}
                      >
                        移出
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            <div className="border-t border-border pt-3">
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
