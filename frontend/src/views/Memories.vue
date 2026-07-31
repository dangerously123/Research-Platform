<template>
  <div class="memories-page">
    <div class="header-row">
      <h3>我的记忆</h3>
      <el-button type="danger" plain @click="handleClearAll"
        :disabled="!memories.length || clearing" :loading="clearing">
        清空全部
      </el-button>
    </div>

    <!-- 搜索区 -->
    <div class="search-bar">
      <el-input v-model="searchQuery" placeholder="语义搜索记忆..." clearable @clear="loadMemories">
        <template #append>
          <el-button @click="doSearch" :loading="searching">搜索</el-button>
        </template>
      </el-input>
      <el-select v-model="topicFilter" placeholder="按主题筛选" clearable @change="loadMemories" style="width:160px">
        <el-option label="全部" value="" />
        <el-option label="数据分析" value="数据分析" />
        <el-option label="技术" value="技术" />
        <el-option label="运维" value="运维" />
        <el-option label="流程" value="流程" />
        <el-option label="权限管理" value="权限管理" />
        <el-option label="销售" value="销售" />
        <el-option label="通用" value="通用" />
      </el-select>
    </div>

    <!-- 搜索结果 -->
    <div v-if="searchResults.length" class="search-results">
      <el-alert title="语义搜索结果" type="info" :closable="false" show-icon style="margin-bottom:12px" />
      <el-card v-for="r in searchResults" :key="r.memory_id" class="memory-card" shadow="hover">
        <div class="memory-question">{{ r.question }}</div>
        <div class="memory-answer">{{ r.answer_summary }}</div>
        <div class="memory-meta">
          <el-tag size="small" type="success">相似度: {{ (r.score * 100).toFixed(1) }}%</el-tag>
          <el-tag v-if="r.topic_tags" size="small">{{ r.topic_tags }}</el-tag>
        </div>
      </el-card>
      <el-divider />
    </div>

    <!-- 记忆列表 -->
    <div v-loading="loading" class="memory-list">
      <el-empty v-if="!loading && !memories.length" description="暂无记忆，开始对话后系统会自动保存重要问答" />

      <el-card v-for="mem in memories" :key="mem.id" class="memory-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="memory-question">{{ mem.question }}</span>
            <el-button text type="danger" size="small"
              :loading="deletingIds.has(mem.id)" :disabled="deletingIds.has(mem.id)"
              @click="handleDelete(mem.id)">
              删除
            </el-button>
          </div>
        </template>
        <div class="memory-answer">{{ mem.answer_summary }}</div>
        <div v-if="mem.key_facts?.length" class="key-facts">
          <span class="facts-label">关键事实：</span>
          <el-tag v-for="(fact, i) in mem.key_facts.slice(0, 3)" :key="i" size="small" type="info"
            style="margin-right:4px;margin-bottom:4px">
            {{ fact.length > 30 ? fact.slice(0, 30) + '...' : fact }}
          </el-tag>
        </div>
        <div class="memory-meta">
          <el-tag v-if="mem.topic_tags" size="small">{{ mem.topic_tags }}</el-tag>
          <span class="meta-text">重要性: {{ (mem.importance * 100).toFixed(0) }}%</span>
          <span class="meta-text">被引用: {{ mem.access_count }} 次</span>
          <span class="meta-text">{{ formatDate(mem.created_at) }}</span>
        </div>
      </el-card>

      <!-- 分页 -->
      <el-pagination
        v-if="total > pageSize"
        :current-page="page" :page-size="pageSize" :total="total"
        @current-change="changePage" layout="prev, pager, next" style="margin-top:16px;justify-content:center" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const memories = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const topicFilter = ref('')
const searchQuery = ref('')
const searchResults = ref<any[]>([])
const searching = ref(false)
const clearing = ref(false)
const deletingIds = reactive(new Set<number>())

onMounted(loadMemories)

async function loadMemories() {
  loading.value = true
  searchResults.value = []
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (topicFilter.value) params.topic = topicFilter.value
    const res = await api.get('/memories', { params })
    memories.value = res.data.memories
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

async function doSearch() {
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    return
  }
  if (searching.value) return
  searching.value = true
  try {
    const res = await api.post('/memories/search', { query: searchQuery.value, top_k: 5 })
    searchResults.value = res.data.results
  } catch {
    searchResults.value = []
    ElMessage.error('搜索失败')
  } finally {
    searching.value = false
  }
}

function changePage(p: number) {
  page.value = p
  loadMemories()
}

async function handleDelete(memoryId: number) {
  if (deletingIds.has(memoryId)) return
  await ElMessageBox.confirm('确定删除这条记忆？删除后不可恢复。')
  deletingIds.add(memoryId)
  try {
    await api.delete(`/memories/${memoryId}`)
    ElMessage.success('已删除')
    loadMemories()
  } catch {
    ElMessage.error('删除失败')
  } finally {
    deletingIds.delete(memoryId)
  }
}

async function handleClearAll() {
  if (clearing.value) return
  await ElMessageBox.confirm('确定清空所有记忆？此操作不可撤销！', '警告', { type: 'warning' })
  clearing.value = true
  try {
    await api.delete('/memories')
    ElMessage.success('已清空所有记忆')
    memories.value = []
    total.value = 0
  } catch {
    ElMessage.error('清空失败')
  } finally {
    clearing.value = false
  }
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now.getTime() - d.getTime()) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '昨天'
  if (diff < 7) return `${diff}天前`
  return d.toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.memories-page { max-width: 900px; margin: 0 auto; }
.header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.search-bar { display: flex; gap: 12px; margin-bottom: 20px; }
.search-bar .el-input { flex: 1; }
.memory-card { margin-bottom: 12px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.memory-question { font-weight: 600; font-size: 14px; color: #303133; }
.memory-answer { color: #606266; font-size: 13px; line-height: 1.6; margin: 8px 0; }
.key-facts { margin: 8px 0; }
.facts-label { font-size: 12px; color: #909399; }
.memory-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.meta-text { font-size: 12px; color: #909399; }
.search-results { margin-bottom: 16px; }
</style>
