import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Select } from "./Select";
import { Tabs } from "./Tabs";
import { Tooltip } from "./Tooltip";
import { EmptyQuery, EmptyState } from "./States";

describe("UI 原语", () => {
  it("Select 渲染选项且箭头装饰不参与读屏", () => {
    render(
      <Select aria-label="排序">
        <option value="a">A</option>
        <option value="b">B</option>
      </Select>,
    );
    const sel = screen.getByRole("combobox");
    expect(sel).toHaveValue("a");
    expect(screen.queryAllByRole("img", { hidden: false })).toHaveLength(0);
  });

  it("Tabs 切换选中态并回调", () => {
    const on = vi.fn();
    render(<Tabs value="a" onValueChange={on} items={[{ value: "a", label: "甲" }, { value: "b", label: "乙" }]} />);
    const tabA = screen.getByRole("tab", { name: "甲" });
    const tabB = screen.getByRole("tab", { name: "乙" });
    expect(tabA).toHaveAttribute("aria-selected", "true");
    expect(tabB).toHaveAttribute("aria-selected", "false");
    fireEvent.click(tabB);
    expect(on).toHaveBeenCalledWith("b");
  });

  it("Tooltip 内容存在且初始不可见", () => {
    render(
      <Tooltip label="删除">
        <button>×</button>
      </Tooltip>,
    );
    expect(screen.getByRole("tooltip")).toHaveTextContent("删除");
    expect(screen.getByRole("tooltip").className).toContain("opacity-0");
  });

  it("EmptyQuery 提供清除筛选动作", () => {
    const on = vi.fn();
    render(<EmptyQuery onReset={on} />);
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(on).toHaveBeenCalled();
  });

  it("EmptyState 与 EmptyQuery 语义区分", () => {
    render(<EmptyState title="还没有内容" />);
    expect(screen.getByText("还没有内容")).toBeInTheDocument();
  });
});
