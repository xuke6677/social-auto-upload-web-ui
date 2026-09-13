<template>
  <div class="personalization-page">
    <div class="page-header">
      <h2>个性化设置</h2>
      <p class="page-desc">为每个账号设置默认合集，视频发布时将自动带入（单个账号设置和批量发布均生效），发布页手动选择会覆盖默认值。</p>
    </div>

    <div v-if="loading" class="loading-state">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>加载中...</span>
    </div>

    <el-empty v-else-if="platformGroups.length === 0" description="暂无支持合集的账号，请先在「账号管理」添加账号" />

    <div v-else class="platform-list">
      <div v-for="group in platformGroups" :key="group.platform.key" class="platform-section">
        <div class="platform-header">
          <img :src="group.platform.logo" class="platform-logo" :alt="group.platform.name" />
          <span class="platform-name">{{ group.platform.name }}</span>
          <span class="account-count">{{ group.accounts.length }} 个账号</span>
        </div>

        <div class="account-cards">
          <div v-for="acc in group.accounts" :key="acc.id" class="account-card">
            <div class="account-info">
              <div class="avatar-wrap">
                <img v-if="acc.avatar" :src="acc.avatar" class="avatar" :alt="acc.name" />
                <div v-else class="avatar avatar-placeholder">{{ (acc.name || '?')[0] }}</div>
                <span class="status-dot" :class="acc.status === '正常' ? 'ok' : 'bad'" :title="acc.status" />
              </div>
              <div class="account-meta">
                <div class="account-name" :title="acc.name">{{ acc.name }}</div>
                <div class="account-status">{{ acc.status }}</div>
              </div>
            </div>

            <div class="collection-setting">
              <div class="setting-label">默认合集</div>
              <RemoteSearchSelect
                v-model="selections[acc.id].name"
                :data="selections[acc.id].data"
                :fetcher="acc._fetcher"
                :field-map="group.fieldMap"
                search-mode="frontend"
                empty-behavior="load-all"
                placeholder="选择默认合集（可留空）"
                search-placeholder="输入合集名称过滤"
                @change="(item) => onCollectionChange(acc, group.platform.key, item)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { accountApi } from '@/api/account'
import { useAccountStore } from '@/stores/account'
import { platformNameToKey, getPlatformByKey } from '@/config/platforms'
import { COLLECTION_PLATFORMS } from '@/config/accountCollections'
import RemoteSearchSelect from '@/components/common/RemoteSearchSelect.vue'

const accountStore = useAccountStore()
const loading = ref(true)

// 每个账号的当前选择（v-model 绑定）
const selections = reactive({})   // { [accountId]: { name, data } }

// 支持合集的平台分组（只列出这些平台的账号）
const platformGroups = computed(() => {
  const groups = {}
  for (const acc of accountStore.accounts) {
    const key = platformNameToKey[acc.platform]
    if (!key || !COLLECTION_PLATFORMS[key]) continue
    if (!groups[key]) {
      groups[key] = {
        platform: getPlatformByKey(key),
        accounts: [],
        fieldMap: COLLECTION_PLATFORMS[key].fieldMap,
      }
    }
    groups[key].accounts.push(acc)
  }
  // fetcher 按账号生成，挂到每个 account 上（避免模板内重复创建）
  const result = Object.values(groups)
  for (const g of result) {
    for (const acc of g.accounts) {
      if (!acc._fetcher) acc._fetcher = COLLECTION_PLATFORMS[g.platform.key].makeFetcher(acc.id)
    }
  }
  return result
})

async function onCollectionChange(acc, platformKey, item) {
  const payload = item
    ? { name: item[COLLECTION_PLATFORMS[platformKey].fieldMap.label] || selections[acc.id].name, id: String(item[COLLECTION_PLATFORMS[platformKey].fieldMap.key] ?? ''), data: item }
    : { name: '', id: '', data: null }
  // 修正 name：RemoteSearchSelect 的 change 值就是 label
  if (item) payload.name = selections[acc.id].name
  selections[acc.id].data = item || null
  try {
    await accountApi.saveDefaultCollection(acc.id, payload)
    ElMessage.success(item ? `已保存「${acc.name}」的默认合集` : `已清空「${acc.name}」的默认合集`)
  } catch (e) {
    ElMessage.error('保存失败，请重试')
  }
}

onMounted(async () => {
  try {
    // 账号列表（store 为空时才拉取）
    if (accountStore.accounts.length === 0) {
      const res = await accountApi.getAccounts()
      accountStore.setAccounts(res.data)
    }
    // 默认合集配置
    const res = await accountApi.getDefaultCollections()
    const map = res.data || {}
    for (const acc of accountStore.accounts) {
      const def = map[String(acc.id)] || {}
      selections[acc.id] = { name: def.name || '', data: def.data || null }
    }
  } catch (e) {
    console.error('加载个性化设置失败:', e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.personalization-page {
  padding: 24px;
  max-width: 1200px;
}

.page-header {
  margin-bottom: 24px;
  h2 {
    margin: 0 0 8px;
    font-size: 22px;
    color: $text-primary;
  }
  .page-desc {
    margin: 0;
    font-size: 13px;
    color: $text-secondary;
    line-height: 1.6;
  }
}

.loading-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 60px 0;
  justify-content: center;
  color: $text-secondary;
}

.platform-section {
  margin-bottom: 28px;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  .platform-logo {
    width: 24px;
    height: 24px;
    border-radius: 6px;
  }
  .platform-name {
    font-size: 16px;
    font-weight: 600;
    color: $text-primary;
  }
  .account-count {
    font-size: 12px;
    color: $text-muted;
  }
}

.account-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}

.account-card {
  background: $bg-surface;
  border: 1px solid $border;
  border-radius: 14px;
  padding: 16px;
  transition: border-color 0.2s, box-shadow 0.2s;

  &:hover {
    border-color: $border-active;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
  }
}

.account-info {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.avatar-wrap {
  position: relative;
  flex-shrink: 0;
}

.avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  object-fit: cover;
}

.avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-brand;
  color: #fff;
  font-size: 17px;
  font-weight: 600;
}

.status-dot {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 2px solid $bg-surface;
  &.ok { background: #22c55e; }
  &.bad { background: #ef4444; }
}

.account-meta {
  min-width: 0;
}

.account-name {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-status {
  margin-top: 2px;
  font-size: 12px;
  color: $text-muted;
}

.collection-setting {
  .setting-label {
    margin-bottom: 8px;
    font-size: 13px;
    color: $text-secondary;
  }
}
</style>
