/**
 * 账号默认合集 — 平台差异化配置的唯一真实来源
 *
 * 存储格式（后端 account_settings.default_collection，按账号一条）：
 *   { name: '合集名', id: '合集id(可空)', data: {完整合集对象} }
 *
 * 每个平台提供：
 *   fieldMap     RemoteSearchSelect 的字段映射
 *   makeFetcher  (accountId) => (keyword) => Promise<{list}>
 *   toOverrides  (def) => 发布页 form/mergeConfig 使用的字段集合
 *
 * 支持合集的平台：抖音/小红书/B站/快手/视频号/微博/公众号/支付宝/头条
 */
import { xhsApi } from '@/api/xiaohongshu'
import { biliApi } from '@/api/bilibili'
import { kuaishouApi } from '@/api/kuaishou'
import { channelsApi } from '@/api/channels'
import { weiboApi } from '@/api/weibo'
import { weixinGzhApi } from '@/api/weixin_gzh'
import { douyinImageApi } from '@/api/douyinImage'
import { alipayApi } from '@/api/alipay'
import { toutiaoApi } from '@/api/toutiao'

// 后端一次返回全量、前端按关键词过滤的通用 fetcher 工厂
function _clientFilterFetcher(fetchAll, labelKey) {
  return async (keyword) => {
    const resp = await fetchAll()
    const all = resp.data?.list || []
    const kw = keyword?.trim().toLowerCase()
    return { list: kw ? all.filter(c => c[labelKey]?.toLowerCase().includes(kw)) : all }
  }
}

const _nameFieldMap = { label: 'name' }

const _xhsFieldMap = {
  label: 'name',
  key: 'id',
  desc: (item) => item.note_num != null
    ? (item.note_num > 0 ? `共 ${item.note_num} 篇` : '暂无内容')
    : ''
}

// 支付宝/头条合集:title 主标题,category+total 派生描述,coverUrl 扁平封面
const _compilationFieldMap = {
  label: 'title',
  key: 'compilationId',
  desc: (item) => {
    const parts = []
    if (item.category) parts.push(item.category)
    if (item.total != null) parts.push(`${item.total} 个内容`)
    return parts.join(' · ')
  },
  cover: 'coverUrl'
}

const _douyinMixFieldMap = {
  label: 'mix_name',
  key: 'mix_id',
  desc: 'desc',
  cover: 'cover_url.url_list.0'
}

export const COLLECTION_PLATFORMS = {
  douyin: {
    fieldMap: _douyinMixFieldMap,
    makeFetcher: (accountId) => async (keyword) => {
      const resp = await douyinImageApi.getMixList(accountId)
      const all = resp.data?.mix_list || []
      const kw = keyword?.trim().toLowerCase()
      return { list: kw ? all.filter(m => m.mix_name?.toLowerCase().includes(kw)) : all }
    },
    // 发布页 form.mixId 实际存的是合集名称(发布时按名称匹配)
    toOverrides: (def) => ({ mixId: def.name, mixData: def.data || null }),
  },
  xiaohongshu: {
    fieldMap: _xhsFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => xhsApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({
      collectionName: def.name,
      collectionId: def.id || '',
      collectionData: def.data || null,
    }),
  },
  bilibili: {
    fieldMap: _nameFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => biliApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({ biliCollectionName: def.name, biliCollectionData: def.data || null }),
  },
  kuaishou: {
    fieldMap: _nameFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => kuaishouApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({ kuaishouCollectionName: def.name, kuaishouCollectionData: def.data || null }),
  },
  channels: {
    fieldMap: _nameFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => channelsApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({ channelsCollectionName: def.name, channelsCollectionData: def.data || null }),
  },
  weibo: {
    fieldMap: _nameFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => weiboApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({ weiboCollectionName: def.name, weiboCollectionData: def.data || null }),
  },
  weixin_gzh: {
    fieldMap: _nameFieldMap,
    makeFetcher: (accountId) => _clientFilterFetcher(() => weixinGzhApi.getCollections(accountId), 'name'),
    toOverrides: (def) => ({ gzhCollectionName: def.name, gzhCollectionData: def.data || null }),
  },
  alipay: {
    fieldMap: _compilationFieldMap,
    makeFetcher: (accountId) => async (keyword) => {
      const resp = await alipayApi.searchCompilation(accountId, keyword || '')
      return { list: resp.data?.list || [] }
    },
    toOverrides: (def) => ({ compilation: def.name, compilationData: def.data || null }),
  },
  toutiao: {
    fieldMap: _compilationFieldMap,
    makeFetcher: (accountId) => async (keyword) => {
      const resp = await toutiaoApi.searchCompilation(accountId, keyword || '')
      return { list: resp.data?.list || [] }
    },
    // 头条 settingsFields 的合集字段 key 是 collection
    toOverrides: (def) => ({ collection: def.name, compilationData: def.data || null }),
  },
}

/**
 * 把账号默认合集转换为发布页对应平台的覆写字段集合。
 * 无默认配置 / 平台不支持合集时返回 null。
 */
export function collectionDefaultsToOverrides(platformKey, def) {
  if (!def || !def.name) return null
  const cfg = COLLECTION_PLATFORMS[platformKey]
  if (!cfg) return null
  return cfg.toOverrides(def)
}
