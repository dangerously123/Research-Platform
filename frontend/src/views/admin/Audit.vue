<template>
  <div class="audit-page">
    <h3>Audit Logs</h3>
    <el-form :inline="true" class="filter-form" @submit.prevent>
      <el-form-item label="Operation">
        <el-select v-model="filters.operation_type" clearable placeholder="All" :disabled="loading" class="filter-select">
          <el-option label="Login" value="login" />
          <el-option label="Logout" value="logout" />
          <el-option label="Query" value="query" />
          <el-option label="Export" value="export" />
          <el-option label="Permission Change" value="permission_change" />
          <el-option label="Role Change" value="role_change" />
          <el-option label="Config Change" value="config_change" />
        </el-select>
      </el-form-item>
      <el-form-item label="Resource">
        <el-input v-model="filters.resource_type" clearable placeholder="Resource type" :disabled="loading" />
      </el-form-item>
      <el-form-item label="User ID">
        <el-input-number v-model="filters.user_id" :min="1" clearable :disabled="loading" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" :disabled="loading" @click="reloadFirstPage">Search</el-button>
        <el-button :disabled="loading" @click="resetFilters">Reset</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      closable
      class="page-alert"
      @close="errorMsg = ''"
    />

    <el-table :data="logs" border stripe v-loading="loading">
      <el-table-column prop="user_id" label="User ID" width="90" />
      <el-table-column prop="operation_type" label="Operation" width="150" />
      <el-table-column prop="resource_type" label="Resource Type" width="140" />
      <el-table-column prop="resource_id" label="Resource ID" width="140" show-overflow-tooltip />
      <el-table-column prop="ip_address" label="IP" width="140" />
      <el-table-column prop="created_at" label="Time" width="190" show-overflow-tooltip />
      <el-table-column prop="data_scope" label="Data Scope" min-width="220" show-overflow-tooltip />
    </el-table>

    <el-empty v-if="!loading && !logs.length && !errorMsg" description="No audit logs" />
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
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import api from '@/utils/api'

const logs = ref<any[]>([])
const filters = reactive<{ operation_type: string; resource_type: string; user_id: number | null }>({
  operation_type: '',
  resource_type: '',
  user_id: null,
})
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')
let requestId = 0

onMounted(loadLogs)

async function loadLogs() {
  if (loading.value) return
  const currentRequestId = ++requestId
  loading.value = true
  errorMsg.value = ''
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.operation_type) params.operation_type = filters.operation_type
    if (filters.resource_type) params.resource_type = filters.resource_type
    if (filters.user_id) params.user_id = filters.user_id
    const res = await api.get('/audit/logs', { params })
    if (currentRequestId !== requestId) return
    logs.value = res.data.logs || []
    total.value = res.data.total || 0
  } catch (error: any) {
    if (currentRequestId !== requestId) return
    errorMsg.value = error.response?.data?.message || 'Failed to load audit logs'
    logs.value = []
    total.value = 0
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}

function reloadFirstPage() {
  page.value = 1
  loadLogs()
}

function resetFilters() {
  filters.operation_type = ''
  filters.resource_type = ''
  filters.user_id = null
  reloadFirstPage()
}

function changePage(nextPage: number) {
  if (page.value === nextPage) return
  page.value = nextPage
  loadLogs()
}
</script>

<style scoped>
.audit-page { padding: 0 16px; }
.filter-form { margin-bottom: 16px; }
.filter-select { width: 180px; }
.page-alert { margin-bottom: 12px; }
.pagination { margin-top: 16px; }
</style>
