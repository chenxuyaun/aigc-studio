/**
 * Service Worker 新版本检测。
 *
 * 策略（治「部署后没变化」）：
 * 1. controllerchange（新版 SW 已接管）时：
 *    - 页面在后台 → 立即自动刷新（用户看不到，零打扰，回来就是新版）；
 *    - 页面在前台 → 保持原行为：发 `aigc:new-version` 事件，AppShell 展示
 *      「新版本可用」提示条由用户手动刷新（不打断正在进行的流式生成）。
 * 2. 更新检查时机：页面重新可见（切回标签页/手机亮屏）+ 每 15 分钟轮询，
 *    替代原来的每小时——部署后最迟几分钟内即可拿到新版。
 *
 * 配合 ErrorBoundary 的动态 import 失败自动刷新兜底。
 */
let installed = false;

export function installSwReloadHandler(): void {
  if (installed) return;
  installed = true;
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    // 新 SW 接管：后台页直接刷新（无打断风险）；前台页交给提示条
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      window.location.reload();
      return;
    }
    window.dispatchEvent(new CustomEvent("aigc:new-version"));
  });

  const checkUpdate = (): void => {
    navigator.serviceWorker
      .getRegistration()
      .then((reg) => {
        reg?.update().catch(() => {});
      })
      .catch(() => {});
  };

  // 切回页面时检查更新（PWA 冷启动 / 标签页切回的最高频时机）
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkUpdate();
  });
  // 兜底轮询：15 分钟
  window.setInterval(checkUpdate, 15 * 60 * 1000);
}
