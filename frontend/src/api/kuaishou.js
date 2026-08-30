import { http } from '@/utils/request'

// 拼接查询串:自动跳过 null/undefined/空串,避免把 "null" 拼进 URL
function buildQuery(params) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return q ? `?${q}` : ''
}

// 快手创作者平台相关 API(后端 blueprint: backend/blueprints/kuaishou_bp.py)
export const kuaishouApi = {
  // 合集列表(后端 CloakBrowser 打开发布页抓取,一次返回全量)
  // accountId 可空:为空时后端用数据库里任意一个快手账号的 cookie
  getCollections(accountId) {
    return http.get(`/api/kuaishou/collections${buildQuery({ account_id: accountId })}`)
  },
}
