/** 角色卡详情：全字段编辑 / 导入 / 导出 / 备用开场白。 */

import { useEffect, useState } from "react";

import { Download, Upload } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import { estimateTokens, type CharacterDetail } from "./types";

interface Props {
  assetId: string;
  onSaved?: () => void;
  onDeleted?: (assetId: string) => void;
}

export function CharacterPanel({ assetId, onSaved, onDeleted }: Props) {
  const toast = useToast();
  const [card, setCard] = useState<CharacterDetail | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const res = await apiClient.get<{ asset: CharacterDetail }>(
        `/roleplay/characters/${assetId}`,
      );
      setCard(res.asset);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "角色卡加载失败");
    }
  };

  useEffect(() => {
    setCard(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  const set = <K extends keyof CharacterDetail>(key: K, value: CharacterDetail[K]) => {
    setCard((c) => (c ? { ...c, [key]: value } : c));
  };

  const save = async () => {
    if (!card) return;
    setSaving(true);
    try {
      const body = { ...card } as Partial<CharacterDetail>;
      delete body.asset_id;
      delete body.url;
      await apiClient.put(`/roleplay/characters/${assetId}`, body);
      toast.success("角色卡已保存");
      onSaved?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const exportCard = async (fmt: "png" | "json") => {
    try {
      const blob = await apiClient.getBlob(`/roleplay/characters/${assetId}/export?format=${fmt}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `character-${assetId.slice(0, 8)}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    }
  };

  const importCard = async (file: File) => {
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiClient.postForm<{ ok: boolean; asset_id: string }>(
        "/roleplay/characters/import",
        form,
      );
      toast.success("角色卡导入成功");
      onSaved?.();
      void res;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    }
  };

  const removeCard = async () => {
    if (!window.confirm(`确定删除角色卡「${card?.name ?? ""}」？此操作不可恢复。`)) return;
    try {
      await apiClient.del(`/roleplay/characters/${assetId}`);
      toast.success("角色卡已删除");
      onDeleted?.(assetId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  if (!card) return <p className="py-4 text-center text-xs text-muted-foreground">加载中…</p>;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2">
        <img src={card.url} alt="" className="h-12 w-12 rounded-lg border border-border object-cover" />
        <div className="min-w-0 flex-1">
          <Input
            value={card.name}
            onChange={(e) => set("name", e.target.value)}
            className="h-8 text-sm font-medium"
          />
        </div>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => void exportCard("png")} title="导出 PNG 角色卡">
            <Download className="h-3.5 w-3.5" aria-hidden />
          </Button>
          <Button variant="outline" size="sm" onClick={() => void exportCard("json")} title="导出 JSON">
            JSON
          </Button>
          <Button
            variant="outline"
            size="sm"
            title="删除角色卡"
            onClick={() => void removeCard()}
            className="text-danger hover:bg-danger/10"
          >
            删
          </Button>
          <label className="cursor-pointer">
            <Button variant="outline" size="sm" title="导入 PNG/JSON 角色卡">
              <Upload className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <input
              type="file"
              accept=".png,.json,.yaml,.yml"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importCard(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>

      <Textarea value={card.description} onChange={(e) => set("description", e.target.value)} placeholder="外观与背景" className="min-h-[64px] text-xs" />
      <Textarea value={card.personality} onChange={(e) => set("personality", e.target.value)} placeholder="性格" className="min-h-[48px] text-xs" />
      <Textarea value={card.scenario} onChange={(e) => set("scenario", e.target.value)} placeholder="初始场景" className="min-h-[48px] text-xs" />
      <Textarea value={card.first_mes} onChange={(e) => set("first_mes", e.target.value)} placeholder="开场白" className="min-h-[48px] text-xs" />
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">备用开场白（{card.alternate_greetings.length}）</summary>
        {card.alternate_greetings.map((g, i) => (
          <div key={i} className="mt-1 flex gap-1">
            <Input
              value={g}
              onChange={(e) => {
                const next = [...card.alternate_greetings];
                next[i] = e.target.value;
                set("alternate_greetings", next);
              }}
              className="h-7 text-xs"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => set("alternate_greetings", card.alternate_greetings.filter((_, j) => j !== i))}
            >
              ×
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          size="sm"
          className="mt-1"
          onClick={() => set("alternate_greetings", [...card.alternate_greetings, ""])}
        >
          + 备用开场白
        </Button>
      </details>
      <Textarea value={card.mes_example} onChange={(e) => set("mes_example", e.target.value)} placeholder="示例对话（{{user}}: 开头，<START> 分块）" className="min-h-[48px] text-xs" />
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">高级（系统提示 / 对话后指令 / 备注 / 标签）</summary>
        <Textarea value={card.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} placeholder="系统提示（覆盖默认扮演提示）" className="mt-1 min-h-[48px] text-xs" />
        <Textarea value={card.post_history_instructions} onChange={(e) => set("post_history_instructions", e.target.value)} placeholder="对话后指令（PHI）" className="mt-1 min-h-[40px] text-xs" />
        <Textarea value={card.creator_notes} onChange={(e) => set("creator_notes", e.target.value)} placeholder="创作者备注" className="mt-1 min-h-[40px] text-xs" />
        <Input
          value={card.tags.join("，")}
          onChange={(e) =>
            set(
              "tags",
              e.target.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean),
            )
          }
          placeholder="标签（逗号分隔）"
          className="mt-1 h-7 text-xs"
        />
        <label className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          话痨度（群聊发言概率）
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={card.talkativeness}
            onChange={(e) => set("talkativeness", Number(e.target.value))}
            className="flex-1"
          />
          {card.talkativeness}
        </label>
      </details>

      <div className="rounded-lg border border-border bg-background px-2.5 py-2 text-[10px] text-muted-foreground">
        <div className="mb-1 flex justify-between">
          <span>角色卡 token 预算（估算）</span>
          <span className="font-medium text-foreground">
            {estimateTokens(
              [
                card.description,
                card.personality,
                card.scenario,
                card.first_mes,
                card.mes_example,
                card.system_prompt,
                card.post_history_instructions,
              ].join("\n"),
            )}{" "}
            tok
          </span>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          <span>描述 {estimateTokens(card.description)}</span>
          <span>性格 {estimateTokens(card.personality)}</span>
          <span>场景 {estimateTokens(card.scenario)}</span>
          <span>开场 {estimateTokens(card.first_mes)}</span>
          <span>示例 {estimateTokens(card.mes_example)}</span>
          <span>系统提示 {estimateTokens(card.system_prompt)}</span>
        </div>
      </div>
      <Button size="sm" onClick={() => void save()} disabled={saving} className="w-full">
        {saving ? "保存中…" : "保存角色卡"}
      </Button>
      <p className="text-[10px] text-muted-foreground">
        宏提示：{"{{char}}"}（角色名）、{"{{user}}"}（你的名字）、{"{{random::A::B}}"}、{"{{roll::1d20}}"}
      </p>
    </div>
  );
}
