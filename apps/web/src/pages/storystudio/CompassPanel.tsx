import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface Compass {
  intent?: string;
  focus?: string;
}

interface Props {
  projectId: string;
  settings?: Record<string, unknown> | undefined;
  onChanged?: () => void;
}

/**
 * 创作罗盘：全书承诺（题材/卖点/必须保留/必须避免）+ 当前阶段目标。
 * 保存后注入每次章节生成（防多轮跑偏/一致性漂移）。
 */
export function CompassPanel({ projectId, settings, onChanged }: Props) {
  const toast = useToast();
  const compass = (settings?.compass ?? {}) as Compass;
  const [intent, setIntent] = useState(compass.intent ?? "");
  const [focus, setFocus] = useState(compass.focus ?? "");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      await apiClient.put(`/story/projects/${projectId}/compass`, {
        intent,
        focus,
      });
      toast.success("罗盘已保存：后续生成都会守住这些承诺");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        🧭 创作罗盘 = 全书承诺 + 当前目标。保存后<b>注入每一次章节生成</b>，
        防止多轮创作跑偏、人设/基调漂移。
      </p>
      <Field label="全书承诺（题材 / 卖点 / 必须保留 / 必须避免）">
        {({ id }) => (
          <Textarea
            id={id}
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            rows={5}
            placeholder={"例如：\n· 题材：市井悬疑，主角是退休刑警老周\n· 卖点：案件背后全是邻里人情\n· 必须保留：方言对白、小城烟火气\n· 必须避免：玄幻设定、突然的宏大叙事"}
          />
        )}
      </Field>
      <Field label="当前阶段目标（本阶段最高优先级）">
        {({ id }) => (
          <Textarea
            id={id}
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            rows={2}
            placeholder={"例如：本阶段把「雨夜」作为每章氛围锚点，铺垫老周与女儿的关系线"}
          />
        )}
      </Field>
      <Button onClick={save} loading={busy} size="sm" className="self-end">
        保存罗盘
      </Button>
    </div>
  );
}
