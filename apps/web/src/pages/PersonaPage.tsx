import { Link, useNavigate } from "react-router-dom";
import { BookOpen, ChevronRight, MessageCircle, Server, UserRound, Users } from "lucide-react";

import { apiClient } from "@/lib/apiClient";
import { useQuery } from "@tanstack/react-query";

/**
 * saiOS v2 P3 —— 角色中心（/persona）：角色域四能力收拢入口。
 * 聚合捏卡/扮演/故事/SillyTavern + 最近角色快捷回到对话。
 */

const CARDS = [
  {
    to: "/create/character-card",
    icon: UserRound,
    title: "角色捏卡",
    desc: "世界书 · 头像生成 · SillyTavern PNG 卡导出，一分钟立起一个完整人设",
  },
  {
    to: "/roleplay",
    icon: MessageCircle,
    title: "角色扮演",
    desc: "长期记忆陪伴对话，L0-L3 记忆分层自动沉淀你们的每一段经历",
  },
  {
    to: "/story",
    icon: BookOpen,
    title: "故事工作室",
    desc: "AI 剧本工坊：大纲→章节→连载，支持多线叙事与角色一致性",
  },
  {
    to: "/sillytavern",
    icon: Server,
    title: "SillyTavern",
    desc: "专业前端直连管理：环境自适应地址、token 掩码、卡池互通",
  },
];

interface RoleplayItem {
  id: string;
  name?: string;
  character_name?: string;
  updated_at?: string;
}

export function PersonaPage() {
  const navigate = useNavigate();
  const { data: recent } = useQuery({
    queryKey: ["persona-recent"],
    queryFn: async () => {
      try {
        return await apiClient.get<RoleplayItem[]>("/roleplay/sessions?limit=6");
      } catch {
        // 端点差异容错：尝试列表接口
        try {
          return await apiClient.get<RoleplayItem[]>("/roleplay/sessions");
        } catch {
          return [];
        }
      }
    },
    staleTime: 30_000,
  });

  const items = Array.isArray(recent) ? recent : [];

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <header className="mb-8">
        <p className="flex items-center gap-2 text-xs font-medium text-primary-text">
          <Users className="h-4 w-4" aria-hidden /> Persona hub
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">角色中心</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          角色域全部能力收拢于此——从捏卡立设、长期记忆陪伴到剧本连载与专业前端，一条动线完成。
        </p>
      </header>

      {/* 四能力卡 */}
      <div className="grid gap-4 sm:grid-cols-2">
        {CARDS.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="group relative overflow-hidden rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-soft)] transition-colors hover:border-primary"
          >
            <div className="relative">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-muted text-primary-text">
                <c.icon className="h-5.5 w-5.5" aria-hidden />
              </span>
              <h2 className="mt-3 flex items-center gap-1 font-display text-lg font-semibold">
                {c.title}
                <ChevronRight className="h-4 w-4 opacity-0 transition-transform group-hover:translate-x-0.5 group-hover:opacity-100" aria-hidden />
              </h2>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{c.desc}</p>
            </div>
          </Link>
        ))}
      </div>

      {/* 最近角色 */}
      {items.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 font-display text-base font-semibold">最近陪伴的角色</h2>
          <div className="flex flex-wrap gap-2">
            {items.map((r) => (
              <button
                key={r.id}
                onClick={() => navigate(`/roleplay?chat=${r.id}`)}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
              >
                <MessageCircle className="h-3.5 w-3.5 text-primary-text" aria-hidden />
                {r.character_name || r.name || r.id.slice(0, 8)}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
