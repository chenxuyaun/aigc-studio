import { StrictMode } from "react";

import { createRoot, type Root } from "react-dom/client";

import type { AigcStudioHostProps, MountResult } from "@aigc/shared-types";

import App from "./App";
import { installSwReloadHandler } from "@/lib/swReload";

/**
 * 供宿主系统挂载 Remote 的入口。
 *
 * 宿主调用 mount(el, props)，得到 unmount() 用于卸载并清理 React 树
 * （连带 QueryClient、Router、事件监听等副作用）。
 */
export function mount(container: HTMLElement, props: AigcStudioHostProps = {}): MountResult {
  // 部署新版本后 SW 接管 → 自动刷新到新 bundle（防旧 chunk 404）
  installSwReloadHandler();
  let root: Root | null = createRoot(container);
  root.render(
    <StrictMode>
      <App {...props} />
    </StrictMode>,
  );

  return {
    unmount() {
      root?.unmount();
      root = null;
    },
  };
}

export default mount;
