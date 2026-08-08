/** 角色扮演（SillyTavern 功能融入）共享类型。 */

export interface CharacterItem {
  asset_id: string;
  filename: string;
  url: string;
  name?: string;
  /** 多人创作共享：admin 共享后全员可见可用 */
  is_shared?: boolean;
}

export interface CharacterDetail {
  asset_id: string;
  name: string;
  description: string;
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
  alternate_greetings: string[];
  system_prompt: string;
  post_history_instructions: string;
  creator_notes: string;
  tags: string[];
  character_book: Record<string, unknown>;
  talkativeness: number;
  depth_prompt: Record<string, unknown>;
  settings: Record<string, unknown>;
  url: string;
}

export interface ChatSession {
  id: string;
  title: string;
  character_asset_ids: string[];
  group: boolean;
  model: string;
  temperature?: number | null;
  max_tokens?: number | null;
  top_p?: number | null;
  settings: Record<string, unknown>;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  mood?: string;
  created_at?: string;
  /** 备选回复（swipe）：切回历史候选 */
  swipes?: string[];
  swipeIndex?: number;
}

export interface LoreEntry {
  id: string;
  character_name?: string | null;
  keyword: string;
  keywords: string[];
  keysecondary: string[];
  content: string;
  constant: boolean;
  selective: boolean;
  selective_logic: string;
  position: string;
  order_value: number;
  depth: number;
  role: string;
  scan_depth?: number | null;
  case_sensitive: boolean;
  match_whole_words: boolean;
  probability: number;
  enabled: boolean;
}

export interface RegexScript {
  id: string;
  name: string;
  pattern: string;
  replacement: string;
  placement: string;
  enabled: boolean;
  scope: string;
  character_name?: string | null;
}

export interface QuickReply {
  id: string;
  label: string;
  message: string;
  scope: string;
  character_name?: string | null;
  sort_order: number;
  auto?: boolean;
}

export interface Persona {
  id: string;
  name: string;
  description: string;
  avatar_asset_id?: string | null;
}

/** 粗略 token 估算（与后端 worldbook.estimate_tokens 对齐）。 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / 2));
}
