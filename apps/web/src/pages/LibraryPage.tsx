import { Navigate, useNavigate, useParams } from "react-router-dom";
import type { ComponentType } from "react";

import {
  BookOpen,
  Bot,
  Clapperboard,
  FolderOpen,
  Globe,
  Headphones,
  Library,
  Lightbulb,
  Camera,
  ListChecks,
} from "lucide-react";

import { cn } from "@/lib/cn";
import { WorksPage } from "@/pages/WorksPage";
import { TasksPage } from "@/pages/TasksPage";
import { AssetsPage } from "@/pages/AssetsPage";
import { PromptsPage } from "@/pages/PromptsPage";
import { KnowledgePage } from "@/pages/KnowledgePage";
import { AsmrPage } from "@/pages/AsmrPage";
import { PhotographyPage } from "@/pages/PhotographyPage";
import { InspirationGalleryPage } from "@/pages/InspirationGalleryPage";
import { AgentsPage } from "@/pages/AgentsPage";
import CommunityPage from "@/pages/CommunityPage";

/**
 * v3 融合：资产唯一页（/library/:tab）。
 * 作品/任务/素材/提示词/知识库/ASMR/写真相册/灵感/分享墙/Agent 库 = 类型 tab。
 * 旧路由（/works /tasks /assets …）全部 301 到对应 tab，页面组件原样复用。
 */
interface LibraryTab {
  key: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  element: React.ReactNode;
}

const TABS: LibraryTab[] = [
  { key: "works", label: "作品", icon: Clapperboard, element: <WorksPage /> },
  { key: "tasks", label: "任务", icon: ListChecks, element: <TasksPage /> },
  { key: "assets", label: "素材", icon: FolderOpen, element: <AssetsPage /> },
  { key: "prompts", label: "提示词", icon: Library, element: <PromptsPage /> },
  { key: "knowledge", label: "知识库", icon: BookOpen, element: <KnowledgePage /> },
  { key: "asmr", label: "ASMR", icon: Headphones, element: <AsmrPage /> },
  { key: "albums", label: "相册", icon: Camera, element: <PhotographyPage /> },
  { key: "inspiration", label: "灵感", icon: Lightbulb, element: <InspirationGalleryPage /> },
  { key: "community", label: "分享墙", icon: Globe, element: <CommunityPage /> },
  { key: "agents", label: "Agent", icon: Bot, element: <AgentsPage /> },
];

export function LibraryPage() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const active = TABS.find((t) => t.key === tab);
  if (!active) return <Navigate to="/library/works" replace />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="sr-only">资产藏馆</h1>
      {/* 类型 tab 条 */}
      <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-border px-4 py-2.5 md:px-6">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-current={t.key === active.key ? "page" : undefined}
            onClick={() => navigate(`/library/${t.key}`)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-2 text-sm transition-colors",
              t.key === active.key
                ? "bg-primary/12 font-semibold text-primary-text"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <t.icon className="h-4 w-4" aria-hidden />
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{active.element}</div>
    </div>
  );
}

export default LibraryPage;
