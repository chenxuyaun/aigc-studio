/**
 * 提示词模板变量解析与替换。
 *
 * 数据源（prompt.qqsrc.com 画廊）约 86% 的提示词含模板变量：
 *   {argument name="theme" default="火车摄影"}
 * 部分条目是 JSON 转义后的形式（\" 表示字面引号）：
 *   {argument name=\"headline text\" default=\"...\"}
 * 本模块两种形式都解析；替换时把残留的 \" 还原为普通引号。
 */

export interface TemplateVariable {
  name: string;
  defaultValue: string;
}

const ARG_BLOCK = /\{argument\s+([^}]*)\}/g;

/**
 * 从块内部文本提取 name/default 值。
 * 先把转义引号 \" 还原为 "，再按键匹配：
 * - name 值内不会出现引号，用非贪婪匹配
 * - default 值可能内嵌引号（如 变成"超会聊天"的小助手），用贪婪匹配到块末尾的最后一个引号
 */
function extractStringValue(inner: string, key: "name" | "default"): string {
  const unescaped = inner.replace(/\\"/g, '"');
  const pattern =
    key === "default" ? `${key}="([\\s\\S]*)"` : `${key}="([^"]*)"`;
  const m = unescaped.match(new RegExp(pattern));
  if (!m) return "";
  return (m[1] ?? "").trim();
}

/** 解析文本中的模板变量（按出现顺序去重）。 */
export function parseTemplateVariables(content: string): TemplateVariable[] {
  const vars: TemplateVariable[] = [];
  const seen = new Set<string>();
  for (const m of content.matchAll(ARG_BLOCK)) {
    const name = extractStringValue(m[1] ?? "", "name");
    if (!name || seen.has(name)) continue;
    seen.add(name);
    vars.push({ name, defaultValue: extractStringValue(m[1] ?? "", "default") });
  }
  return vars;
}

/** 把变量值替换进模板；未提供值的变量保留原块；顺带清理数据源残留的转义引号。 */
export function applyTemplateValues(
  content: string,
  values: Record<string, string>,
): string {
  const replaced = content.replace(ARG_BLOCK, (block, inner: string) => {
    const name = extractStringValue(inner, "name");
    if (name && name in values) return values[name] ?? "";
    return block;
  });
  return replaced.replaceAll(/\\"/g, '"');
}
