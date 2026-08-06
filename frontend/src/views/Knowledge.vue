<template>
  <div class="page-shell knowledge-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">知识检索</h1>
        <div class="page-subtitle">输入自然语言问题，获取检索结果与模型回答。</div>
      </div>
    </div>

    <div class="page-panel search-panel">
      <div class="search-bar">
        <el-input
          v-model="query"
          placeholder="输入一个自然语言问题..."
          @keydown.enter="doSearch"
          clearable
          :disabled="loading"
          size="large"
        />
        <el-switch v-model="useLLM" active-text="LLM 回答" inactive-text="仅检索" :disabled="loading" />
        <el-button type="primary" size="large" @click="doSearch" :loading="loading" :disabled="loading || !query.trim()">
          查询
        </el-button>
      </div>

      <div v-if="result" class="result-area">
        <div v-if="result.answer" class="result-card">
          <div class="result-head">
            <h3>AI 回答</h3>
            <el-tag v-if="result.degraded" type="warning" effect="light">LLM 不可用，展示检索结果</el-tag>
          </div>
          <div class="answer-content" v-html="escapeHtml(result.answer)"></div>
        </div>

        <div v-if="result.sources?.length" class="result-card">
          <div class="result-head">
            <h3>来源依据</h3>
            <span class="soft-text">共 {{ result.sources.length }} 条</span>
          </div>
          <el-collapse accordion>
            <el-collapse-item v-for="(source, index) in result.sources" :key="index" :title="source.title">
              <div class="snippet">{{ source.snippet }}</div>
              <el-tag size="small" effect="light">相关度 {{ (source.relevance_score * 100).toFixed(1) }}%</el-tag>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div v-if="!result.has_result" class="empty-state-panel">
          <el-empty description="没有匹配结果，换个问题试试。" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import api from '@/utils/api'

const query = ref('')
const useLLM = ref(true)
const loading = ref(false)
const result = ref<any>(null)
const errorMsg = ref('')

async function doSearch() {
  if (!query.value.trim() || loading.value) return
  loading.value = true
  result.value = null
  errorMsg.value = ''
  try {
    const res = await api.post('/knowledge/search', {
      query: query.value.trim(),
      top_k: 10,
      use_llm: useLLM.value,
    })
    result.value = res.data
  } catch {
    errorMsg.value = 'Search failed. Please retry later.'
    ElNotification({
      title: '检索未完成',
      message: '知识检索暂时没有返回结果，你可以稍后再试一次。',
      type: 'warning',
      position: 'top-right',
      duration: 4200,
    })
  } finally {
    loading.value = false
  }
}

function escapeHtml(text: string): string {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
.knowledge-page {
  max-width: 1100px;
  margin: 0 auto;
}

.search-panel {
  padding: 24px;
}

.search-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search-bar :deep(.el-input) {
  flex: 1;
}

.result-area {
  display: grid;
  gap: 16px;
  margin-top: 18px;
}

.result-card {
  padding: 20px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: var(--app-radius);
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.86) 0%, rgba(30, 41, 59, 0.6) 100%);
}

.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.result-head h3 {
  margin: 0;
  font-size: 16px;
}

.answer-content {
  line-height: 1.9;
  color: var(--app-text);
}

.snippet {
  color: var(--app-text-muted);
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 10px;
}
</style>
