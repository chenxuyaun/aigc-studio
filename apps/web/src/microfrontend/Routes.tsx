import { Suspense, lazy } from "react";

import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { LoadingState } from "@/components/ui/States";
import { useAuthStore } from "@/stores/auth";
import { useHost } from "./hostContext";

// 页面级懒加载：首屏只加载登录/工作台，其余按路由分包（含 WorkflowCanvasEditor 的 xyflow 独立 chunk）
const LoginPage = lazy(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const DashboardPage = lazy(() =>
  import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const TextGenPage = lazy(() =>
  import("@/pages/TextGenPage").then((m) => ({ default: m.TextGenPage })),
);
const ImageGenPage = lazy(() =>
  import("@/pages/ImageGenPage").then((m) => ({ default: m.ImageGenPage })),
);
const RoleplayPage = lazy(() =>
  import("@/pages/RoleplayPage").then((m) => ({ default: m.RoleplayPage })),
);
const SillyTavernPage = lazy(() =>
  import("@/pages/SillyTavernPage").then((m) => ({ default: m.SillyTavernPage })),
);
const CharacterCardPage = lazy(() =>
  import("@/pages/CharacterCardPage").then((m) => ({ default: m.CharacterCardPage })),
);
const ComicGenPage = lazy(() =>
  import("@/pages/ComicGenPage").then((m) => ({ default: m.ComicGenPage })),
);
const UpstreamPage = lazy(() =>
  import("@/pages/UpstreamPage").then((m) => ({ default: m.UpstreamPage })),
);
const VideoGenPage = lazy(() =>
  import("@/pages/VideoGenPage").then((m) => ({ default: m.VideoGenPage })),
);
const AudioGenPage = lazy(() =>
  import("@/pages/AudioGenPage").then((m) => ({ default: m.AudioGenPage })),
);
const MusicGenPage = lazy(() =>
  import("@/pages/MusicGenPage").then((m) => ({ default: m.MusicGenPage })),
);
const CreationPage = lazy(() =>
  import("@/pages/CreationPage").then((m) => ({ default: m.CreationPage })),
);
const WorksPage = lazy(() =>
  import("@/pages/WorksPage").then((m) => ({ default: m.WorksPage })),
);
const SharedMusicPage = lazy(() =>
  import("@/pages/SharedMusicPage").then((m) => ({ default: m.SharedMusicPage })),
);
const PromptGeneratorPage = lazy(() =>
  import("@/pages/PromptGeneratorPage").then((m) => ({ default: m.PromptGeneratorPage })),
);
const PromptOptimizerPage = lazy(() =>
  import("@/pages/PromptOptimizerPage").then((m) => ({ default: m.PromptOptimizerPage })),
);
const PromptsPage = lazy(() => import("@/pages/PromptsPage").then((m) => ({ default: m.PromptsPage })));
const AgentsPage = lazy(() => import("@/pages/AgentsPage").then((m) => ({ default: m.AgentsPage })));
const AgentChatPage = lazy(() =>
  import("@/pages/AgentChatPage").then((m) => ({ default: m.AgentChatPage })),
);
const SkillsPage = lazy(() => import("@/pages/SkillsPage").then((m) => ({ default: m.SkillsPage })));
const SkillChatPage = lazy(() =>
  import("@/pages/SkillChatPage").then((m) => ({ default: m.SkillChatPage })),
);
const KnowledgePage = lazy(() =>
  import("@/pages/KnowledgePage").then((m) => ({ default: m.KnowledgePage })),
);
const WorkflowsPage = lazy(() =>
  import("@/pages/WorkflowsPage").then((m) => ({ default: m.WorkflowsPage })),
);
const WorkflowCanvasEditor = lazy(() =>
  import("@/pages/WorkflowCanvasEditor").then((mod) => ({ default: mod.WorkflowCanvasEditor })),
);
const PhotographyPage = lazy(() =>
  import("@/pages/PhotographyPage").then((m) => ({ default: m.PhotographyPage })),
);
const PhotographyAlbumPage = lazy(() =>
  import("@/pages/PhotographyPage").then((m) => ({ default: m.PhotographyAlbumPage })),
);
const TasksPage = lazy(() => import("@/pages/TasksPage").then((m) => ({ default: m.TasksPage })));
const AssetsPage = lazy(() => import("@/pages/AssetsPage").then((m) => ({ default: m.AssetsPage })));
const ProvidersPage = lazy(() =>
  import("@/pages/ProvidersPage").then((m) => ({ default: m.ProvidersPage })),
);
const LogsPage = lazy(() => import("@/pages/LogsPage").then((m) => ({ default: m.LogsPage })));
const UsersPage = lazy(() => import("@/pages/UsersPage").then((m) => ({ default: m.UsersPage })));
const SharedPromptPage = lazy(() =>
  import("@/pages/SharedPromptPage").then((m) => ({ default: m.SharedPromptPage })),
);
const StoryStudioPage = lazy(() =>
  import("@/pages/StoryStudioPage").then((m) => ({ default: m.StoryStudioPage })),
);
const StoryProjectPage = lazy(() =>
  import("@/pages/StoryProjectPage").then((m) => ({ default: m.StoryProjectPage })),
);
const AgentDirectoryPage = lazy(() =>
  import("@/pages/AgentDirectoryPage").then((m) => ({ default: m.AgentDirectoryPage })),
);
const SearchPage = lazy(() =>
  import("@/pages/SearchPage").then((m) => ({ default: m.SearchPage })),
);
const AsmrPage = lazy(() =>
  import("@/pages/AsmrPage").then((m) => ({ default: m.AsmrPage })),
);

function Page({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingState />}>{children}</Suspense>;
}

/** 受保护布局：未登录跳转登录页；已登录渲染 AppShell + 子路由。
 *  Remote 模式宿主下发的 accessToken 也算已登录（store 可能尚未同步）。 */
function ProtectedLayout() {
  const authed = useAuthStore((s) => s.isAuthenticated());
  const hostToken = useHost().accessToken;
  if (!authed && !hostToken) return <Navigate to="/login" replace />;
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Page><LoginPage /></Page>} />
      <Route path="/share/prompts/:promptId" element={<Page><SharedPromptPage /></Page>} />
      <Route path="/share/music/:workId" element={<Page><SharedMusicPage /></Page>} />
      <Route element={<ProtectedLayout />}>
      <Route path="/" element={<Page><DashboardPage /></Page>} />
      {/* AI 创作已与工作台合一（目标框 + 引擎直控）；/create 直达重定向 */}
      <Route path="/create" element={<Navigate to="/" replace />} />
        <Route path="/sillytavern" element={<Page><SillyTavernPage /></Page>} />
        <Route path="/roleplay" element={<Page><RoleplayPage /></Page>} />
        <Route path="/story" element={<Page><StoryStudioPage /></Page>} />
        <Route path="/agent-directory" element={<Page><AgentDirectoryPage /></Page>} />
        <Route path="/story/:projectId" element={<Page><StoryProjectPage /></Page>} />
        <Route path="/search" element={<Page><SearchPage /></Page>} />
        <Route path="/asmr" element={<Page><AsmrPage /></Page>} />
        <Route path="/create/text" element={<Page><TextGenPage /></Page>} />
        <Route path="/create/image" element={<Page><ImageGenPage /></Page>} />
        <Route path="/create/comic" element={<Page><ComicGenPage /></Page>} />
        <Route path="/create/character-card" element={<Page><CharacterCardPage /></Page>} />
        <Route path="/settings/upstream" element={<Page><UpstreamPage /></Page>} />
        <Route path="/create/video" element={<Page><VideoGenPage /></Page>} />
        <Route path="/create/audio" element={<Page><AudioGenPage /></Page>} />
        <Route path="/create/music" element={<Page><MusicGenPage /></Page>} />
        <Route path="/create/studio" element={<Page><CreationPage /></Page>} />
        <Route path="/works" element={<Page><WorksPage /></Page>} />
        <Route path="/create/prompt" element={<Page><PromptGeneratorPage /></Page>} />
        <Route path="/create/prompt-optimize" element={<Page><PromptOptimizerPage /></Page>} />
        <Route path="/prompts" element={<Page><PromptsPage /></Page>} />
        <Route path="/agents" element={<Page><AgentsPage /></Page>} />
        <Route path="/agents/:id/chat" element={<Page><AgentChatPage /></Page>} />
        <Route path="/skills" element={<Page><SkillsPage /></Page>} />
        <Route path="/skills/:id/chat" element={<Page><SkillChatPage /></Page>} />
        <Route path="/workflows" element={<Page><WorkflowsPage /></Page>} />
        <Route path="/knowledge" element={<Page><KnowledgePage /></Page>} />
        <Route path="/workflows/new" element={<Page><WorkflowCanvasEditor /></Page>} />
        <Route path="/workflows/:id/edit" element={<Page><WorkflowCanvasEditor /></Page>} />
        <Route path="/photography" element={<Page><PhotographyPage /></Page>} />
        <Route path="/photography/:albumId" element={<Page><PhotographyAlbumPage /></Page>} />
        <Route path="/tasks" element={<Page><TasksPage /></Page>} />
        <Route path="/assets" element={<Page><AssetsPage /></Page>} />
        <Route path="/settings/providers" element={<Page><ProvidersPage /></Page>} />
        <Route path="/settings/users" element={<Page><UsersPage /></Page>} />
        <Route path="/settings/logs" element={<Page><LogsPage /></Page>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default AppRoutes;
