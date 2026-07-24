<template>
  <div>
    <h3>角色权限管理</h3>
    <el-button type="primary" @click="showCreate = true">创建角色</el-button>
    <el-table :data="roles" border stripe style="margin-top:16px">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="角色名" />
      <el-table-column prop="description" label="描述" />
      <el-table-column label="权限数" width="100">
        <template #default="{ row }">{{ row.permissions?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button size="small" @click="editRole(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="deleteRole(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const roles = ref<any[]>([])
const showCreate = ref(false)

onMounted(loadRoles)

async function loadRoles() {
  const res = await api.get('/roles')
  roles.value = res.data
}

function editRole(_row: any) { /* 打开编辑弹窗 */ }

async function deleteRole(id: number) {
  await ElMessageBox.confirm('确定删除该角色？')
  try {
    await api.delete(`/roles/${id}`)
    ElMessage.success('删除成功')
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '删除失败')
  }
}
</script>
