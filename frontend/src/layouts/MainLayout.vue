<template>
  <el-container class="layout-container">
    <el-aside width="220px" class="aside">
      <div class="logo">数据分析平台</div>
      <el-menu :default-active="route.path" router class="menu">
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Search /></el-icon>
          <span>知识检索</span>
        </el-menu-item>
        <el-menu-item index="/reports">
          <el-icon><DataAnalysis /></el-icon>
          <span>数据报表</span>
        </el-menu-item>
        <el-menu-item index="/memories">
          <el-icon><Collection /></el-icon>
          <span>我的记忆</span>
        </el-menu-item>
        <el-sub-menu index="/admin">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统管理</span>
          </template>
          <el-menu-item index="/admin/roles">角色权限</el-menu-item>
          <el-menu-item index="/admin/prompts">Prompt模板</el-menu-item>
          <el-menu-item index="/admin/tokens">Token监控</el-menu-item>
          <el-menu-item index="/admin/models">模型管理</el-menu-item>
          <el-menu-item index="/admin/audit">审计日志</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span>{{ userStore.user?.username }}</span>
        <el-button text @click="handleLogout">退出</el-button>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ChatDotRound, Search, DataAnalysis, Setting, Collection } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.layout-container { height: 100vh; }
.aside { background: #304156; }
.logo { color: #fff; font-size: 16px; font-weight: bold; padding: 20px; text-align: center; }
.menu { border-right: none; background: #304156; }
.menu .el-menu-item, .menu .el-sub-menu__title { color: #bfcbd9; }
.menu .el-menu-item.is-active { background: #263445; color: #409eff; }
.header { display: flex; align-items: center; justify-content: flex-end; gap: 12px; border-bottom: 1px solid #eee; }
.main { background: #f5f7fa; }
</style>
