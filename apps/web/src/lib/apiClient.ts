import type { ApiError } from "@aigc/shared-types";

/** 统一领域错误：所有外部错误在边界转换为 AppError，业务层只处理它。 */
export class AppError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | undefined;
  readonly details: unknown;

  constructor(params: {
    code: string;
    message: string;
    status: number;
    requestId?: string | undefined;
    details?: unknown;
  }) {
    super(params.message);
    this.name = "AppError";
    this.code = params.code;
    this.status = params.status;
    this.requestId = params.requestId;
    this.details = params.details;
  }
}

type TokenGetter = () => string | null;
type TokenSetter = (access: string, refresh: string) => void;
type UnauthorizedHandler = () => void;

let getToken: TokenGetter = () => null;
let getRefreshToken: TokenGetter = () => null;
let setTokens: TokenSetter = () => {};
let onUnauthorized: UnauthorizedHandler = () => {};
let baseUrl = "/api/v1";
let isRefreshing = false;
let refreshQueue: Array<(token: string | null) => void> = [];

/** 由应用启动时注入 token 来源 / 401 处理 / API 根地址（支持宿主覆盖）。 */
export function configureApiClient(opts: {
  getToken?: TokenGetter;
  getRefreshToken?: TokenGetter;
  setTokens?: TokenSetter;
  onUnauthorized?: UnauthorizedHandler;
  baseUrl?: string;
}): void {
  if (opts.getToken) getToken = opts.getToken;
  if (opts.getRefreshToken) getRefreshToken = opts.getRefreshToken;
  if (opts.setTokens) setTokens = opts.setTokens;
  if (opts.onUnauthorized) onUnauthorized = opts.onUnauthorized;
  if (opts.baseUrl) baseUrl = opts.baseUrl;
}

/** 尝试刷新 access_token。成功返回新 token，失败返回 null。 */
export async function tryRefreshToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  // 防止并发刷新：已在刷新中则排队等待。
  if (isRefreshing) {
    return new Promise((resolve) => {
      refreshQueue.push(resolve);
    });
  }

  isRefreshing = true;
  try {
    const res = await fetch(`${baseUrl}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token: string; refresh_token: string };
    setTokens(data.access_token, data.refresh_token);
    // 通知排队中的请求。
    refreshQueue.forEach((cb) => cb(data.access_token));
    refreshQueue = [];
    return data.access_token;
  } catch {
    return null;
  } finally {
    isRefreshing = false;
  }
}

export function apiBaseUrl(): string {
  return baseUrl;
}

/** 429 等临时错误不清除登录态，仅抛出 AppError 供上层展示。 */
export class RateLimitError extends AppError {
  readonly retryAfter: number;
  constructor(retryAfter: number, requestId?: string) {
    super({
      code: "RATE_LIMITED",
      message: "请求过于频繁，请稍后再试",
      status: 429,
      requestId,
    });
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

/**
 * 生成请求 ID。crypto.randomUUID 仅在安全上下文（HTTPS/localhost）可用，
 * 本项目常以 http://IP:5000 部署，因此提供非安全上下文回退。
 */
function randomId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") {
    try {
      return c.randomUUID();
    } catch {
      // 非安全上下文下 randomUUID 可能抛错，走回退。
    }
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16);
    const v = ch === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Request-ID", randomId());
  return headers;
}

async function toAppError(res: Response): Promise<AppError> {
  let code = "ERROR";
  let message = `请求失败 (${res.status})`;
  let details: unknown;
  let requestId: string | undefined = res.headers.get("X-Request-ID") ?? undefined;
  try {
    const body = (await res.json()) as { error?: ApiError; request_id?: string };
    if (body.error) {
      code = body.error.code;
      message = body.error.message;
      details = body.error.details;
    }
    if (body.request_id) requestId = body.request_id;
  } catch {
    // 非 JSON 响应，保留默认信息。
  }
  // 429 限流：返回特殊错误，不触发登出。
  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After") || 60);
    return new RateLimitError(retryAfter, requestId);
  }
  return new AppError({ code, message, status: res.status, requestId, details });
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers = authHeaders();
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(body);
  }
  if (signal) init.signal = signal;
  const res = await fetch(`${baseUrl}${path}`, init);
  // 401：尝试刷新 token 后重试一次。
  if (res.status === 401) {
    const newToken = await tryRefreshToken();
    if (newToken) {
      // 用新 token 重试原请求。
      const retryHeaders = authHeaders();
      const retryInit: RequestInit = { method, headers: retryHeaders };
      if (body !== undefined) {
        retryHeaders.set("Content-Type", "application/json");
        retryInit.body = JSON.stringify(body);
      }
      if (signal) retryInit.signal = signal;
      const retryRes = await fetch(`${baseUrl}${path}`, retryInit);
      if (retryRes.ok) {
        if (retryRes.status === 204) return undefined as T;
        return (await retryRes.json()) as T;
      }
      // 重试仍失败，抛出错误。
      throw await toAppError(retryRes);
    }
    // 刷新失败或无 refresh_token，登出。
    onUnauthorized();
    throw await toAppError(res);
  }
  if (!res.ok) throw await toAppError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function getBlob(path: string): Promise<Blob> {
  const res = await fetch(`${baseUrl}${path}`, { headers: authHeaders() });
  if (res.status === 401) {
    const newToken = await tryRefreshToken();
    if (newToken) {
      const retryRes = await fetch(`${baseUrl}${path}`, { headers: authHeaders() });
      if (retryRes.ok) return retryRes.blob();
      throw await toAppError(retryRes);
    }
    onUnauthorized();
    throw await toAppError(res);
  }
  if (!res.ok) throw await toAppError(res);
  return res.blob();
}

/** multipart 上传（写真摄影等多文件场景）。不要手动设 Content-Type，让浏览器带 boundary。 */
async function postForm<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  const headers = authHeaders();
  const init: RequestInit = { method: "POST", headers, body: form };
  if (signal) init.signal = signal;
  const res = await fetch(`${baseUrl}${path}`, init);
  if (res.status === 401) {
    const newToken = await tryRefreshToken();
    if (newToken) {
      const retryHeaders = authHeaders();
      const retryInit: RequestInit = { method: "POST", headers: retryHeaders, body: form };
      if (signal) retryInit.signal = signal;
      const retryRes = await fetch(`${baseUrl}${path}`, retryInit);
      if (retryRes.ok) {
        if (retryRes.status === 204) return undefined as T;
        return (await retryRes.json()) as T;
      }
      throw await toAppError(retryRes);
    }
    onUnauthorized();
    throw await toAppError(res);
  }
  if (!res.ok) throw await toAppError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 带上传进度回调的 multipart 上传（XHR 实现，fetch 不暴露上传进度）。 */
export async function postFormWithProgress<T>(
  path: string,
  form: FormData,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const headers = authHeaders();
  const doSend = (): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${baseUrl}${path}`);
      const auth = headers.get("Authorization");
      if (auth) xhr.setRequestHeader("Authorization", auth);
      xhr.setRequestHeader("X-Request-ID", headers.get("X-Request-ID") ?? randomId());
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(xhr.responseText ? (JSON.parse(xhr.responseText) as T) : (undefined as T));
          } catch {
            reject(new AppError({ code: "PARSE_ERROR", message: "响应解析失败", status: xhr.status }));
          }
        } else {
          reject(new AppError({ code: "HTTP_ERROR", message: `上传失败 (${xhr.status})`, status: xhr.status }));
        }
      };
      xhr.onerror = () => reject(new AppError({ code: "NETWORK_ERROR", message: "网络错误", status: 0 }));
      xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
      if (signal) {
        signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }
      xhr.send(form);
    });
  try {
    return await doSend();
  } catch (err) {
    // 401 时刷新后重试一次
    if (err instanceof AppError && err.status === 401) {
      const newToken = await tryRefreshToken();
      if (newToken) return doSend();
      onUnauthorized();
    }
    throw err;
  }
}

export const apiClient = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>("POST", path, body, signal),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  getBlob,
  postForm,
  postFormWithProgress,
};

export interface SseEvent {
  type?: string;
  content?: string;
  [key: string]: unknown;
}

/**
 * 以 fetch + ReadableStream 消费 SSE（用于文本流式生成）。
 * 逐条把 `data:` 行解析为 JSON 回调，直到流结束或被 abort。
 */
export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = authHeaders({ "Content-Type": "application/json" });
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });
  if (!res.ok) throw await toAppError(res);
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as SseEvent);
      } catch {
        // 忽略无法解析的行。
      }
    }
  }
}
