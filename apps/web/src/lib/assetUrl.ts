import { apiClient } from "./apiClient";

/**
 * 资产签名 URL 刷新：/content?sig=... 只保留 10 分钟（ASSET_SIGNED_TTL_SECONDS），
 * 历史消息/最近生成的媒体渲染后很快过期。本 helper 从旧 URL 提取 asset id，
 * 调认证端点重新签发一个新鲜 URL。
 */
export function extractAssetId(url: string): string | null {
  const m = url.match(/\/assets\/([^/?]+)\/(?:content|access-url)/);
  return m?.[1] ?? null;
}

let refreshing = new Set<string>();

/** 用旧签名 URL（或裸 asset id）换一个新鲜签名 URL；失败返回 null。 */
export async function refreshAssetUrl(oldUrl: string): Promise<string | null> {
  const assetId = extractAssetId(oldUrl);
  if (!assetId || refreshing.has(assetId)) return null;
  refreshing.add(assetId);
  try {
    const r = await apiClient.get<{ url?: string }>(`/assets/${assetId}/access-url`);
    return r?.url ?? null;
  } catch {
    return null;
  } finally {
    refreshing.delete(assetId);
  }
}

/** 给 <img>/<audio> 用的 onError 处理器：签名过期自动刷新一次 src。 */
export function makeAssetErrorHandler(getEl: () => { src: string } | null, setSrc: (url: string) => void) {
  return async () => {
    const el = getEl();
    if (!el) return;
    const fresh = await refreshAssetUrl(el.src);
    if (fresh) setSrc(fresh);
  };
}
