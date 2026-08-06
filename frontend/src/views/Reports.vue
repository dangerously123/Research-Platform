<template>
  <div class="page-shell reports-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">数据报表</h1>
        <div class="page-subtitle">选择报表并生成分页数据，支持 Excel 与 PDF 导出。</div>
      </div>
      <div class="page-toolbar">
        <el-button :loading="loading" :disabled="loading" @click="loadReports">刷新列表</el-button>
        <el-button type="primary" :disabled="loading" @click="loadReport">重新生成</el-button>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">报表数量</div>
        <div class="metric-value">{{ reports.length }}</div>
        <div class="metric-note">当前可访问的报表模板</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">当前页</div>
        <div class="metric-value">{{ page }}</div>
        <div class="metric-note">分页浏览中的页码</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">导出任务</div>
        <div class="metric-value">{{ activeExport?.task_id || '-' }}</div>
        <div class="metric-note">最近一次导出任务编号</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">导出状态</div>
        <div class="metric-value">{{ activeExport?.status || 'idle' }}</div>
        <div class="metric-note">当前导出任务状态</div>
      </div>
    </div>

    <div class="page-panel workspace-panel">
      <div class="toolbar-row">
        <el-select
          v-model="selectedReport"
          placeholder="选择报表"
          :disabled="loadingReport || reportsLoading"
          class="report-selector"
          @change="loadReport"
          filterable
        >
          <el-option v-for="report in reports" :key="report.id" :label="report.name" :value="report.id" />
        </el-select>

        <div class="soft-text">支持表格分页展示与异步导出</div>
      </div>

      <div v-if="loadingReport" class="loading-state">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <p>正在生成报表...</p>
      </div>

      <el-alert
        v-if="activeExport"
        :title="exportTitle"
        :type="activeExport.status === 'failed' ? 'warning' : 'success'"
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
            下载文件
          </el-button>
        </template>
      </el-alert>

      <div v-if="reportData && !loadingReport" class="report-content">
        <el-empty v-if="!reportData.data?.length" description="暂无数据" />
        <template v-else>
          <el-table :data="reportData.data" border stripe class="report-table compact-table">
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
            导出 Excel
          </el-button>
          <el-button
            type="warning"
            :loading="exportingPdf"
            :disabled="exportingExcel || exportingPdf || !reportData"
            @click="exportReport('pdf')"
          >
            导出 PDF
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElNotification } from 'element-plus'
import api from '@/utils/api'

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
const loading = computed(() => reportsLoading.value || loadingReport.value)

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
    ElNotification({
      title: '报表列表加载失败',
      message: '可以稍后再刷新一次，或者检查后端服务是否正常。',
      type: 'warning',
      position: 'top-right',
      duration: 4200,
    })
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
      ElNotification({
        title: '报表生成失败',
        message: '请稍后重试，或切换到其他报表继续查看。',
        type: 'warning',
        position: 'top-right',
        duration: 4200,
      })
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
    ElMessage.success(`已创建导出任务 #${res.data.task_id}`)
    pollExportStatus(res.data.task_id)
  } catch (error: any) {
    ElNotification({
      title: '导出创建失败',
      message: '请重试一次，或稍后再导出该报表。',
      type: 'warning',
      position: 'top-right',
      duration: 4200,
    })
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
.reports-page {
  max-width: 1400px;
  margin: 0 auto;
}

.workspace-panel {
  padding: 20px;
}

.toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.report-selector {
  width: min(420px, 100%);
}

.loading-state {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 180px;
  color: var(--app-text-muted);
}

.report-table {
  width: 100%;
  margin-top: 16px;
}

.pagination {
  margin-top: 16px;
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 14px;
}
</style>
