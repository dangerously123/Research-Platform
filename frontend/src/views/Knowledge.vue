<template>
  <div class="knowledge-page">
    <h3>知识库检索</h3>
    <div class="search-bar">
      <el-input v-model="query" placeholder="输入自然语言问题..." @keydown.enter="doSearch" clearable />
      <el-switch v-model="useLLM" active-text="LLM回答" inactive-text="仅检索" />
      <el-button type="primary" @click="doSearch" :loading="loading" :disabled="loading">搜索</el-button>
    </div>

    <!-- 错误提示 -->
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" closable
      @close="errorMsg = ''" style="margin-bottom:12px" />

    <div v-if="result" class="result-area">
      <div v-if="result.answer" class="answer-box">
        <h4>AI 回答</h4>
        <div class="answer-content" v-html="escapeHtml(result.answer)"></div>
        <el-tag v-if="result.degraded" type="warning">LLM不可用，以下为原始检索结果</el-tag>
      </div>

      <div v-if="result.sources.length" class="sources-box">
        <h4>参考来源</h4>
        <el-collapse>
          <el-collapse-item v-for="(s, i) in result.sources" :key="i" :title="s.title">
            <div class="snippet">{{ s.snippet }}</div>
            <el-tag size="small">相关度: {{ (s.relevance_score * 100).toFixed(1) }}%</el-tag>
          </el-collapse-item>
        </el-collapse>
      </div>

      <el-empty v-if="!result.has_result" description="未找到匹配结果，请调整问题" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
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
      query: query.value,
      top_k: 10,
      use_llm: useLLM.value,
    })
    result.value = res.data
  } catch {
    errorMsg.value = '搜索失败，请稍后重试'
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
.knowledge-page { max-width: 900px; margin: 0 auto; }
.search-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 24px; }
.search-bar .el-input { flex: 1; }
.answer-box { background: #f9fafb; padding: 16px; border-radius: 8px; margin-bottom: 16px; }
.answer-content { line-height: 1.8; }
.snippet { color: #606266; font-size: 13px; line-height: 1.6; }
</style>
