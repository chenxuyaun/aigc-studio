import type { SyntheticEvent } from "react";

import { usePrivateMediaUrl } from "@/hooks/usePrivateMediaUrl";

interface AssetMediaProps {
  /**
   * access-url 接口端点（如 /assets/{id}/access-url）。
   * 有值时走 JWT + blob 的健壮链路（缓存/重试/到期自动刷新），
   * 历史旧签名 URL（过期/换 key）也能恢复显示。
   */
  accessEndpoint?: string | null;
  /** 兜底 URL：accessEndpoint 未提供或加载中时先用它（旧签名 URL 等）。 */
  fallbackUrl?: string;
  alt?: string;
  className?: string;
  /** img | audio | video */
  kind?: "img" | "audio" | "video";
  controls?: boolean;
  onImgError?: (e: SyntheticEvent<HTMLImageElement>) => void;
}

/**
 * 资产媒体组件：短时签名 URL 过期 / 换 key 导致 401 时，
 * 通过 access-url 接口（携带 JWT）自动换取新的可展示地址，
 * 历史图片/音频/视频也能恢复显示。
 */
export default function AssetMedia({
  accessEndpoint,
  fallbackUrl,
  alt = "",
  className = "",
  kind = "img",
  controls = true,
  onImgError,
}: AssetMediaProps) {
  const { url } = usePrivateMediaUrl(accessEndpoint);
  const src = url ?? fallbackUrl ?? "";

  if (kind === "audio") {
    return <audio src={src} controls={controls} className={className} />;
  }
  if (kind === "video") {
    return <video src={src} controls={controls} className={className} />;
  }
  return <img src={src} alt={alt} className={className} onError={onImgError} />;
}
