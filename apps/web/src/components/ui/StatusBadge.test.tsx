import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("展示成功状态的中文文案", () => {
    render(<StatusBadge status="succeeded" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });

  it("展示失败状态的中文文案", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("失败")).toBeInTheDocument();
  });
});
