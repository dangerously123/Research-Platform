<template>
  <div>
    <h3>LLM 模型管理</h3>
    <el-button type="primary" @click="showAdd = true">添加模型</el-button>
    <el-table :data="models" border stripe style="margin-top:16px">
      <el-table-column prop="model_id" label="模型ID" />
      <el-table-column prop="model_name" label="名称" />
      <el-table-column prop="provider" label="提供商" width="100" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" />
      <el-table-column prop="avg_latency_ms" label="延迟(ms)" width="100" />
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="checkHealth(row.model_id)">检查</el-button>
          <el-button size="small" type="danger" @click="removeModel(row.model_id)">移除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'

const models = ref<any[]>([])
const showAdd = ref(false)

onMounted(loadModels)

async function loadModels() {
  const res = await api.get('/llm/models')
  models.value = res.data
}

async function checkHealth(modelId: string) {
  const res = await api.post(`/llm/models/${modelId}/health-check`)
  ElMessage.info(`状态: ${res.data.status}, 延迟: ${res.data.latency_ms}ms`)
  loadModels()
}

async function removeModel(modelId: string) {
  await api.delete(`/llm/models/${modelId}`)
  ElMessage.success('已移除')
  loadModels()
}
</script>
