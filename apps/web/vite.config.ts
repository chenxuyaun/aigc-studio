import path from "node:path";

import { federation } from "@module-federation/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vite";

/**
 * AIGC Studio 前端构建配置。
 *
 * 同时产出：
 *  - Standalone 独立站点（宿主机 5000 → 容器 nginx）。
 *  - Remote 微前端入口 remoteEntry.js（暴露 ./App ./Routes ./mount ./types）。
 *  - PWA：manifest + service worker（Workbox），手机可「添加到主屏幕」当 App 用。
 */
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    federation({
      name: "aigc_studio",
      filename: "remoteEntry.js",
      exposes: {
        "./App": "./src/microfrontend/App.tsx",
        "./Routes": "./src/microfrontend/Routes.tsx",
        "./mount": "./src/microfrontend/mount.tsx",
        "./types": "./src/microfrontend/types.ts",
      },
      shared: {
        react: { singleton: true, requiredVersion: "^19.0.0" },
        "react-dom": { singleton: true, requiredVersion: "^19.0.0" },
        "react-router-dom": { singleton: true },
      },
    }),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["pwa-192.png", "pwa-512.png"],
      manifest: {
        name: "AIGC Studio · AI 创作中心",
        short_name: "AIGC Studio",
        description: "AI 创作工作台：文本/图片/视频/语音生成、知识库、Agent",
        theme_color: "#e8912a",
        background_color: "#faf9f6",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/pwa-maskable-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "maskable",
          },
          {
            src: "/pwa-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/health/],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5180,
    proxy: {
      "/api": { target: "http://127.0.0.1:8002", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8002", changeOrigin: true },
    },
  },
  build: {
    target: "esnext",
    outDir: "dist",
    // 避免与 SPA 客户端路由 /assets 冲突（否则刷新 /assets 命中物理目录 → nginx 403）。
    assetsDir: "static",
  },
});
