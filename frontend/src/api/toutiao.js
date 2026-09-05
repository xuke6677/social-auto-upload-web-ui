import { http } from '@/utils/request'

// 拼接查询串:自动跳过 null/undefined/空串,避免把 "null" 拼进 URL
// (account_id=null 会让后端按 id='null' 查库 → 404「没有可用的今日头条账号」)
function buildQuery(params) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return q ? `?${q}` : ''
}

// 今日头条内容创作平台相关 API(后端 blueprint: backend/blueprints/toutiao_bp.py)
export const toutiaoApi = {
  // 搜索合集(后端通过 CloakBrowser 拦截 pSeries/simpleGetAlbumInfoByMediaId)
  // accountId 可空:为空时后端用数据库里任意一个头条账号的 cookie
  searchCompilation(accountId, keyword) {
    return http.get(`/api/toutiao/compilation-search${buildQuery({ account_id: accountId, keyword })}`)
  },
}
