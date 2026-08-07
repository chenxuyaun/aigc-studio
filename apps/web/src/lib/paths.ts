/** 把后端返回的 API 端点（可能带 /api/v1 前缀）转成客户端调用路径。 */
export function toClientApiPath(endpoint: string): string {
  if (endpoint.startsWith("/api/v1")) return endpoint.slice("/api/v1".length) || "/";
  return endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
}
