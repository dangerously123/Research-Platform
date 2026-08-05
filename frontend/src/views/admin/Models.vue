<template>
  <div class="models-page">
    <div class="page-header">
      <h3>LLM Model Management</h3>
      <el-button type="primary" :disabled="loadingList" @click="openAddDialog">Add Model</el-button>
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

    <el-table :data="models" border stripe v-loading="loadingList">
      <el-table-column prop="model_id" label="Model ID" min-width="160" show-overflow-tooltip />
      <el-table-column prop="model_name" label="Name" min-width="160" show-overflow-tooltip />
      <el-table-column prop="provider" label="Provider" width="110" />
      <el-table-column label="Status" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="Priority" width="90" />
      <el-table-column prop="avg_latency_ms" label="Latency(ms)" width="120" />
      <el-table-column prop="last_health_check" label="Last Check" min-width="170" show-overflow-tooltip />
      <el-table-column label="Actions" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="checkingIds.has(row.model_id)"
            :disabled="checkingIds.has(row.model_id) || removingIds.has(row.model_id)"
            @click="checkHealth(row.model_id)"
          >
            Check
          </el-button>
          <el-button
            size="small"
            type="danger"
            :loading="removingIds.has(row.model_id)"
            :disabled="checkingIds.has(row.model_id) || removingIds.has(row.model_id)"
            @click="removeModel(row.model_id)"
          >
            Remove
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="Add Model" width="680px" destroy-on-close>
      <el-form label-width="130px" @submit.prevent>
        <el-form-item label="Model ID" required>
          <el-input v-model="form.model_id" maxlength="64" show-word-limit :disabled="saving" />
        </el-form-item>
        <el-form-item label="Model Name" required>
          <el-input v-model="form.model_name" maxlength="128" show-word-limit :disabled="saving" />
        </el-form-item>
        <el-form-item label="Provider" required>
          <el-select v-model="form.provider" :disabled="saving" class="full-width">
            <el-option label="OpenAI" value="openai" />
            <el-option label="Qwen" value="qwen" />
            <el-option label="Wenxin" value="wenxin" />
            <el-option label="Ollama" value="ollama" />
            <el-option label="vLLM" value="vllm" />
          </el-select>
        </el-form-item>
        <el-form-item label="Endpoint URL" required>
          <el-input v-model="form.endpoint_url" :disabled="saving" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password :disabled="saving" />
        </el-form-item>
        <el-form-item label="Priority">
          <el-input-number v-model="form.priority" :min="0" :max="999" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Context Window">
          <el-input-number v-model="form.context_window" :min="1" :max="1000000" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number v-model="form.max_tokens" :min="1" :max="1000000" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Task Types">
          <el-input v-model="taskTypesText" :disabled="saving" placeholder="chat,rag,summary" />
          <div class="form-tip">Comma-separated. Leave empty to support all task types.</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="saveModel">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

type ModelRow = {
  model_id: string
  model_name: string
  provider: string
  status: string
  priority: number
  avg_latency_ms?: number | null
  last_health_check?: string | null
}

const models = ref<ModelRow[]>([])
const loadingList = ref(false)
const saving = ref(false)
const checkingIds = ref(new Set<string>())
const removingIds = ref(new Set<string>())
const errorMsg = ref('')
const dialogVisible = ref(false)
const taskTypesText = ref('')
const form = ref({
  model_id: '',
  model_name: '',
  provider: 'openai',
  endpoint_url: '',
  api_key: '',
  priority: 0,
  context_window: 8192,
  max_tokens: 4096,
  temperature: 0.7,
})

const canSave = computed(() => Boolean(
  form.value.model_id.trim() &&
  form.value.model_name.trim() &&
  form.value.provider &&
  form.value.endpoint_url.trim()
))

onMounted(loadModels)

async function loadModels() {
  if (loadingList.value) return
  loadingList.value = true
  errorMsg.value = ''
  try {
    const res = await api.get('/llm/models')
    models.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to load models'
  } finally {
    loadingList.value = false
  }
}

function openAddDialog() {
  form.value = {
    model_id: '',
    model_name: '',
    provider: 'openai',
    endpoint_url: '',
    api_key: '',
    priority: 0,
    context_window: 8192,
    max_tokens: 4096,
    temperature: 0.7,
  }
  taskTypesText.value = ''
  dialogVisible.value = true
}

function parseTaskTypes(): string[] | null {
  const values = taskTypesText.value.split(',').map((item) => item.trim()).filter(Boolean)
  return values.length ? values : null
}

async function saveModel() {
  if (saving.value || !canSave.value) return
  saving.value = true
  try {
    await api.post('/llm/models', {
      ...form.value,
      model_id: form.value.model_id.trim(),
      model_name: form.value.model_name.trim(),
      endpoint_url: form.value.endpoint_url.trim(),
      api_key: form.value.api_key.trim() || null,
      task_types: parseTaskTypes(),
    })
    ElMessage.success('Model added')
    dialogVisible.value = false
    await loadModels()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to add model')
  } finally {
    saving.value = false
  }
}

async function checkHealth(modelId: string) {
  if (checkingIds.value.has(modelId)) return
  checkingIds.value = new Set(checkingIds.value).add(modelId)
  try {
    const res = await api.post(`/llm/models/${modelId}/health-check`)
    ElMessage.info(`Status: ${res.data.status}, latency: ${res.data.latency_ms}ms`)
    await loadModels()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Health check failed')
  } finally {
    const next = new Set(checkingIds.value)
    next.delete(modelId)
    checkingIds.value = next
  }
}

async function removeModel(modelId: string) {
  if (removingIds.value.has(modelId)) return
  try {
    await ElMessageBox.confirm(`Remove model ${modelId}?`, 'Confirm', { type: 'warning' })
  } catch {
    return
  }

  removingIds.value = new Set(removingIds.value).add(modelId)
  try {
    await api.delete(`/llm/models/${modelId}`)
    ElMessage.success('Model removed')
    await loadModels()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to remove model')
  } finally {
    const next = new Set(removingIds.value)
    next.delete(modelId)
    removingIds.value = next
  }
}
</script>

<style scoped>
.models-page { padding: 0 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-alert { margin-bottom: 12px; }
.full-width { width: 100%; }
.form-tip { color: #909399; font-size: 12px; line-height: 1.4; margin-top: 6px; }
</style>
