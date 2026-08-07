import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";

describe("App 启动", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/");
  });

  it("未登录时整站引导到登录页", async () => {
    render(<App />);
    // 路由守卫将 "/" 重定向到登录页，证明 Router + 守卫 + AppShell 装配无运行时错误。
    expect(await screen.findByRole("button", { name: "登录" })).toBeInTheDocument();
  });
});
