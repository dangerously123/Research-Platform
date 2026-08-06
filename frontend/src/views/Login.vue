<template>
  <div class="login-page">
    <section class="login-brief">
      <div class="brand-line">
        <div class="brand-mark">DA</div>
        <span>内部数据分析平台</span>
      </div>
      <h1>把知识检索、数据报表与智能问答放进同一个工作台。</h1>
      <p>
        面向企业内部分析场景，统一会话、权限、模型和审计能力，让数据团队用更少切换完成更多判断。
      </p>
      <div class="brief-grid">
        <div class="brief-item">
          <strong>RAG</strong>
          <span>知识检索</span>
        </div>
        <div class="brief-item">
          <strong>RBAC</strong>
          <span>权限控制</span>
        </div>
        <div class="brief-item">
          <strong>LLM</strong>
          <span>模型网关</span>
        </div>
      </div>
    </section>

    <section class="login-panel">
      <div class="panel-header">
        <h2>欢迎回来</h2>
        <p>登录以继续访问分析工作台</p>
      </div>

      <el-form :model="form" :rules="rules" ref="formRef" class="login-form" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
            size="large"
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" size="large" class="login-button">
          登录
        </el-button>
      </el-form>

      <div class="login-footer">
        <span>默认管理员</span>
        <strong>admin / admin123</strong>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref()
const loading = ref(false)
const errorMsg = ref('')

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  errorMsg.value = ''
  try {
    await userStore.login(form.username, form.password)
    router.push('/')
  } catch (err: any) {
    errorMsg.value = err.response?.data?.message || '登录失败'
    ElNotification({
      title: '登录未通过',
      message: '账号或密码不正确，请再试一次。',
      type: 'warning',
      position: 'top-right',
      duration: 4200,
    })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(380px, 480px);
  gap: 48px;
  align-items: center;
  padding: 56px;
}

.login-brief {
  max-width: 760px;
}

.brand-line {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 700;
  color: var(--app-text-strong);
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: linear-gradient(135deg, #246bfb 0%, #1fbf75 100%);
  color: #fff;
  font-weight: 800;
  box-shadow: 0 14px 30px rgba(36, 107, 251, 0.26);
}

.login-brief h1 {
  margin: 42px 0 18px;
  max-width: 720px;
  font-size: 46px;
  line-height: 1.18;
  font-weight: 800;
  color: var(--app-text-strong);
}

.login-brief p {
  margin: 0;
  max-width: 620px;
  color: var(--app-text-muted);
  font-size: 16px;
  line-height: 1.9;
}

.brief-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 40px;
  max-width: 560px;
}

.brief-item {
  padding: 18px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: var(--app-shadow-soft);
}

.brief-item strong {
  display: block;
  color: var(--app-primary);
  font-size: 18px;
}

.brief-item span {
  display: block;
  margin-top: 8px;
  color: var(--app-text-muted);
  font-size: 13px;
}

.login-panel {
  padding: 36px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 20px;
  background: rgba(15, 23, 42, 0.72);
  box-shadow: var(--app-shadow);
  backdrop-filter: blur(16px);
}

.panel-header {
  margin-bottom: 28px;
}

.panel-header h2 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: 28px;
  font-weight: 800;
}

.panel-header p {
  margin: 8px 0 0;
  color: var(--app-text-muted);
}

.login-form :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 12px;
}

.login-button {
  width: 100%;
  min-height: 46px;
  border-radius: 12px;
  font-weight: 700;
}

.login-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 13px;
}

.login-footer strong {
  color: var(--app-text-strong);
}

@media (max-width: 980px) {
  .login-page {
    grid-template-columns: 1fr;
    padding: 28px;
  }

  .login-brief h1 {
    font-size: 34px;
  }
}

@media (max-width: 640px) {
  .brief-grid {
    grid-template-columns: 1fr;
  }
}
</style>
