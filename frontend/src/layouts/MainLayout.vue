<template>
  <el-container class="layout-shell">
    <el-aside class="sidebar" width="284px">
      <div class="brand-block">
        <div class="brand-mark">DA</div>
        <div class="brand-copy">
          <div class="brand-name">Data Analysis</div>
          <div class="brand-desc">Intelligence Workspace</div>
        </div>
      </div>

      <el-button class="create-btn" type="primary" :icon="Plus" @click="goChat">
        新建会话
      </el-button>

      <div class="side-group">
        <div class="side-group-title">核心工作</div>
        <el-menu :default-active="route.path" router class="side-menu" :collapse-transition="false">
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
        </el-menu>
      </div>

      <div class="side-group">
        <div class="side-group-title">个人管理</div>
        <el-menu :default-active="route.path" router class="side-menu" :collapse-transition="false">
          <el-menu-item index="/memories">
            <el-icon><Collection /></el-icon>
            <span>我的记忆</span>
          </el-menu-item>
        </el-menu>
      </div>

      <div class="side-group">
        <div class="side-group-title">系统管理</div>
        <el-menu :default-active="route.path" router class="side-menu" :collapse-transition="false">
          <el-sub-menu index="/admin">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>系统管理</span>
            </template>
            <el-menu-item index="/admin/roles">角色权限</el-menu-item>
            <el-menu-item index="/admin/prompts">Prompt 模板</el-menu-item>
            <el-menu-item index="/admin/tokens">Token 监控</el-menu-item>
            <el-menu-item index="/admin/models">模型管理</el-menu-item>
            <el-menu-item index="/admin/audit">审计日志</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </div>
    </el-aside>

    <el-container class="main-shell">
      <el-header class="topbar">
        <div class="topbar-left">
          <div class="logo-pulse">
            <div class="logo-orb"></div>
            <div class="logo-lines">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
          <div>
            <div class="topbar-title">{{ pageTitle }}</div>
            <div class="topbar-subtitle">深蓝玻璃态企业数据平台</div>
          </div>
        </div>

        <div class="topbar-center">
          <el-input v-model="globalSearch" size="large" placeholder="全局搜索会话、报告、模型..." clearable>
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <div class="topbar-actions">
          <el-tag effect="light" class="status-pill" type="success">Stable</el-tag>
          <el-dropdown @command="handleCommand">
            <div class="user-chip">
              <el-avatar :size="32">{{ userInitial }}</el-avatar>
              <div class="user-meta">
                <span class="username">{{ userStore.user?.username || 'Guest' }}</span>
                <span class="role-label">System User</span>
              </div>
              <el-icon class="dropdown-icon"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人设置</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="content-shell">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  ArrowDown,
  ChatDotRound,
  Collection,
  DataAnalysis,
  Plus,
  Search,
  Setting,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const globalSearch = ref('')

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/chat': '智能问答',
    '/knowledge': '知识检索',
    '/reports': '数据报表',
    '/memories': '我的记忆',
    '/admin/roles': '角色权限',
    '/admin/prompts': 'Prompt 模板',
    '/admin/tokens': 'Token 监控',
    '/admin/models': '模型管理',
    '/admin/audit': '审计日志',
  }
  return map[route.path] || '数据分析平台'
})

const userInitial = computed(() => (userStore.user?.username?.[0] || 'U').toUpperCase())

function goChat() {
  router.push('/chat')
}

function handleCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
    return
  }
  ElMessage.info('个人设置功能稍后开放')
}
</script>

<style scoped>
.layout-shell {
  min-height: 100vh;
  background: transparent;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 16px;
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.96) 0%, rgba(15, 23, 42, 0.88) 100%);
  box-shadow: 10px 0 28px rgba(2, 6, 23, 0.32);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 12px 0;
  color: #fff;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 16px;
  background: linear-gradient(135deg, #14b8a6 0%, #2563eb 100%);
  font-size: 16px;
  font-weight: 800;
  box-shadow: 0 14px 32px rgba(20, 184, 166, 0.24);
}

.brand-name {
  font-size: 18px;
  font-weight: 800;
}

.brand-desc {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(226, 232, 240, 0.56);
}

.create-btn {
  width: 100%;
  min-height: 48px;
  font-weight: 700;
  box-shadow: 0 16px 30px rgba(20, 184, 166, 0.22);
}

.side-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.side-group-title {
  padding: 10px 12px 0;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: rgba(148, 163, 184, 0.84);
  text-transform: uppercase;
}

.side-menu {
  border: 0;
  background: transparent;
}

.side-menu :deep(.el-menu-item),
.side-menu :deep(.el-sub-menu__title) {
  height: 48px;
  margin-bottom: 8px;
  border-radius: 14px;
  color: rgba(226, 232, 240, 0.76);
  background: transparent;
}

.side-menu :deep(.el-menu-item:hover),
.side-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.05);
}

.side-menu :deep(.el-menu-item.is-active) {
  color: #ffffff;
  background: linear-gradient(135deg, rgba(20, 184, 166, 0.22), rgba(37, 99, 235, 0.34));
  box-shadow: var(--app-glow);
}

.main-shell {
  min-width: 0;
}

.topbar {
  display: grid;
  grid-template-columns: auto minmax(320px, 1fr) auto;
  gap: 18px;
  align-items: center;
  min-height: 86px;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(15, 23, 42, 0.66);
  backdrop-filter: blur(18px);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-pulse {
  position: relative;
  width: 34px;
  height: 34px;
}

.logo-orb {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: radial-gradient(circle at 35% 35%, rgba(255, 255, 255, 0.8), rgba(20, 184, 166, 0.95) 48%, rgba(37, 99, 235, 0.95) 100%);
  box-shadow: 0 0 0 0 rgba(20, 184, 166, 0.36);
  animation: orbPulse 2.8s ease-in-out infinite;
}

.logo-lines {
  position: absolute;
  inset: 7px;
  display: grid;
  gap: 3px;
}

.logo-lines span {
  display: block;
  border-radius: 999px;
  height: 3px;
  background: rgba(15, 23, 42, 0.72);
}

.topbar-title {
  font-size: 20px;
  font-weight: 800;
  color: var(--app-text-strong);
}

.topbar-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.topbar-center {
  justify-self: center;
  width: min(640px, 100%);
}

.topbar-center :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 999px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-pill {
  border-radius: 999px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px 6px 6px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.68);
  cursor: pointer;
}

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
}

.username {
  font-size: 13px;
  font-weight: 700;
  color: var(--app-text-strong);
}

.role-label {
  margin-top: 3px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.dropdown-icon {
  color: var(--app-text-muted);
}

.content-shell {
  padding: 0;
}

.content-shell :deep(> div) {
  min-height: calc(100vh - 86px);
}

@keyframes orbPulse {
  0%,
  100% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(20, 184, 166, 0.36);
  }
  50% {
    transform: scale(1.06);
    box-shadow: 0 0 0 10px rgba(20, 184, 166, 0);
  }
}
</style>
