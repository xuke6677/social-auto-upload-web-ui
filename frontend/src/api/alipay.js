import { http } from '@/utils/request'

// 拼接查询串:自动跳过 null/undefined/空串,避免把 "null" 拼进 URL
// (account_id=null 会让后端按 id='null' 查库 → 404「没有可用的支付宝账号」)
function buildQuery(params) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return q ? `?${q}` : ''
}

// 支付宝内容创作平台相关 API(后端 blueprint: backend/blueprints/alipay_bp.py)
export const alipayApi = {
  // 搜索合集(后端通过 CloakBrowser 拦截 queryCompilationsByPublicId.json)
  // accountId 可空:为空时后端用数据库里任意一个支付宝账号的 cookie
  searchCompilation(accountId, keyword) {
    return http.get(`/api/alipay/compilation-search${buildQuery({ account_id: accountId, keyword })}`)
  },

  // 获取图集背景音乐列表(后端打开 short-content 页 + 拦截 queryAllMaterial.json,
  // 一次性返回全部音乐,前端客户端分页)
  // accountId 可空:为空时后端用数据库里任意一个支付宝账号的 cookie
  musicList(accountId) {
    return http.get(`/api/alipay/music-list${buildQuery({ account_id: accountId })}`)
  },
}
