<template>
  <div class="roles-page">
    <div class="page-header">
      <h3>Role Management</h3>
      <el-button type="primary" :disabled="loadingList" @click="openCreateDialog">
        Create Role
      </el-button>
    </div>

    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      closable
      @close="errorMsg = ''"
      class="page-alert"
    />

    <el-table :data="roles" border stripe v-loading="loadingList">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="Role Name" min-width="160" />
      <el-table-column prop="description" label="Description" min-width="220" show-overflow-tooltip />
      <el-table-column label="Permissions" width="120">
        <template #default="{ row }">{{ row.permissions?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="Actions" width="190" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :disabled="saving" @click="openEditDialog(row)">Edit</el-button>
          <el-button
            size="small"
            type="danger"
            :loading="deletingIds.has(row.id)"
            :disabled="saving || deletingIds.has(row.id)"
            @click="deleteRole(row.id)"
          >
            Delete
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Role' : 'Create Role'" width="680px" destroy-on-close>
      <el-form label-width="110px" @submit.prevent>
        <el-form-item label="Role Name" required>
          <el-input v-model="form.name" maxlength="64" show-word-limit :disabled="saving" />
        </el-form-item>
        <el-form-item label="Description">
          <el-input v-model="form.description" type="textarea" :rows="2" :disabled="saving" />
        </el-form-item>
        <el-form-item label="Permissions">
          <el-input
            v-model="permissionsText"
            type="textarea"
            :rows="10"
            :disabled="saving"
            placeholder='[{"resource_type":"report","resource_id":"*","access_level":"read","department_scope":null}]'
          />
          <div class="form-tip">Use JSON array. Leave empty for no permissions.</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="saveRole">
          Save
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

type PermissionDefinition = {
  resource_type: string
  resource_id: string
  access_level: string
  department_scope?: number[] | null
}

type RoleRow = {
  id: number
  name: string
  description?: string | null
  permissions?: PermissionDefinition[]
}

const roles = ref<RoleRow[]>([])
const loadingList = ref(false)
const saving = ref(false)
const deletingIds = ref(new Set<number>())
const errorMsg = ref('')
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = ref({ name: '', description: '' })
const permissionsText = ref('[]')

onMounted(loadRoles)

async function loadRoles() {
  if (loadingList.value) return
  loadingList.value = true
  errorMsg.value = ''
  try {
    const res = await api.get('/roles')
    roles.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    errorMsg.value = error.response?.data?.message || 'Failed to load roles'
  } finally {
    loadingList.value = false
  }
}

function openCreateDialog() {
  editingId.value = null
  form.value = { name: '', description: '' }
  permissionsText.value = '[]'
  dialogVisible.value = true
}

function openEditDialog(row: RoleRow) {
  editingId.value = row.id
  form.value = { name: row.name || '', description: row.description || '' }
  permissionsText.value = JSON.stringify(row.permissions || [], null, 2)
  dialogVisible.value = true
}

function parsePermissions(): PermissionDefinition[] {
  const raw = permissionsText.value.trim()
  if (!raw) return []
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) throw new Error('Permissions must be a JSON array')
  for (const item of parsed) {
    if (!item?.resource_type || !item?.resource_id || !item?.access_level) {
      throw new Error('Each permission needs resource_type, resource_id and access_level')
    }
  }
  return parsed
}

async function saveRole() {
  if (saving.value || !form.value.name.trim()) return
  let permissions: PermissionDefinition[]
  try {
    permissions = parsePermissions()
  } catch (error: any) {
    ElMessage.error(error.message || 'Invalid permissions JSON')
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      permissions,
    }
    if (editingId.value) {
      await api.put(`/roles/${editingId.value}`, payload)
      ElMessage.success('Role updated')
    } else {
      await api.post('/roles', payload)
      ElMessage.success('Role created')
    }
    dialogVisible.value = false
    await loadRoles()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to save role')
  } finally {
    saving.value = false
  }
}

async function deleteRole(id: number) {
  if (deletingIds.value.has(id)) return
  try {
    await ElMessageBox.confirm('Delete this role?', 'Confirm', { type: 'warning' })
  } catch {
    return
  }

  deletingIds.value = new Set(deletingIds.value).add(id)
  try {
    await api.delete(`/roles/${id}`)
    ElMessage.success('Role deleted')
    await loadRoles()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || 'Failed to delete role')
  } finally {
    const next = new Set(deletingIds.value)
    next.delete(id)
    deletingIds.value = next
  }
}
</script>

<style scoped>
.roles-page { padding: 0 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-alert { margin-bottom: 12px; }
.form-tip { color: #909399; font-size: 12px; line-height: 1.4; margin-top: 6px; }
</style>
