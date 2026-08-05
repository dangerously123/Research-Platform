<template>
  <div class="prompts-page">
    <div class="page-header">
      <h3>Prompt Template Management</h3>
      <el-button type="primary" :disabled="loadingList" @click="openCreateDialog">Create Template</el-button>
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

    <el-table :data="templates" border stripe v-loading="loadingList">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="Name" min-width="160" show-overflow-tooltip />
      <el-table-column prop="category" label="Category" width="130" />
      <el-table-column prop="version" label="Version" width="90" />
      <el-table-column label="Status" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? 'Active' : 'Inactive' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Default" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" type="warning">Default</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="Actions" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :disabled="saving" @click="openEditDialog(row)">Edit</el-button>
          <el-button size="small" :disabled="previewingId === row.id" :loading="previewingId === row.id" @click="previewTemplate(row)">
            Preview
          </el-button>
          <el-button size="small" :disabled="loadingVersionsId === row.id" :loading="loadingVersionsId === row.id" @click="viewVersions(row)">
            History
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editorVisible" :title="editingId ? 'Edit Template' : 'Create Template'" width="760px" destroy-on-close>
      <el-form label-width="130px" @submit.prevent>
        <el-form-item label="Name" required>
          <el-input v-model="form.name" maxlength="128" show-word-limit :disabled="saving" />
        </el-form-item>
        <el-form-item label="Category" required>
          <el-input v-model="form.category" :disabled="saving || Boolean(editingId)" />
        </el-form-item>
        <el-form-item label="Active" v-if="editingId">
          <el-switch v-model="form.is_active" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Content" required>
          <el-input v-model="form.template_content" type="textarea" :rows="12" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Variables">
          <el-input
            v-model="variablesText"
            type="textarea"
            :rows="5"
            :disabled="saving"
            placeholder='[{"name":"user_name","description":"User name","required":true}]'
          />
          <div class="form-tip">Use JSON array. Variables should match placeholders in the template.</div>
        </el-form-item>
        <el-form-item label="Change Note" v-if="editingId">
          <el-input v-model="form.change_description" :disabled="saving" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="editorVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="saveTemplate">Save</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="Template Preview" width="760px" destroy-on-close>
      <el-form label-width="150px" @submit.prevent>
        <el-form-item v-for="variable in previewVariables" :key="variable.name" :label="variable.name">
          <el-input v-model="previewValues[variable.name]" :placeholder="variable.description" />
        </el-form-item>
        <el-empty v-if="!previewVariables.length" description="No variables required" />
      </el-form>
      <el-divider />
      <el-button type="primary" :loading="previewingId === previewTemplateId" @click="runPreview">Render Preview</el-button>
      <div v-if="previewResult" class="preview-result">
        <div class="preview-meta">Estimated tokens: {{ previewResult.token_count }}</div>
        <pre>{{ previewResult.rendered_content }}</pre>
      </div>
    </el-dialog>

    <el-dialog v-model="versionsVisible" title="Version History" width="860px" destroy-on-close>
      <el-table :data="versions" border stripe v-loading="loadingVersionsId !== null">
        <el-table-column prop="version" label="Version" width="90" />
        <el-table-column prop="changed_by" label="Changed By" width="110" />
        <el-table-column prop="change_description" label="Note" min-width="180" show-overflow-tooltip />
        <el-table-column prop="created_at" label="Created At" min-width="170" show-overflow-tooltip />
        <el-table-column label="Actions" width="120">
          <template #default="{ row }">
            <el-button size="small" type="warning" :loading="rollbackingVersion === row.version" @click="rollbackVersion(row.version)">
              Rollback
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!versions.length && loadingVersionsId === null" description="No versions" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

type VariableDefinition = {
  name: string
  description: string
  required?: boolean
}

type PromptTemplate = {
  id: number
  name: string
  category: string
  template_content: string
  variables?: VariableDefinition[] | null
  version: number
  is_active: boolean
  is_default: boolean
}

type TemplateVersion = {
  id: number
  version: number
  template_content: string
  changed_by: number
  change_description?: string | null
  created_at: string
}

const templates = ref<PromptTemplate[]>([])
const versions = ref<TemplateVersion[]>([])
const loadingList = ref(false)
const saving = ref(false)
const previewingId = ref<number | null>(null)
const loadingVersionsId = ref<number | null>(null)
const rollbackingVersion = ref<number | null>(null)
const errorMsg = ref('')
const editorVisible = ref(false)
const previewVisible = ref(false)
const versionsVisible = ref(false)
const editingId = ref<number | null>(null)
const versionTemplateId = ref<number | null>(null)
const previewTemplateId = ref<number | null>(null)
const previewVariables = ref<VariableDefinition[]>([])
const previewValues = reactive<Record<string, string>>({})
const previewResult = ref<{ rendered_content: string; token_count: number } | null>(null)
const variablesText = ref('[]')
const form = ref({
  name: '',
  category: 'general',
  template_content: '',
  is_active: true,
  change_description: '',
})

const canSave = computed(() => Boolean(
  form.value.name.trim() &&
  form.value.category.trim() &&
  form.value.template_content.trim()
))

onMounted(loadTemplates)

async function loadTemplates() {
  if (loadingList.value) return
  loadingList.value = true
  errorMsg.value = ''
  try {
    const res = await api.get('/prompts/templates')
    templates.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to load prompt templates'
  } finally {
    loadingList.value = false
  }
}

function openCreateDialog() {
  editingId.value = null
  form.value = { name: '', category: 'general', template_content: '', is_active: true, change_description: '' }
  variablesText.value = '[]'
  editorVisible.value = true
}

function openEditDialog(template: PromptTemplate) {
  editingId.value = template.id
  form.value = {
    name: template.name || '',
    category: template.category || 'general',
    template_content: template.template_content || '',
    is_active: template.is_active,
    change_description: '',
  }
  variablesText.value = JSON.stringify(template.variables || [], null, 2)
  editorVisible.value = true
}

function parseVariables(): VariableDefinition[] {
  const raw = variablesText.value.trim()
  if (!raw) return []
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) throw new Error('Variables must be a JSON array')
  for (const item of parsed) {
    if (!item?.name || !item?.description) throw new Error('Each variable needs name and description')
  }
  return parsed
}

async function saveTemplate() {
  if (saving.value || !canSave.value) return
  let variables: VariableDefinition[]
  try {
    variables = parseVariables()
  } catch (error: any) {
    ElMessage.error(error.message || 'Invalid variables JSON')
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      await api.put(`/prompts/templates/${editingId.value}`, {
        name: form.value.name.trim(),
        template_content: form.value.template_content,
        variables,
        is_active: form.value.is_active,
        change_description: form.value.change_description,
      })
      ElMessage.success('Template updated')
    } else {
      await api.post('/prompts/templates', {
        name: form.value.name.trim(),
        category: form.value.category.trim(),
        template_content: form.value.template_content,
        variables,
      })
      ElMessage.success('Template created')
    }
    editorVisible.value = false
    await loadTemplates()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to save template')
  } finally {
    saving.value = false
  }
}

function previewTemplate(template: PromptTemplate) {
  previewTemplateId.value = template.id
  previewVariables.value = template.variables || []
  previewResult.value = null
  for (const key of Object.keys(previewValues)) delete previewValues[key]
  for (const variable of previewVariables.value) previewValues[variable.name] = ''
  previewVisible.value = true
}

async function runPreview() {
  if (!previewTemplateId.value || previewingId.value) return
  previewingId.value = previewTemplateId.value
  try {
    const res = await api.post(`/prompts/templates/${previewTemplateId.value}/preview`, { variables: previewValues })
    previewResult.value = res.data
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to render preview')
  } finally {
    previewingId.value = null
  }
}

async function viewVersions(template: PromptTemplate) {
  versionTemplateId.value = template.id
  versionsVisible.value = true
  versions.value = []
  loadingVersionsId.value = template.id
  try {
    const res = await api.get(`/prompts/templates/${template.id}/versions`)
    versions.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to load versions')
  } finally {
    loadingVersionsId.value = null
  }
}

async function rollbackVersion(version: number) {
  if (!versionTemplateId.value || rollbackingVersion.value) return
  try {
    await ElMessageBox.confirm(`Rollback to version ${version}?`, 'Confirm', { type: 'warning' })
  } catch {
    return
  }

  rollbackingVersion.value = version
  try {
    await api.post(`/prompts/templates/${versionTemplateId.value}/rollback/${version}`)
    ElMessage.success('Template rolled back')
    versionsVisible.value = false
    await loadTemplates()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to rollback template')
  } finally {
    rollbackingVersion.value = null
  }
}
</script>

<style scoped>
.prompts-page { padding: 0 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-alert { margin-bottom: 12px; }
.form-tip { color: #909399; font-size: 12px; line-height: 1.4; margin-top: 6px; }
.preview-result { margin-top: 16px; }
.preview-meta { color: #606266; margin-bottom: 8px; }
.preview-result pre { white-space: pre-wrap; word-break: break-word; background: #f5f7fa; padding: 12px; border-radius: 4px; }
</style>
