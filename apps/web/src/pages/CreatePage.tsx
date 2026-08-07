import type { ComponentType } from "react";

import {
  AudioLines,
  BookOpen,
  Camera,
  Clapperboard,
  Image as ImageIcon,
  Sparkles,
  Type as TypeIcon,
  Users,
  Wand2,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/cn";

interface Tool {
  to: string;
  title: string;
  desc: string;
  scene: string;
  icon: ComponentType<{ className?: string }>;
  ready: boolean;
}

const TOOLS: Tool[] = [
  { to: "/create/text", title: "文本生成", desc: "流式生成文案、脚本、教案", scene: "写作 · 改写 · 翻译", icon: TypeIcon, ready: true },
  { to: "/create/image", title: "图片生成", desc: "文本生成图片，异步任务", scene: "海报 · 插画 · 摄影", icon: ImageIcon, ready: true },
  { to: "/create/video", title: "视频生成", desc: "文本生成短视频", scene: "分镜 · 广告 · 概念", icon: Clapperboard, ready: true },
  { to: "/create/audio", title: "语音生成", desc: "文本转语音，多发音人", scene: "配音 · 朗读 · 播客", icon: AudioLines, ready: true },
  { to: "/create/comic", title: "漫画生成", desc: "自动分镜、逐格出图、拼合成页", scene: "故事 · 四格 · 九宫格", icon: BookOpen, ready: true },
  { to: "/create/character-card", title: "角色卡生成", desc: "为 SillyTavern 生成角色扮演角色卡", scene: "角色 · 头像 · 开场白", icon: Users, ready: true },
  { to: "/create/prompt", title: "提示词生成", desc: "把想法变成结构化提示词", scene: "结构化 · 保存 · 复用", icon: Sparkles, ready: true },
  { to: "/create/prompt-optimize", title: "提示词优化", desc: "诊断并优化已有提示词", scene: "诊断 · 评分 · 三版本", icon: Wand2, ready: true },
  { to: "/photography", title: "写真摄影", desc: "上传并管理写真参考图集", scene: "相册 · 上传 · 风格参考", icon: Camera, ready: true },
];

export function CreatePage() {
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="AI 创作" description="选择一个工具开始创作" />
      <div className="grid gap-3 p-4 sm:grid-cols-2 md:p-6 lg:grid-cols-3">
        {TOOLS.map((t) => (
          <button
            key={t.to}
            disabled={!t.ready}
            onClick={() => t.ready && navigate(t.to)}
            className={cn(
              "flex flex-col gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-5 text-left transition-all",
              t.ready ? "hover:-translate-y-0.5 hover:border-primary" : "cursor-not-allowed opacity-55",
            )}
          >
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary/12 text-primary-text">
              <t.icon className="h-5.5 w-5.5" aria-hidden />
            </span>
            <span>
              <span className="block text-[15px] font-semibold">{t.title}</span>
              <span className="mt-1 block text-sm text-muted-foreground">{t.desc}</span>
            </span>
            <span className="mt-auto font-mono-ui text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {t.scene}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
