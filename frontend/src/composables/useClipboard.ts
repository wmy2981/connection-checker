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
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    const selection = document.getSelection()
    const prevRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
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
