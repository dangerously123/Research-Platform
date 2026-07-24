<template>
  <div>
    <h3>Prompt 模板管理</h3>
    <el-button type="primary" @click="showCreate = true">创建模板</el-button>
    <el-table :data="templates" border stripe style="margin-top:16px">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="模板名" />
      <el-table-column prop="category" label="分类" width="120" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="previewTemplate(row.id)">预览</el-button>
          <el-button size="small" @click="viewVersions(row.id)">历史</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'

const templates = ref<any[]>([])
const showCreate = ref(false)

onMounted(async () => {
  const res = await api.get('/prompts/templates')
  templates.value = res.data
})

function previewTemplate(_id: number) { /* 打开预览弹窗 */ }
function viewVersions(_id: number) { /* 打开版本历史弹窗 */ }
</script>
