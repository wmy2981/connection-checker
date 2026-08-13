/** 复制文本到剪贴板，多方案降级：Clipboard API → execCommand → 调用方提示手动复制。 */

export async function copyText(text: string): Promise<boolean> {
  // 方案 1：Clipboard API（HTTPS 或 localhost 下可用；http 内网部署时不可用）
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* 权限被拒或非安全上下文，继续降级 */
    }
  }
  // 方案 2：隐藏 textarea + execCommand（传统 http 环境可用）
  // 注意两点（2026-08 线上 bug 的教训）：
  // 1. textarea 必须「可渲染但移出视口」——opacity:0 / display:none 会让 Chrome 的
  //    execCommand('copy') 返回 true 但实际复制空或旧选区；
  // 2. 挂在焦点元素所在的 dialog 容器内——naive-ui NModal 的 focus trap 会把挂到
  //    body 的 textarea 焦点拉回并清除选区，导致 modal 内复制失效（id/检查数据
  //    复制失败、页面本体令牌复制正常，正是此差异）。
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'absolute'
    ta.style.left = '-9999px'
    ta.style.top = '0'
    const container =
      (document.activeElement?.closest('[role="dialog"]') as HTMLElement | null) ?? document.body
    container.appendChild(ta)
    const selection = document.getSelection()
    const prevRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    ta.remove()
    if (prevRange && selection) {
      selection.removeAllRanges()
      selection.addRange(prevRange)
    }
    if (ok) return true
  } catch {
    /* 继续降级 */
  }
  // 方案 3：均失败，由调用方提示手动复制
  return false
}
