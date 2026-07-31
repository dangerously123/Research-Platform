<template>
  <div class="reports-page">
    <h3>数据报表</h3>
    <el-select v-model="selectedReport" placeholder="选择报表" @change="loadReport"
      :disabled="loadingReport" style="width:300px;margin-bottom:16px">
      <el-option v-for="r in reports" :key="r.id" :label="r.name" :value="r.id" />
    </el-select>

    <!-- 加载状态 -->
    <div v-if="loadingReport" style="text-align:center;padding:40px">
      <el-icon class="is-loading" :size="32"><loading /></el-icon>
      <p>加载中...</p>
    </div>

    <!-- 错误提示 -->
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" closable
      @close="errorMsg = ''" style="margin-bottom:12px" />

    <div v-if="reportData && !loadingReport" class="report-content">
      <div class="chart-area">
        <div ref="chartRef" style="width:100%;height:400px"></div>
      </div>

      <el-table :data="reportData.data" border stripe style="width:100%;margin-top:16px">
        <el-table-column v-for="col in columns" :key="col" :prop="col" :label="col" />
      </el-table>

      <el-pagination
        :current-page="page" :page-size="pageSize" :total="reportData.pagination.total"
        @current-change="changePage" :disabled="loadingReport"
        layout="prev, pager, next" style="margin-top:16px" />

      <el-button type="success" @click="exportReport('excel')"
        :loading="exportingExcel" :disabled="exportingExcel || exportingPdf"
        style="margin-top:12px">
        导出 Excel
      </el-button>
      <el-button type="warning" @click="exportReport('pdf')"
        :loading="exportingPdf" :disabled="exportingExcel || exportingPdf">
        导出 PDF
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'

const reports = ref<any[]>([])
const selectedReport = ref<number | null>(null)
const reportData = ref<any>(null)
const page = ref(1)
const pageSize = ref(50)
const chartRef = ref()
const loadingReport = ref(false)
const exportingExcel = ref(false)
const exportingPdf = ref(false)
const errorMsg = ref('')

const columns = computed(() => {
  if (reportData.value?.data?.length) return Object.keys(reportData.value.data[0])
  return []
})

onMounted(async () => {
  try {
    const res = await api.get('/reports')
    reports.value = res.data.reports
  } catch {
    errorMsg.value = '加载报表列表失败'
  }
})

async function loadReport() {
  if (!selectedReport.value || loadingReport.value) return
  loadingReport.value = true
  errorMsg.value = ''
  try {
    const res = await api.post(`/reports/${selectedReport.value}/generate`, {
      chart_type: 'table',
      page: page.value,
      page_size: pageSize.value,
    })
    reportData.value = res.data
  } catch {
    errorMsg.value = '报表生成失败'
  } finally {
    loadingReport.value = false
  }
}

function changePage(p: number) {
  page.value = p
  loadReport()
}

async function exportReport(format: string) {
  if (!selectedReport.value) return
  const loadingRef = format === 'excel' ? exportingExcel : exportingPdf
  if (loadingRef.value) return
  loadingRef.value = true
  try {
    const res = await api.post(`/reports/${selectedReport.value}/export`, { format })
    ElMessage.success(`导出任务已创建，任务ID: ${res.data.task_id}`)
  } catch {
    ElMessage.error('导出失败')
  } finally {
    loadingRef.value = false
  }
}
</script>

<style scoped>
.reports-page { padding: 0 16px; }
</style>
