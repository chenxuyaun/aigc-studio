import { useEffect, useRef, useState } from "react";

import type { GenerationTask, MediaAccess } from "@aigc/shared-types";

import { AppError, apiClient } from "@/lib/apiClient";
import { toClientApiPath } from "@/lib/paths";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "expired"]);
// 轮询上限：超过即放弃（任务卡死时避免页面永远 busy）
const MAX_ATTEMPTS = 1200; // 1200 × 500ms = 10 分钟

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface MediaTaskResult {
  assetUrl: string;
  mime: string;
  assetId: string;
  isReal?: boolean;
  provider?: string;
  fallbackReason?: string | null;
}

interface MediaTaskState {
  busy: boolean;
  progress: number;
  status: string;
  result: MediaTaskResult | null;
  /** 完整 result JSON（漫画等需要每格数据的类型使用） */
  rawResult: Record<string, unknown> | null;
  error: string | null;
}

const IDLE: MediaTaskState = {
  busy: false,
  progress: 0,
  status: "",
  result: null,
  rawResult: null,
  error: null,
};

/**
 * 通用媒体生成任务：POST 创建 → 轮询进度 → access-url 换取可展示地址。
 */
export function useMediaTask(endpoint: string) {
  const [state, setState] = useState<MediaTaskState>(IDLE);
  const objectUrlRef = useRef<string | null>(null);
  const aliveRef = useRef(true);

  useEffect(
    () => () => {
      aliveRef.current = false;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  function clearUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }

  async function run(
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown> | null> {
    clearUrl();
    aliveRef.current = true;
    setState({ ...IDLE, busy: true, status: "queued" });
    try {
      const task = await apiClient.post<GenerationTask>(endpoint, body);
      if (!aliveRef.current) return null;
      let current = task;
      let attempts = 0;
      while (!TERMINAL.has(current.status) && attempts < MAX_ATTEMPTS) {
        attempts += 1;
        await sleep(500);
        if (!aliveRef.current) return null; // 组件卸载后停止轮询
        current = await apiClient.get<GenerationTask>(`/tasks/${task.id}`);
        setState((s) => ({ ...s, status: current.status, progress: current.progress }));
      }
      if (!TERMINAL.has(current.status)) {
        setState((s) => ({
          ...s,
          busy: false,
          error: "任务超时，请到任务中心查看最新状态",
        }));
        return null;
      }
      if (current.status !== "succeeded") {
        setState((s) => ({ ...s, busy: false, error: current.error_message || "生成失败" }));
        return null;
      }
      // 成功但 result 为空（异常产物）：避免 JSON.parse 崩溃
      if (!current.result) {
        setState((s) => ({ ...s, busy: false, error: "任务成功但缺少结果数据" }));
        return null;
      }
      const parsed = JSON.parse(current.result) as Record<string, unknown> & {
        asset_id: string;
        mime: string;
        access_url_endpoint?: string;
        is_real?: boolean;
        provider?: string;
        fallback_reason?: string | null;
      };
      const accessPath = toClientApiPath(
        parsed.access_url_endpoint ?? `/assets/${parsed.asset_id}/access-url`,
      );
      const access = await apiClient.get<MediaAccess>(accessPath);
      let display = access.url;
      if (!display.startsWith("http://") && !display.startsWith("https://")) {
        const blob = await apiClient.getBlob(toClientApiPath(display));
        display = URL.createObjectURL(blob);
        objectUrlRef.current = display;
      }
      if (!aliveRef.current) return null;
      setState({
        busy: false,
        progress: 100,
        status: "succeeded",
        error: null,
        result: {
          assetUrl: display,
          mime: parsed.mime,
          assetId: parsed.asset_id,
          isReal: Boolean(parsed.is_real),
          provider: parsed.provider ?? "unknown",
          fallbackReason: parsed.fallback_reason ?? null,
        },
        rawResult: parsed,
      });
      return parsed;
    } catch (err) {
      if (!aliveRef.current) return null;
      setState((s) => ({
        ...s,
        busy: false,
        error: err instanceof AppError ? err.message : "生成失败，请重试",
      }));
      return null;
    }
  }

  return { ...state, run };
}
