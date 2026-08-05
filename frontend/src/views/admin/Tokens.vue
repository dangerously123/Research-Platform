<template>
  <div class="tokens-page">
    <div class="page-header">
      <h3>Token Usage Monitor</h3>
      <div>
        <el-button :loading="loading" :disabled="loading" @click="loadDashboard">Refresh</el-button>
        <el-button type="primary" :disabled="loading" @click="openQuotaDialog">Set Quota</el-button>
      </div>
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

    <el-row :gutter="16" class="stats-row" v-loading="loading">
      <el-col :span="6">
        <el-statistic title="Monthly Tokens" :value="monthlyTokens" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="Monthly Cost" :value="monthlyCost" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="Calls" :value="dashboard.current_month?.total_calls || 0" />
      </el-col>
    </el-row>

    <h4>Quotas</h4>
    <el-table :data="dashboard.quotas" border stripe v-loading="loading">
      <el-table-column prop="target_type" label="Type" width="120" />
      <el-table-column prop="target_id" label="Target ID" width="120" />
      <el-table-column prop="monthly_limit" label="Monthly Limit" min-width="140" />
      <el-table-column prop="current_usage" label="Current Usage" min-width="140" />
      <el-table-column label="Usage" min-width="220">
        <template #default="{ row }">
          <el-progress :percentage="usagePercent(row)" :color="usageColor(row)" />
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !dashboard.quotas.length && !errorMsg" description="No quotas configured" />

    <el-dialog v-model="quotaDialogVisible" title="Set Token Quota" width="560px" destroy-on-close>
      <el-form label-width="150px" @submit.prevent>
        <el-form-item label="Target Type" required>
          <el-select v-model="quotaForm.target_type" :disabled="savingQuota" class="full-width">
            <el-option label="User" value="user" />
            <el-option label="Department" value="department" />
          </el-select>
        </el-form-item>
        <el-form-item label="Target ID" required>
          <el-input-number v-model="quotaForm.target_id" :min="1" :disabled="savingQuota" />
        </el-form-item>
        <el-form-item label="Monthly Token Limit" required>
          <el-input-number v-model="quotaForm.monthly_token_limit" :min="1" :disabled="savingQuota" />
        </el-form-item>
        <el-form-item label="Monthly Cost Limit">
          <el-input-number v-model="quotaForm.monthly_cost_limit" :min="0" :precision="2" :step="10" :disabled="savingQuota" />
        </el-form-item>
        <el-form-item label="Alert Threshold">
          <el-input-number v-model="quotaForm.alert_threshold" :min="0.1" :max="1" :step="0.05" :disabled="savingQuota" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="savingQuota" @click="quotaDialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="savingQuota" @click="saveQuota">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'

const dashboard = ref<any>({ current_month: {}, quotas: [] })
const loading = ref(false)
const savingQuota = ref(false)
const errorMsg = ref('')
const quotaDialogVisible = ref(false)
const quotaForm = ref({
  target_type: 'user',
  target_id: 1,
  monthly_token_limit: 100000,
  monthly_cost_limit: null as number | null,
  alert_threshold: 0.8,
})

const monthlyTokens = computed(() => {
  const current = dashboard.value.current_month || {}
  return (current.total_input_tokens || 0) + (current.total_output_tokens || 0)
})

const monthlyCost = computed(() => Number(dashboard.value.current_month?.total_cost || 0).toFixed(2))

onMounted(loadDashboard)

async function loadDashboard() {
  if (loading.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await api.get('/tokens/dashboard')
    dashboard.value = { current_month: res.data.current_month || {}, quotas: res.data.quotas || [] }
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to load token dashboard'
  } finally {
    loading.value = false
  }
}

function usagePercent(row: any) {
  return Math.min(100, Math.round((row.usage_ratio || 0) * 100))
}

function usageColor(row: any) {
  if ((row.usage_ratio || 0) >= 1) return '#f56c6c'
  if ((row.usage_ratio || 0) >= 0.8) return '#e6a23c'
  return '#409eff'
}

function openQuotaDialog() {
  quotaForm.value = {
    target_type: 'user',
    target_id: 1,
    monthly_token_limit: 100000,
    monthly_cost_limit: null,
    alert_threshold: 0.8,
  }
  quotaDialogVisible.value = true
}

async function saveQuota() {
  if (savingQuota.value) return
  savingQuota.value = true
  try {
    await api.post('/tokens/quotas', quotaForm.value)
    ElMessage.success('Quota saved')
    quotaDialogVisible.value = false
    await loadDashboard()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to save quota')
  } finally {
    savingQuota.value = false
  }
}
</script>

<style scoped>
.tokens-page { padding: 0 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-alert { margin-bottom: 12px; }
.stats-row { margin-bottom: 24px; }
.full-width { width: 100%; }
</style>
