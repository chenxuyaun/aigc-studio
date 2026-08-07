import { StrictMode } from "react";

import { createRoot } from "react-dom/client";

import App from "./microfrontend/App";
import { installSwReloadHandler } from "./lib/swReload";
import "@xyflow/react/dist/style.css";
import "./styles/index.css";

// 部署新版本后 SW 接管 → 自动刷新到新 bundle（防旧 chunk 404）
installSwReloadHandler();

// Standalone 独立模式入口：无 Host props，App 内部使用自身 Router。
const container = document.getElementById("root");
if (!container) {
  throw new Error("根节点 #root 不存在");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
