import type { ComponentType } from "react";

import {
  AudioLines,
  BookOpen,
  Camera,
  Clapperboard,
  ImageIcon,
  Music,
  Sparkles,
  Theater,
  TypeIcon,
  Users,
  Wand2,
} from "lucide-react";

export interface CreateTool {
  to: string;
  title: string;
  desc: string;
  scene: string;
  icon: ComponentType<{ className?: string }>;
  ready?: boolean;
  /** core=引擎直控（Mission 可替代）；suite=创作套件（保留独立入口） */
  group?: "core" | "suite";
}

/** 全站创作工具唯一清单（CreatePage / DashboardPage / TasksPage / PromptsPage 共用）。 */
export const CREATE_TOOLS: CreateTool[] = [
  { to: "/create/text", title: "文本生成", desc: "流式生成文案、脚本、教案", scene: "写作 · 改写 · 翻译", icon: TypeIcon, ready: true, group: "core" },
  { to: "/create/image", title: "图片生成", desc: "文本生成图片，异步任务", scene: "海报 · 插画 · 摄影", icon: ImageIcon, ready: true, group: "core" },
  { to: "/create/video", title: "视频生成", desc: "文本生成短视频", scene: "分镜 · 广告 · 概念", icon: Clapperboard, ready: true, group: "core" },
  { to: "/create/audio", title: "语音生成", desc: "文本转语音，多发音人", scene: "配音 · 朗读 · 播客", icon: AudioLines, ready: true, group: "core" },
  { to: "/create/music", title: "音乐生成", desc: "MusicGen 文本描述生成音乐", scene: "纯音乐 · 氛围 · 配乐", icon: Music, ready: true, group: "core" },
  { to: "/create/comic", title: "漫画生成", desc: "自动分镜、逐格出图、拼合成页", scene: "故事 · 四格 · 九宫格", icon: BookOpen, ready: true, group: "core" },
  { to: "/create/studio", title: "AI 导演工作室", desc: "给一个主题，AI 选角建组，群内分角色共创", scene: "主题 · 选角 · 群聊共创", icon: Theater, ready: true, group: "suite" },
  { to: "/create/character-card", title: "角色卡生成", desc: "为 SillyTavern 生成角色扮演角色卡", scene: "角色 · 头像 · 开场白", icon: Users, ready: true, group: "suite" },
  { to: "/create/prompt", title: "提示词生成", desc: "把想法变成结构化提示词", scene: "结构化 · 保存 · 复用", icon: Sparkles, ready: true, group: "suite" },
  { to: "/create/prompt-optimize", title: "提示词优化", desc: "诊断并优化已有提示词", scene: "诊断 · 评分 · 三版本", icon: Wand2, ready: true, group: "suite" },
  { to: "/photography", title: "写真摄影", desc: "上传并管理写真参考图集", scene: "相册 · 上传 · 风格参考", icon: Camera, ready: true, group: "suite" },
];

/** 工作台快捷工具（CreatePage 全量清单的子集）。 */
export const QUICK_TOOLS = CREATE_TOOLS.filter((t) =>
  ["/create/text", "/create/image", "/create/video", "/create/audio", "/create/prompt", "/photography"].includes(t.to),
);

/** 任务中心「新建任务」可直达的媒体工具。 */
export const MEDIA_TOOLS = CREATE_TOOLS.filter((t) =>
  ["/create/text", "/create/image", "/create/video", "/create/audio"].includes(t.to),
);
