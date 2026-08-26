/**
 * 批14：复制文本统一入口（修「按钮点击无效」）。
 *
 * 根因：navigator.clipboard 仅安全上下文（HTTPS/localhost）可用——
 * 公网 http://IP 直访时为 undefined，直接调用 = TypeError = 按钮无效。
 * 此前 13 处散落的直调统一收敛到这里：
 * 1) 安全上下文优先 Clipboard API；
 * 2) 否则临时 textarea + execCommand（opacity 不能为 0——部分浏览器
 *    会拒绝复制不可见元素；iOS 需 setSelectionRange）；
 * 3) 两级都失败静默返回 false（调用方可据此决定是否提示），绝不抛未处理异常。
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 权限被拒等 → 走回退。
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.opacity = "0.01";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length); // iOS 兼容
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (ok) return true;
  } catch {
    // 继续走最后兜底。
  }
  // 最后兜底：非安全上下文下 clipboard 对象也可能存在但拒绝
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* 放弃 */
    }
  }
  return false;
}
