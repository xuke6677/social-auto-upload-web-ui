/**
 * 标签输入框通用工具：批量解析 + 平台限长截断
 *
 * 需求 A：粘贴 `#AI神器 #开源` 或 `AI神器,开源`（中英逗号都支持）按回车拆成多个标签。
 * 需求 B：按平台配置(platforms.js 的 maxTags)截断，超限丢弃后面的标签并轻提示。
 */

/**
 * 把一段原始输入解析成标签数组。
 * 规则：按 `#` / 英文逗号 / 中文逗号 分割，去掉每项前后空格，丢弃空项，按首次出现顺序去重。
 *
 * @param {string} raw
 * @returns {string[]}
 *
 * 示例:
 *   "#AI神器 #开源 #白板动画" => ["AI神器", "开源", "白板动画"]
 *   "AI神器,开源，白板动画"  => ["AI神器", "开源", "白板动画"]
 *   "单个标签"               => ["单个标签"]
 */
export function parseTagInput(raw) {
  if (!raw) return []
  const seen = new Set()
  const result = []
  for (const piece of String(raw).split(/[#，,]/)) {
    const tag = piece.trim()
    if (!tag || seen.has(tag)) continue
    seen.add(tag)
    result.push(tag)
  }
  return result
}

/**
 * 把解析出的标签追加到目标数组（原地修改）。
 * - 与 target 中已有标签去重（重复项计入 dups，不报错）
 * - maxTags 为数字时按上限截断：target 已有数 + reserved 达到上限后，后续标签丢弃（计入 overflowed）
 *
 * @param {Array<string>} target - 响应式标签数组
 * @param {string[]} parsed - parseTagInput 的结果
 * @param {object} [options]
 * @param {number} [options.maxTags] - 平台上限（含 target 已有项和 reserved）；不传则不限
 * @param {number} [options.reserved] - 占用配额但不在 target 中的数量（如抖音官方活动数）
 * @returns {{ added: string[], dups: string[], overflowed: number }}
 */
export function appendTags(target, parsed, { maxTags, reserved = 0 } = {}) {
  const added = []
  const dups = []
  let overflowed = 0
  for (const tag of parsed) {
    if (target.includes(tag)) { dups.push(tag); continue }
    if (typeof maxTags === 'number' && target.length + reserved >= maxTags) { overflowed++; continue }
    target.push(tag)
    added.push(tag)
  }
  return { added, dups, overflowed }
}
