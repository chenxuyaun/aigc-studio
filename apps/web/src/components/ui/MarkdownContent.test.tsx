import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/apiClient";

import { MarkdownContent } from "./MarkdownContent";

vi.mock("@/lib/apiClient", () => ({
  apiClient: { getBlob: vi.fn() },
}));

beforeEach(() => {
  vi.mocked(apiClient.getBlob).mockReset();
  vi.mocked(apiClient.getBlob).mockResolvedValue(new Blob(["x"], { type: "image/png" }));
  URL.createObjectURL = vi.fn(() => "blob:mock-1");
  URL.revokeObjectURL = vi.fn();
});

describe("MarkdownContent 图片渲染", () => {
  it("外部 http(s) 图片原样直出", async () => {
    render(<MarkdownContent content={"![a](https://example.com/a.png)"} />);
    const img = await screen.findByAltText("a");
    expect(img).toHaveAttribute("src", "https://example.com/a.png");
    expect(apiClient.getBlob).not.toHaveBeenCalled();
  });

  it("私有 /api/ 图片走带鉴权 getBlob 并渲染 blob URL（不再 401 破图）", async () => {
    render(<MarkdownContent content={"![b](/api/v1/assets/abc123/content)"} />);
    const img = await screen.findByAltText("b");
    await waitFor(() => expect(img).toHaveAttribute("src", "blob:mock-1"));
    // apiClient 已带 /api/v1 前缀，markdown 里的绝对前缀应被剥掉
    expect(apiClient.getBlob).toHaveBeenCalledWith("/assets/abc123/content");
  });

  it("私有图片鉴权失败时不渲染破图", async () => {
    vi.mocked(apiClient.getBlob).mockRejectedValue(new Error("401"));
    render(<MarkdownContent content={"![c](/api/v1/assets/dead/content)"} />);
    await waitFor(() => expect(apiClient.getBlob).toHaveBeenCalled());
    await waitFor(() => {
      const img = screen.queryByAltText("c");
      expect(img).not.toBeInTheDocument();
    });
  });
});
