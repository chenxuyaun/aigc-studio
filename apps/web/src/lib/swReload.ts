/**
 * Service Worker 新版本检测。
 *
 * 部署新版本后 SW 更新并接管（clientsClaim）会触发 controllerchange——
 * 此时页面仍在跑旧 bundle。不再强制刷新（避免打断用户操作），改为发出
 * `aigc:new-version` 自定义事件，由 AppShell 展示「新版本可用」提示条，
 * 用户点击后手动刷新。配合 ErrorBoundary 的动态 import 失败自动刷新兜底。
 */
let installed = false;

export function installSwReloadHandler(): void {
  if (installed) return;
  installed = true;
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    window.dispatchEvent(new CustomEvent("aigc:new-version"));
  });
  // 定期后台检查更新，发现新版本即提示
  window.setInterval(() => {
    navigator.serviceWorker
      .getRegistration()
      .then((reg) => {
        reg?.update().catch(() => {});
      })
      .catch(() => {});
  }, 60 * 60 * 1000); // 每小时
}
