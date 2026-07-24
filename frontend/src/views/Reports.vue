<template>
  <div class="reports-page">
    <h3>数据报表</h3>
    <el-select v-model="selectedReport" placeholder="选择报表" @change="loadReport" style="width:300px;margin-bottom:16px">
      <el-option v-for="r in reports" :key="r.id" :label="r.name" :value="r.id" />
    </el-select>

    <div v-if="reportData" class="report-content">
      <div class="chart-area">
        <!-- ECharts 图表占位 -->
        <div ref="chartRef" style="width:100%;height:400px"></div>
      </div>

      <el-table :data="reportData.data" border stripe style="width:100%;margin-top:16px">
        <el-table-column v-for="col in columns" :key="col" :prop="col" :label="col" />
      </el-table>

      <el-pagination
        :current-page="page" :page-size="pageSize" :total="reportData.pagination.total"
        @current-change="changePage" layout="prev, pager, next" style="margin-top:16px" />

      <el-button type="success" @click="exportReport('excel')" style="margin-top:12px">导出 Excel</el-button>
      <el-button type="warning" @click="exportReport('pdf')">导出 PDF</el-button>
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

const columns = computed(() => {
  if (reportData.value?.data?.length) return Object.keys(reportData.value.data[0])
  return []
})

onMounted(async () => {
  const res = await api.get('/reports')
  reports.value = res.data.reports
})

async function loadReport() {
  if (!selectedReport.value) return
  const res = await api.post(`/reports/${selectedReport.value}/generate`, {
    chart_type: 'table',
    page: page.value,
    page_size: pageSize.value,
  })
  reportData.value = res.data
}

function changePage(p: number) {
  page.value = p
  loadReport()
}

async function exportReport(format: string) {
  if (!selectedReport.value) return
  const res = await api.post(`/reports/${selectedReport.value}/export`, { format })
  ElMessage.success(`导出任务已创建，任务ID: ${res.data.task_id}`)
}
</script>

<style scoped>
.reports-page { padding: 0 16px; }
</style>
