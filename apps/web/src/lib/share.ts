/** 分享链接生成（全站统一：音乐作品/提示词等公开分享页的 URL 拼接）。 */

export function shareUrl(kind: "music" | "prompt", id: string): string {
  return `${window.location.origin}/share/${kind}/${encodeURIComponent(id)}`;
}

/** 复制分享链接到剪贴板（返回是否成功）。 */
export async function copyShareUrl(kind: "music" | "prompt", id: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(shareUrl(kind, id));
    return true;
  } catch {
    return false;
  }
}
