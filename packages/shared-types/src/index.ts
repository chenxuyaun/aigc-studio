/**
 * AIGC Studio 前后端共享类型契约。
 *
 * 前端不得重复定义这些结构；后端 OpenAPI 生成的类型未来在此汇总。
 */

// ---------------------------------------------------------------------------
// 通用响应封装
// ---------------------------------------------------------------------------

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
  request_id?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ---------------------------------------------------------------------------
// 领域枚举
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "user";

export type TaskType = "text" | "image" | "video" | "audio" | "chapter";

export type TaskStatus =
  | "queued"
  | "submitting"
  | "processing"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "expired";

export type PromptType =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "code"
  | "agent"
  | "education"
  | "other";

// ---------------------------------------------------------------------------
// 领域实体
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

/** 管理端用户列表行（GET /users/）。 */
export type UserRow = User;

export interface GenerationTask {
  id: string;
  task_type: TaskType;
  status: TaskStatus;
  progress: number;
  result: string;
  model: string;
  error_message: string;
  /** 创建参数 JSON 字符串，用于再次运行回填 */
  params?: string;
  created_at: string;
  updated_at: string;
}

export interface Prompt {
  id: string;
  title: string;
  content: string;
  category_id: string | null;
  prompt_type: PromptType;
  is_public: boolean;
  favorite_count: number;
  use_count: number;
  author_id: string;
  source_type: string;
  cover_url: string;
  source_url: string;
  source_author: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface PromptCategory {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Agents / Skills / Workflows（与提示词库同构的创意资产模块）
// ---------------------------------------------------------------------------

export interface Agent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  category_id: string | null;
  agent_type: string;
  is_public: boolean;
  favorite_count: number;
  use_count: number;
  author_id: string;
  source_type: string;
  cover_url: string;
  source_url: string;
  source_author: string;
  model: string;
  temperature: number | null;
  max_tokens: number | null;
  tools: string[];
  created_at: string;
  updated_at: string;
}

export interface AgentCategory {
  id: string;
  name: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  instructions: string;
  skill_type: string;
  model: string;
  is_public: boolean;
  favorite_count: number;
  use_count: number;
  author_id: string;
  source_type: string;
  cover_url: string;
  source_url: string;
  source_author: string;
  inputs_schema: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  graph: Record<string, unknown>;
  category_id: string | null;
  workflow_type: string;
  is_public: boolean;
  favorite_count: number;
  use_count: number;
  author_id: string;
  source_type: string;
  cover_url: string;
  source_url: string;
  source_author: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface WorkflowCategory {
  id: string;
  name: string;
}

/** 工作流图节点 */
export interface WorkflowGraphNode {
  id: string;
  type: "skill" | "prompt" | "agent";
  name: string;
  position?: { x: number; y: number };
  /**
   * 节点类型专属配置数据。
   * - prompt: { promptContent, model, temperature }
   * - agent: { model, systemPrompt, temperature }
   * - skill: { skillType, params }
   */
  data?: Record<string, unknown>;
}

/** 工作流图边 */
export interface WorkflowGraphEdge {
  from: string;
  to: string;
}

/** 工作流图 */
export interface WorkflowGraph {
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: string;
  owner_id: string;
  cover_url: string;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  task_id: string | null;
  storage_backend?: string;
  created_at: string;
  url: string;
  access_url_endpoint?: string;
}

export interface MediaAccess {
  url: string;
  expires_at: string;
}

export interface PhotoAlbum {
  id: string;
  title: string;
  description: string;
  cover_photo_id: string | null;
  cover_url: string | null;
  cover_access_url_endpoint?: string | null;
  style_tags: string;
  is_public: boolean;
  photo_count: number;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface Photo {
  id: string;
  album_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  width: number;
  height: number;
  caption: string;
  sort_order: number;
  storage_backend?: string;
  url: string;
  access_url_endpoint?: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// 生成请求
// ---------------------------------------------------------------------------

export interface TextGenerationRequest {
  model: string;
  prompt: string;
  messages?: Array<{ role: string; content: string }>;
  temperature?: number;
  max_tokens?: number;
  stream: boolean;
}

export interface ImageGenerationRequest {
  model: string;
  prompt: string;
  negative_prompt?: string;
  width: number;
  height: number;
  num_images: number;
  reference_photo_id?: string | null;
  reference_asset_id?: string | null;
}

// ---------------------------------------------------------------------------
// 微前端 Host 契约（Standalone 与 Remote 双模式）
// ---------------------------------------------------------------------------

/** 工作台统计（GET /dashboard/stats）。 */
export interface DashboardStats {
  success: boolean;
  data: {
    total_tasks: number;
    succeeded: number;
    failed: number;
    text_count: number;
    image_count: number;
    video_count: number;
    audio_count: number;
    trend_7d?: Array<{ date: string; count: number }>;
    recent_tasks?: Array<{
      id: string;
      task_type: string;
      status: string;
      progress: number;
      model: string;
      created_at: string | null;
    }>;
  };
}

/** 管理端 Provider 配置行（GET /providers/admin）。 */
export interface ProviderAdminRow {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  default_model: string;
  is_enabled: boolean;
  priority: number;
  timeout_seconds?: number;
  has_api_key: boolean;
  api_key_fingerprint: string;
  created_at: string;
}

/** Provider 调用日志行（GET /logs/）。 */
export interface CallLogItem {
  id: string;
  task_id: string;
  task_type: string;
  provider: string;
  model: string;
  status: string;
  error_message: string;
  duration_ms: number;
  created_at: string;
}

/** 文本生成模型目录项（GET /providers/catalog）。 */
export interface CatalogItem {
  id: string;
  name: string;
  provider_type: string;
  default_model: string;
  is_enabled?: boolean;
  source?: string;
}

export interface AigcStudioUser {
  id: string;
  name: string;
  avatar?: string;
  roles?: string[];
}

export interface AigcStudioHostProps {
  /** 主系统挂载的路由前缀，Standalone 模式下留空。 */
  basename?: string;
  /** 主系统下发的访问令牌。 */
  accessToken?: string;
  locale?: "zh-CN" | "en-US";
  theme?: "light" | "dark" | "system";
  user?: AigcStudioUser;
  /** 覆盖 API 根地址（默认使用 Remote 自身配置）。 */
  apiBaseUrl?: string;
  /** 窄容器紧凑模式：隐藏独立侧栏，复用宿主导航。 */
  compactMode?: boolean;
  onNavigate?: (path: string) => void;
  onUnauthorized?: () => void;
  getAccessToken?: () => string | Promise<string | null>;
}

/** mount() 的返回值，Host 用于卸载并清理全部副作用。 */
export interface MountResult {
  unmount: () => void;
}

// ---------------------------------------------------------------------------
// Story Forge 创作引擎
// ---------------------------------------------------------------------------

export type StoryProjectStatus = "drafting" | "ongoing" | "completed";

export interface StoryProject {
  id: string;
  title: string;
  synopsis: string;
  genre: string;
  status: StoryProjectStatus;
  character_asset_ids: string[];
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** 列表聚合统计（可选字段） */
  chapter_count?: number;
  total_words?: number;
}

export type ChapterStatus = "outline" | "draft" | "done";

export interface StoryChapter {
  id: string;
  project_id: string;
  chapter_no: number;
  title: string;
  outline: string;
  content: string;
  status: ChapterStatus;
  word_count: number;
  model: string;
  task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoryCharacter {
  id: string;
  project_id: string;
  character_asset_id: string | null;
  name: string;
  role: "protagonist" | "supporting";
  description: string;
  goals: string;
  arc: string;
  current_state: string;
  skill_ids: string[];
}

export interface SerialSchedule {
  id: string;
  project_id: string;
  interval_minutes: number;
  batch_size: number;
  next_run_at: string;
  chapter_count: number;
  status: "active" | "paused";
  mode: "narrative" | "script";
  last_run_at: string;
  error_message: string;
  fail_count: number;
}

export interface StoryBible {
  project: StoryProject;
  chapters: StoryChapter[];
  characters: StoryCharacter[];
}

export type CrewStage = "director" | "writer" | "editor" | "stagehand";

/** 统一本地搜索结果项（scope: knowledge|story|prompts|agents|assets）。 */
export interface SearchResultItem {
  scope: "knowledge" | "story" | "prompts" | "agents" | "assets" | "asmr";
  id: string;
  title: string;
  snippet: string;
  score: number;
  meta: Record<string, unknown>;
}

/** ASMR 作品元数据（多来源聚合）。 */
export interface AsmrWork {
  id: string;
  source: string;
  source_work_id: string;
  title: string;
  circle_name: string;
  price: number;
  release_date: string | null;
  duration_seconds: number;
  rate_average: number;
  dl_count: number;
  nsfw: boolean;
  age_category: string;
  has_subtitle: boolean;
  cover_url: string;
  thumbnail_url: string;
  source_url: string;
  vas?: string[];
  tags?: { name: string; zh: string }[];
  langs?: string[];
  has_chinese?: boolean;
}

/** 角色原著档案（蒸馏产物）。 */
export interface CharacterMemoryProfile {
  asset_id: string;
  book_title: string;
  source_doc_id: string | null;
  identity: string;
  personality: string;
  speech_style: string;
  knowledge_bounds: string;
  relationships: { name: string; relation: string; note: string }[];
  core_memories: { event: string; time: string; impact: string }[];
  status: string;
  error: string;
  updated_at: string | null;
}

/** 角色陪伴记忆总览（原著档案 + 交互记忆 L1/L2/L3 + 注入配置）。 */
export interface CharacterMemoryOverview {
  asset_id: string;
  profile: CharacterMemoryProfile | null;
  atoms: {
    id: string;
    content: string;
    type: string;
    scene: string;
    priority: number | null;
    created_at: string;
  }[];
  scenarios: { name: string; summary: string; heat: number; path: string }[];
  persona: string;
  config: { inject: boolean; budget: number };
}
