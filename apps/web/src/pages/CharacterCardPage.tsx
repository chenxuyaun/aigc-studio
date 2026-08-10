import { useState } from "react";

import { Download, Users } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { RoundtablePanel } from "@/components/creation/RoundtablePanel";
import { EmptyState } from "@/components/ui/States";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { toClientApiPath } from "@/lib/paths";

interface CardResult {
  asset_id: string;
  url: string;
  character: {
    name: string;
    description: string;
    personality: string;
    scenario: string;
    first_mes: string;
    mes_example: string;
  };
}

const STYLES = ["动漫", "写实", "水彩", "像素"];

export function CharacterCardPage() {
  const [genMode, setGenMode] = useState<"single" | "roundtable">("single");
  const [description, setDescription] = useState("");
  const [style, setStyle] = useState(STYLES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CardResult | null>(null);

  async function generate() {
    if (!description.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiClient.post<CardResult>("/character-cards/generate", {
        description,
        style,
      });
      const acc = await apiClient.get<{ url: string }>(
        toClientApiPath(`/assets/${res.asset_id}/access-url`),
      );
      setResult({ ...res, url: acc.url });
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="角色卡生成"
        description="为 SillyTavern 生成角色扮演角色卡（PNG，拖入即用）"
      />
      {/* 模式切换：直接生成 / 创作圆桌 */}
      <div className="flex gap-1 border-b border-border px-4 pt-2 md:px-6" role="tablist">
        {(
          [
            { key: "single", label: "⚡ 直接生成" },
            { key: "roundtable", label: "🎙️ 创作圆桌（多角色讨论人设）" },
          ] as { key: "single" | "roundtable"; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={genMode === t.key}
            onClick={() => setGenMode(t.key)}
            className={cn(
              "rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              genMode === t.key
                ? "border-primary text-primary-text"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {genMode === "roundtable" ? (
        <div className="p-4 md:p-6">
          <RoundtablePanel
            domain="character_card"
            themeLabel="角色设定"
            themePlaceholder="例如：一只会魔法的黑猫，喜欢恶作剧但心地善良…"
            extraLabel="附加要求（可选）"
            extraPlaceholder="世界观 / 说话风格 / 与主角的关系…"
            onFinal={(f) => {
              if (f.content) {
                setDescription(f.content);
                setGenMode("single");
              }
            }}
          />
        </div>
      ) : (
      <div className="grid gap-6 p-4 md:p-6 lg:grid-cols-[380px_1fr]">
        <div className="space-y-4 rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <Field label="角色描述" required>
            {({ id }) => (
              <Textarea
                id={id}
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="例如：一只会魔法的黑猫，喜欢恶作剧但心地善良"
              />
            )}
          </Field>
          <Field label="头像风格">
            {() => (
              <div className="flex flex-wrap gap-2">
                {STYLES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStyle(s)}
                    className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                      style === s
                        ? "border-primary bg-primary/10 font-medium text-primary-text"
                        : "border-border text-muted-foreground hover:border-border-strong"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </Field>
          <Button onClick={() => void generate()} loading={busy} className="w-full">
            <Users className="h-4 w-4" aria-hidden />
            生成角色卡
          </Button>
          {error && <p className="text-sm text-danger">{error}</p>}
          {busy && (
            <p className="text-xs text-muted-foreground">生成角色设定 + 头像，约 1 分钟…</p>
          )}
        </div>
        <div className="space-y-4">
          {result ? (
            <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-bold">{result.character.name}</h3>
                <a href={result.url} download="character.png" target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm">
                    <Download className="h-3.5 w-3.5" aria-hidden />
                    下载角色卡
                  </Button>
                </a>
              </div>
              <img
                src={result.url}
                alt="角色卡"
                className="mx-auto max-h-[420px] rounded-xl border border-border"
              />
              <dl className="mt-4 space-y-2 text-sm">
                <div>
                  <dt className="font-medium">外貌/背景</dt>
                  <dd className="text-muted-foreground">{result.character.description}</dd>
                </div>
                <div>
                  <dt className="font-medium">性格</dt>
                  <dd className="text-muted-foreground">{result.character.personality}</dd>
                </div>
                <div>
                  <dt className="font-medium">初始场景</dt>
                  <dd className="text-muted-foreground">{result.character.scenario}</dd>
                </div>
                <div>
                  <dt className="font-medium">开场白</dt>
                  <dd className="text-muted-foreground">{result.character.first_mes}</dd>
                </div>
              </dl>
              <p className="mt-3 text-xs text-muted-foreground">
                提示：下载后拖入 SillyTavern 角色卡管理即可使用
              </p>
            </div>
          ) : (
            <EmptyState title="还没有角色卡" description="填写左侧角色描述，一键生成 SillyTavern 角色卡" />
          )}
        </div>
      </div>
      )}
    </div>
  );
}
