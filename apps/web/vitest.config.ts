import path from "node:path";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

// 测试配置独立于生产 vite.config，避免 Module Federation 插件干扰 jsdom 环境。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    exclude: [...configDefaults.exclude, "e2e/**", "dist/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      exclude: ["**/*.config.*", "**/test/**", "src/microfrontend/**", "e2e/**"],
    },
  },
});
