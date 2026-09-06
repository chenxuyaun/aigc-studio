import { Suspense, lazy } from "react";

import { Navigate, Outlet, Route, Routes, useLocation, useParams } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { LoadingState } from "@/components/ui/States";
import { useAuthStore } from "@/stores/auth";
import { useHost } from "./hostContext";

// 页面级懒加载：首屏只加载登录/工作台，其余按路由分包（含 WorkflowCanvasEditor 的 xyflow 独立 chunk）
const LoginPage = lazy(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const AssistantHomePage = lazy(() =>
  import("@/pages/AssistantHomePage").then((m) => ({ default: m.AssistantHomePage })),
);
const StudioPage = lazy(() => import("@/pages/StudioPage").then((m) => ({ default: m.StudioPage })));
const PersonaPage = lazy(() => import("@/pages/PersonaPage").then((m) => ({ default: m.PersonaPage })));
const DashboardPage = lazy(() =>
  import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const GrowthPage = lazy(() => import("@/pages/GrowthPage"));
const TeamPage = lazy(() => import("@/pages/TeamPage"));
const RoleplayPage = lazy(() =>
  import("@/pages/RoleplayPage").then((m) => ({ default: m.RoleplayPage })),
);
const AgentChatPage = lazy(() =>
  import("@/pages/AgentChatPage").then((m) => ({ default: m.AgentChatPage })),
);
const WorkflowsPage = lazy(() =>
  import("@/pages/WorkflowsPage").then((m) => ({ default: m.WorkflowsPage })),
);
const WorkflowCanvasEditor = lazy(() =>
  import("@/pages/WorkflowCanvasEditor").then((mod) => ({ default: mod.WorkflowCanvasEditor })),
);
const ProvidersPage = lazy(() =>
  import("@/pages/ProvidersPage").then((m) => ({ default: m.ProvidersPage })),
);
const LogsPage = lazy(() => import("@/pages/LogsPage").then((m) => ({ default: m.LogsPage })));
const UsersPage = lazy(() => import("@/pages/UsersPage").then((m) => ({ default: m.UsersPage })));
const SharedPromptPage = lazy(() =>
  import("@/pages/SharedPromptPage").then((m) => ({ default: m.SharedPromptPage })),
);
const SharedMusicPage = lazy(() =>
  import("@/pages/SharedMusicPage").then((m) => ({ default: m.SharedMusicPage })),
);
const StoryStudioPage = lazy(() =>
  import("@/pages/StoryStudioPage").then((m) => ({ default: m.StoryStudioPage })),
);
const StoryProjectPage = lazy(() =>
  import("@/pages/StoryProjectPage").then((m) => ({ default: m.StoryProjectPage })),
);
const StoryboardPage = lazy(() =>
  import("@/pages/StoryboardPage").then((m) => ({ default: m.StoryboardPage })),
);
const SearchPage = lazy(() =>
  import("@/pages/SearchPage").then((m) => ({ default: m.SearchPage })),
);
// v3 融合：资产唯一页（旧 8 个资产页并入为类型 tab）
const LibraryPage = lazy(() => import("@/pages/LibraryPage").then((m) => ({ default: m.LibraryPage })));
const PhotographyAlbumPage = lazy(() =>
  import("@/pages/PhotographyPage").then((m) => ({ default: m.PhotographyAlbumPage })),
);

function Page({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingState />}>{children}</Suspense>;
}

/** /photography/:albumId → /library/albums/:albumId（保留动态段参数） */
function AlbumRedirect() {
  const { albumId } = useParams<{ albumId: string }>();
  return <Navigate to={`/library/albums/${albumId}`} replace />;
}

/** /create/* → /studio?engine=x：透传 location.state（提示词库「用于创作」的 prompt handoff） */
function StudioRedirect({ engine }: { engine: string }) {
  const location = useLocation();
  const state = (location.state ?? {}) as { prompt?: string };
  return (
    <Navigate
      to={`/studio?engine=${engine}`}
      replace
      state={state.prompt ? { prompt: state.prompt } : undefined}
    />
  );
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
      <Route path="/" element={<Page><AssistantHomePage /></Page>} />
      <Route path="/studio" element={<Page><StudioPage /></Page>} />

      {/* ── v3 五场所 ──
          1. 对话 /            （AI 助手，能力=芯片）
          2. 工作台 /studio     （唯一引擎直控页，?engine= 深链）
          3. 资产 /library/:tab （唯一资产页，旧 8 资产页 = 类型 tab）
          4. 角色 /roleplay     （唯一沉浸模式）
          5. 系统 /dashboard    （admin）
          其余全部 301 归并，页面组件保留复用。 */}
      <Route path="/library" element={<Navigate to="/library/works" replace />} />
      <Route path="/library/:tab" element={<Page><LibraryPage /></Page>} />
      <Route path="/library/albums/:albumId" element={<Page><PhotographyAlbumPage /></Page>} />

      {/* 资产类 → /library */}
      <Route path="/works" element={<Navigate to="/library/works" replace />} />
      <Route path="/tasks" element={<Navigate to="/library/tasks" replace />} />
      <Route path="/assets" element={<Navigate to="/library/assets" replace />} />
      <Route path="/prompts" element={<Navigate to="/library/prompts" replace />} />
      <Route path="/knowledge" element={<Navigate to="/library/knowledge" replace />} />
      <Route path="/asmr" element={<Navigate to="/library/asmr" replace />} />
      <Route path="/photography" element={<Navigate to="/library/albums" replace />} />
      <Route path="/photography/:albumId" element={<AlbumRedirect />} />
      <Route path="/inspiration" element={<Navigate to="/library/inspiration" replace />} />
      <Route path="/community" element={<Navigate to="/library/community" replace />} />
      <Route path="/agents" element={<Navigate to="/library/agents" replace />} />
      <Route path="/agent-directory" element={<Navigate to="/library/agents" replace />} />

      {/* 能力类 → /studio 深链（引擎 tab 直达） */}
      <Route path="/create" element={<Navigate to="/" replace />} />
      <Route path="/create/image" element={<StudioRedirect engine="image" />} />
      <Route path="/create/comic" element={<StudioRedirect engine="image" />} />
      <Route path="/create/text" element={<Navigate to="/" replace />} />
      <Route path="/create/audio" element={<StudioRedirect engine="music" />} />
      <Route path="/create/music" element={<StudioRedirect engine="music" />} />
      <Route path="/create/video" element={<StudioRedirect engine="video" />} />
      <Route path="/create/character-card" element={<StudioRedirect engine="story" />} />
      <Route path="/create/studio" element={<StudioRedirect engine="story" />} />
      <Route path="/create/prompt" element={<Navigate to="/library/prompts" replace />} />
      <Route path="/create/prompt-optimize" element={<Navigate to="/library/prompts" replace />} />

      {/* 角色故事 → /roleplay；story/workflow/team 路由保留（从对话产物进入，不再占导航） */}
      <Route path="/sillytavern" element={<Navigate to="/roleplay" replace />} />
      <Route path="/persona" element={<Page><PersonaPage /></Page>} />
      <Route path="/roleplay" element={<Page><RoleplayPage /></Page>} />
      <Route path="/story" element={<Page><StoryStudioPage /></Page>} />
      <Route path="/story/:projectId" element={<Page><StoryProjectPage /></Page>} />
      <Route path="/storyboard/:projectId" element={<Page><StoryboardPage /></Page>} />
      <Route path="/workflows" element={<Page><WorkflowsPage /></Page>} />
      <Route path="/workflows/new" element={<Page><WorkflowCanvasEditor /></Page>} />
      <Route path="/workflows/:id/edit" element={<Page><WorkflowCanvasEditor /></Page>} />
      <Route path="/team" element={<Page><TeamPage /></Page>} />

      {/* 系统（admin) */}
      <Route path="/dashboard" element={<Page><DashboardPage /></Page>} />
      {/* 休眠路由（不占导航，深链可达）：全域搜索落地页 / AI 成长足迹 */}
      <Route path="/search" element={<Page><SearchPage /></Page>} />
      <Route path="/growth" element={<Page><GrowthPage /></Page>} />
      <Route path="/settings/upstream" element={<Navigate to="/dashboard" replace />} />
      <Route path="/settings/providers" element={<Page><ProvidersPage /></Page>} />
      <Route path="/settings/users" element={<Page><UsersPage /></Page>} />
      <Route path="/settings/logs" element={<Page><LogsPage /></Page>} />

      {/* 旧技能库路由兼容 */}
      <Route path="/skills" element={<Navigate to="/library/agents" replace />} />
      <Route path="/skills/:id/chat" element={<Navigate to="/library/agents" replace />} />
      <Route path="/agents/:id/chat" element={<Page><AgentChatPage /></Page>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default AppRoutes;
