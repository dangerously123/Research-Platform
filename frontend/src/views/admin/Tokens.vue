<template>
  <div>
    <h3>Token 用量监控</h3>
    <el-row :gutter="16" style="margin-bottom:24px">
      <el-col :span="6">
        <el-statistic title="本月总 Token" :value="dashboard.current_month?.total_input_tokens + dashboard.current_month?.total_output_tokens || 0" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="本月费用 (元)" :value="dashboard.current_month?.total_cost?.toFixed(2) || '0.00'" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="调用次数" :value="dashboard.current_month?.total_calls || 0" />
      </el-col>
    </el-row>

    <h4>配额管理</h4>
    <el-table :data="dashboard.quotas" border stripe>
      <el-table-column prop="target_type" label="类型" width="100" />
      <el-table-column prop="target_id" label="ID" width="100" />
      <el-table-column prop="monthly_limit" label="月度上限" />
      <el-table-column prop="current_usage" label="当前用量" />
      <el-table-column label="使用率">
        <template #default="{ row }">
          <el-progress :percentage="Math.round((row.usage_ratio || 0) * 100)" :color="row.usage_ratio > 0.8 ? '#f56c6c' : '#409eff'" />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'

const dashboard = ref<any>({ current_month: {}, quotas: [] })

onMounted(async () => {
  const res = await api.get('/tokens/dashboard')
  dashboard.value = res.data
})
</script>
