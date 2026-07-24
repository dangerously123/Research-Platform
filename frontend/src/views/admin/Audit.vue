<template>
  <div>
    <h3>审计日志</h3>
    <el-form :inline="true" style="margin-bottom:16px">
      <el-form-item label="操作类型">
        <el-select v-model="filters.operation_type" clearable placeholder="全部">
          <el-option label="登录" value="login" />
          <el-option label="查询" value="query" />
          <el-option label="导出" value="export" />
          <el-option label="权限变更" value="permission_change" />
          <el-option label="配置变更" value="config_change" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="loadLogs">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table :data="logs" border stripe>
      <el-table-column prop="user_id" label="用户ID" width="80" />
      <el-table-column prop="operation_type" label="操作类型" width="120" />
      <el-table-column prop="resource_type" label="资源类型" width="120" />
      <el-table-column prop="ip_address" label="IP" width="130" />
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="data_scope" label="数据范围" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import api from '@/utils/api'

const logs = ref<any[]>([])
const filters = reactive({ operation_type: '' })

onMounted(loadLogs)

async function loadLogs() {
  const params: any = {}
  if (filters.operation_type) params.operation_type = filters.operation_type
  const res = await api.get('/audit/logs', { params })
  logs.value = res.data.logs || res.data || []
}
</script>
