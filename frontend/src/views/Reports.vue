<template>
  <div class="reports-page">
    <h3>Reports</h3>
    <el-select
      v-model="selectedReport"
      placeholder="Select report"
      :disabled="loadingReport || reportsLoading"
      class="report-selector"
      @change="loadReport"
    >
      <el-option v-for="report in reports" :key="report.id" :label="report.name" :value="report.id" />
    </el-select>

    <div v-if="loadingReport" class="loading-state">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>Loading...</p>
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

    <el-alert
      v-if="activeExport"
      :title="exportTitle"
      :type="activeExport.status === 'failed' ? 'error' : 'info'"
      show-icon
      class="page-alert"
      :closable="activeExport.status !== 'processing' && activeExport.status !== 'pending'"
      @close="activeExport = null"
    >
      <template #default>
        <el-button
          v-if="activeExport.status === 'completed' && activeExport.download_url"
          type="primary"
          size="small"
          @click="downloadExport(activeExport.download_url)"
        >
          Download
        </el-button>
      </template>
    </el-alert>

    <div v-if="reportData && !loadingReport" class="report-content">
      <el-empty v-if="!reportData.data?.length" description="No data" />
      <template v-else>
        <el-table :data="reportData.data" border stripe class="report-table">
          <el-table-column v-for="col in columns" :key="col" :prop="col" :label="col" show-overflow-tooltip />
        </el-table>

        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :total="reportData.pagination?.total || 0"
          :disabled="loadingReport"
          layout="prev, pager, next"
          class="pagination"
          @current-change="changePage"
        />
      </template>

      <div class="actions">
        <el-button
          type="success"
          :loading="exportingExcel"
          :disabled="exportingExcel || exportingPdf || !reportData"
          @click="exportReport('excel')"
        >
          Export Excel
        </el-button>
        <el-button
          type="warning"
          :loading="exportingPdf"
          :disabled="exportingExcel || exportingPdf || !reportData"
          @click="exportReport('pdf')"
        >
          Export PDF
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'

type ExportStatus = {
  task_id: number
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'not_found'
  download_url?: string | null
  error_message?: string | null
}

const reports = ref<any[]>([])
const selectedReport = ref<number | null>(null)
const reportData = ref<any>(null)
const page = ref(1)
const pageSize = ref(50)
const reportsLoading = ref(false)
const loadingReport = ref(false)
const exportingExcel = ref(false)
const exportingPdf = ref(false)
const errorMsg = ref('')
const activeExport = ref<ExportStatus | null>(null)
let exportPollTimer: ReturnType<typeof window.setTimeout> | null = null
let reportRequestId = 0

const columns = computed(() => {
  if (reportData.value?.data?.length) return Object.keys(reportData.value.data[0])
  return []
})

const exportTitle = computed(() => {
  if (!activeExport.value) return ''
  if (activeExport.value.status === 'completed') return `Export #${activeExport.value.task_id} is ready`
  if (activeExport.value.status === 'failed') return activeExport.value.error_message || 'Export failed'
  if (activeExport.value.status === 'not_found') return 'Export task was not found'
  return `Export #${activeExport.value.task_id} is ${activeExport.value.status}`
})

onMounted(loadReports)
onUnmounted(() => clearExportPoll())

async function loadReports() {
  reportsLoading.value = true
  errorMsg.value = ''
  try {
    const res = await api.get('/reports')
    reports.value = res.data.reports || []
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to load report list'
  } finally {
    reportsLoading.value = false
  }
}

async function loadReport() {
  if (!selectedReport.value || loadingReport.value) return
  const currentRequestId = ++reportRequestId
  loadingReport.value = true
  errorMsg.value = ''
  try {
    const res = await api.post(`/reports/${selectedReport.value}/generate`, {
      chart_type: 'table',
      page: page.value,
      page_size: pageSize.value,
    })
    if (currentRequestId === reportRequestId) reportData.value = res.data
  } catch (error: any) {
    if (currentRequestId === reportRequestId) {
      reportData.value = null
      errorMsg.value = error.response?.data?.message || 'Failed to generate report'
    }
  } finally {
    if (currentRequestId === reportRequestId) loadingReport.value = false
  }
}

function changePage(nextPage: number) {
  if (page.value === nextPage) return
  page.value = nextPage
  loadReport()
}

async function exportReport(format: 'excel' | 'pdf') {
  if (!selectedReport.value) return
  const loadingRef = format === 'excel' ? exportingExcel : exportingPdf
  if (loadingRef.value) return
  loadingRef.value = true
  try {
    const res = await api.post(`/reports/${selectedReport.value}/export`, { format })
    activeExport.value = res.data
    ElMessage.success(`Export task #${res.data.task_id} created`)
    pollExportStatus(res.data.task_id)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to create export task')
  } finally {
    loadingRef.value = false
  }
}

function pollExportStatus(taskId: number) {
  clearExportPoll()
  const poll = async () => {
    try {
      const res = await api.get(`/reports/export/${taskId}`)
      activeExport.value = res.data
      if (res.data.status === 'completed' || res.data.status === 'failed' || res.data.status === 'not_found') return
      exportPollTimer = window.setTimeout(poll, 2000)
    } catch (error: any) {
      activeExport.value = {
        task_id: taskId,
        status: 'failed',
        error_message: error.response?.data?.message || 'Failed to query export status',
      }
    }
  }
  poll()
}

function clearExportPoll() {
  if (exportPollTimer) {
    window.clearTimeout(exportPollTimer)
    exportPollTimer = null
  }
}

function downloadExport(downloadUrl: string) {
  const baseURL = api.defaults.baseURL || ''
  const normalized = downloadUrl.startsWith(baseURL) ? downloadUrl : `${baseURL}${downloadUrl.replace(/^\/api\/v1/, '')}`
  window.open(normalized, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.reports-page { padding: 0 16px; }
.report-selector { width: 300px; margin-bottom: 16px; }
.loading-state { text-align: center; padding: 40px; }
.page-alert { margin-bottom: 12px; }
.report-table { width: 100%; margin-top: 16px; }
.pagination { margin-top: 16px; }
.actions { margin-top: 12px; }
</style>
