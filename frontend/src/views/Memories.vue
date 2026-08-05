<template>
  <div class="memories-page">
    <div class="page-header">
      <h3>My Memories</h3>
      <el-button
        type="danger"
        plain
        :disabled="!memories.length || clearing || loading"
        :loading="clearing"
        @click="handleClearAll"
      >
        Clear All
      </el-button>
    </div>

    <div class="search-bar">
      <el-input
        v-model="searchQuery"
        placeholder="Semantic search memories..."
        clearable
        :disabled="loading || searching"
        @clear="resetSearch"
        @keyup.enter="doSearch"
      >
        <template #append>
          <el-button :loading="searching" :disabled="!searchQuery.trim()" @click="doSearch">Search</el-button>
        </template>
      </el-input>
      <el-select v-model="topicFilter" placeholder="Topic" clearable :disabled="loading || searching" class="topic-select" @change="reloadFirstPage">
        <el-option label="All" value="" />
        <el-option label="General" value="general" />
        <el-option label="Data Analysis" value="data_analysis" />
        <el-option label="Tech" value="tech" />
        <el-option label="Ops" value="ops" />
        <el-option label="Permission" value="permission" />
        <el-option label="Process" value="process" />
        <el-option label="Sales" value="sales" />
      </el-select>
    </div>

    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      closable
      class="page-alert"
      @close="errorMsg = ''"
    />

    <div v-if="searchResults.length" class="search-results">
      <div class="section-header">
        <span>Search Results</span>
        <el-button link type="primary" @click="resetSearch">Back to list</el-button>
      </div>
      <el-card v-for="result in searchResults" :key="result.memory_id" class="memory-card" shadow="hover">
        <div class="memory-question">{{ result.question }}</div>
        <div class="memory-answer">{{ result.answer_summary }}</div>
        <div class="memory-meta">
          <el-tag size="small" type="success">Score {{ Math.round((result.score || 0) * 100) }}%</el-tag>
          <el-tag v-if="result.topic_tags" size="small">{{ result.topic_tags }}</el-tag>
          <span v-if="result.created_at">{{ result.created_at }}</span>
        </div>
      </el-card>
    </div>

    <div v-else v-loading="loading" class="memory-list">
      <el-empty v-if="!loading && !memories.length && !errorMsg" description="No memories yet" />
      <el-card v-for="memory in memories" :key="memory.id" class="memory-card" shadow="hover">
        <div class="memory-card-header">
          <div class="memory-question">{{ memory.question }}</div>
          <el-button
            size="small"
            type="danger"
            plain
            :loading="deletingIds.has(memory.id)"
            :disabled="deletingIds.has(memory.id) || clearing"
            @click="handleDelete(memory.id)"
          >
            Delete
          </el-button>
        </div>
        <div class="memory-answer">{{ memory.answer_summary }}</div>
        <div v-if="memory.key_facts?.length" class="facts">
          <div v-for="fact in memory.key_facts" :key="fact">- {{ fact }}</div>
        </div>
        <div class="memory-meta">
          <el-tag v-if="memory.topic_tags" size="small">{{ memory.topic_tags }}</el-tag>
          <el-tag size="small" type="info">Importance {{ Math.round((memory.importance || 0) * 100) }}%</el-tag>
          <span>Access {{ memory.access_count || 0 }}</span>
          <span>{{ memory.created_at }}</span>
        </div>
      </el-card>

      <el-pagination
        v-if="total > pageSize"
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        :disabled="loading"
        layout="prev, pager, next"
        class="pagination"
        @current-change="changePage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

type MemoryItem = {
  id: number
  question: string
  answer_summary: string
  key_facts?: string[] | null
  topic_tags?: string | null
  importance: number
  access_count: number
  created_at: string
  last_accessed_at?: string | null
}

type SearchResult = {
  memory_id: number
  question: string
  answer_summary: string
  score: number
  topic_tags?: string | null
  created_at?: string | null
}

const memories = ref<MemoryItem[]>([])
const searchResults = ref<SearchResult[]>([])
const searchQuery = ref('')
const topicFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const searching = ref(false)
const clearing = ref(false)
const deletingIds = ref(new Set<number>())
const errorMsg = ref('')
let listRequestId = 0

onMounted(loadMemories)

async function loadMemories() {
  if (loading.value) return
  const requestId = ++listRequestId
  loading.value = true
  errorMsg.value = ''
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (topicFilter.value) params.topic = topicFilter.value
    const res = await api.get('/memories', { params })
    if (requestId !== listRequestId) return
    memories.value = res.data.memories || []
    total.value = res.data.total || 0
  } catch (error: any) {
    if (requestId !== listRequestId) return
    errorMsg.value = error.response?.data?.message || 'Failed to load memories'
    memories.value = []
    total.value = 0
  } finally {
    if (requestId === listRequestId) loading.value = false
  }
}

function reloadFirstPage() {
  page.value = 1
  searchResults.value = []
  loadMemories()
}

function changePage(nextPage: number) {
  if (page.value === nextPage) return
  page.value = nextPage
  loadMemories()
}

async function doSearch() {
  if (!searchQuery.value.trim() || searching.value) return
  searching.value = true
  errorMsg.value = ''
  try {
    const res = await api.post('/memories/search', { query: searchQuery.value.trim(), top_k: 10 })
    searchResults.value = res.data.results || []
    if (!searchResults.value.length) ElMessage.info('No matching memories')
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to search memories'
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

function resetSearch() {
  searchQuery.value = ''
  searchResults.value = []
  loadMemories()
}

async function handleDelete(memoryId: number) {
  if (deletingIds.value.has(memoryId)) return
  try {
    await ElMessageBox.confirm('Delete this memory?', 'Confirm', { type: 'warning' })
  } catch {
    return
  }

  deletingIds.value = new Set(deletingIds.value).add(memoryId)
  try {
    await api.delete(`/memories/${memoryId}`)
    ElMessage.success('Memory deleted')
    await loadMemories()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to delete memory')
  } finally {
    const next = new Set(deletingIds.value)
    next.delete(memoryId)
    deletingIds.value = next
  }
}

async function handleClearAll() {
  if (clearing.value || !memories.value.length) return
  try {
    await ElMessageBox.confirm('Delete all memories? This cannot be undone.', 'Confirm', { type: 'warning' })
  } catch {
    return
  }

  clearing.value = true
  try {
    const res = await api.delete('/memories')
    ElMessage.success(res.data?.message || 'All memories deleted')
    searchResults.value = []
    page.value = 1
    await loadMemories()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to clear memories')
  } finally {
    clearing.value = false
  }
}
</script>

<style scoped>
.memories-page { padding: 0 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.search-bar { display: flex; gap: 12px; margin-bottom: 16px; }
.topic-select { width: 180px; }
.page-alert { margin-bottom: 12px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-weight: 600; }
.memory-list { min-height: 160px; }
.memory-card { margin-bottom: 12px; }
.memory-card-header { display: flex; justify-content: space-between; gap: 12px; }
.memory-question { font-weight: 600; margin-bottom: 8px; }
.memory-answer { color: #606266; line-height: 1.6; }
.facts { margin-top: 8px; color: #606266; }
.memory-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; color: #909399; font-size: 12px; }
.pagination { margin-top: 16px; }
</style>
