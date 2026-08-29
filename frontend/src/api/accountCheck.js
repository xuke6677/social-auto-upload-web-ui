import { http } from '@/utils/request'

// 账号登录状态批量检查（并发池模式）
// 与 PrePublishCheckDialog 内部批量检查同一套模式：
// 并发上限默认 2 —— 每个检查都会拉起一个无头浏览器，且占用后端线程，
// 并发过大会把机器/后端线程池打满（详见 PrePublishCheckDialog.vue 注释）。

// 单账号登录状态检查（GET /checkAccount，后端 120s 超时代理）
export function checkAccountStatus(id) {
  return http.get('/checkAccount', { id })
}

/**
 * 并发池批量检查账号登录状态
 * @param {Array} accounts 待检查账号列表（需含 id 字段）
 * @param {Object} options
 * @param {number} [options.concurrency=2] 并发上限
 * @param {() => boolean} [options.shouldAbort] 返回 true 时停止取新任务并忽略后续结果（组件卸载/被新一轮取代）
 * @param {(account) => void} [options.onAccountStart] 单个账号开始检查
 * @param {(account, { valid: boolean, error: any }) => void} [options.onAccountResult] 单个账号检查完成
 * @returns {Promise<void>} 全部完成（或被中止）后 resolve
 */
export async function checkAccountsConcurrently(accounts, {
  concurrency = 2,
  shouldAbort = () => false,
  onAccountStart,
  onAccountResult,
} = {}) {
  const queue = [...accounts]

  const worker = async () => {
    while (queue.length > 0 && !shouldAbort()) {
      const account = queue.shift()
      if (!account) break
      onAccountStart?.(account)
      let valid = false
      let error = null
      try {
        const res = await checkAccountStatus(account.id)
        valid = res?.code === 200 && !!res?.data?.valid
      } catch (e) {
        error = e
      }
      if (shouldAbort()) return
      onAccountResult?.(account, { valid, error })
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, queue.length) },
    () => worker()
  )
  await Promise.all(workers)
}
