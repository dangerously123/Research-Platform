<template>
  <div class="chat-workspace">
    <aside class="history-rail">
      <el-button class="rail-create" type="primary" :icon="Plus" @click="createConversation" :loading="creatingConv" :disabled="streaming">
        新建会话
      </el-button>

      <button class="history-toggle" type="button" @click="historyOpen = !historyOpen">
        <span>历史会话</span>
        <span class="soft-text">{{ conversations.length }}</span>
      </button>

      <transition name="soft-slide">
        <div v-show="historyOpen" class="history-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="history-item"
            :class="{ active: currentConvId === conv.id, disabled: streaming }"
            @click="selectConversation(conv.id)"
          >
            <div class="history-title">{{ conv.title || `Conversation #${conv.id}` }}</div>
            <div class="history-meta">会话 ID {{ conv.id }}</div>
          </div>
          <div v-if="!conversations.length" class="history-empty">
            暂无会话记录
          </div>
        </div>
      </transition>
    </aside>

    <main class="chat-stage" :class="{ empty: !messages.length && !streaming }">
      <section class="chat-hero">
        <div class="ai-orb">
          <div class="ai-core">AI</div>
        </div>
        <h1>今天想分析什么？</h1>
        <p>输入问题，平台会结合会话上下文与知识检索给出回答。</p>
      </section>

      <section v-if="messages.length || streaming" class="message-panel glass-panel">
        <div class="messages" ref="messagesRef">
          <div v-for="msg in messages" :key="msg.message_id" class="message" :class="msg.role">
            <div class="message-avatar">{{ msg.role === 'user' ? 'U' : 'AI' }}</div>
            <div class="bubble">
              <div class="message-label">{{ msg.role === 'user' ? 'You' : 'Assistant' }}</div>
              <div class="content" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="msg.sources?.length" class="sources">
                <span class="source-label">Sources</span>
                <el-tag v-for="source in msg.sources" :key="source.doc_id" size="small" type="info" effect="light">
                  {{ source.title }}
                </el-tag>
              </div>
            </div>
          </div>

          <div v-if="streaming" class="message assistant">
            <div class="message-avatar">AI</div>
            <div class="bubble bubble-stream">
              <div class="message-label">Assistant</div>
              <div class="content">{{ streamContent }}<span class="cursor">|</span></div>
            </div>
          </div>
        </div>
      </section>

      <section class="composer glass-panel">
        <el-input
          v-model="inputText"
          placeholder="输入你的问题，Ctrl + Enter 发送"
          :rows="4"
          type="textarea"
          resize="none"
          @keydown.enter.ctrl="sendMessage"
          :disabled="streaming"
        />
        <div class="composer-actions">
          <span class="composer-hint">支持自然语言提问、数据分析和知识检索</span>
          <div class="composer-buttons">
            <el-button v-if="streaming" :icon="CircleClose" plain type="warning" @click="abortStream">
              停止
            </el-button>
            <el-button type="primary" :icon="Promotion" @click="sendMessage" :loading="streaming" :disabled="!inputText.trim() || streaming">
              发送
            </el-button>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { CircleClose, Plus, Promotion } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import api from '@/utils/api'

const conversations = ref<any[]>([])
const currentConvId = ref<number | null>(null)
const messages = ref<any[]>([])
const inputText = ref('')
const streaming = ref(false)
const streamContent = ref('')
const messagesRef = ref<HTMLElement>()
const creatingConv = ref(false)
const historyOpen = ref(true)

let abortController: AbortController | null = null
let streamTimeout: ReturnType<typeof setTimeout> | null = null
let streamingConvId: number | null = null
const STREAM_TIMEOUT_MS = 90_000

onMounted(() => {
  loadConversations()
})

onBeforeUnmount(() => {
  abortStream()
})

function notifyRetry(message: string) {
  ElNotification({
    title: '操作没有完成',
    message: `${message} 稍后重试，或检查后端服务是否正常。`,
    type: 'warning',
    position: 'top-right',
    duration: 4200,
  })
}

async function loadConversations() {
  try {
    conversations.value = []
  } catch {
    conversations.value = []
  }
}

async function createConversation() {
  if (creatingConv.value || streaming.value) return
  creatingConv.value = true
  try {
    const res = await api.post('/llm/conversations', { title: null })
    const conv = res.data
    conversations.value.unshift(conv)
    currentConvId.value = conv.id
    messages.value = []
  } catch {
    notifyRetry('新建会话失败。')
  } finally {
    creatingConv.value = false
  }
}

async function selectConversation(id: number) {
  if (streaming.value) return
  if (currentConvId.value === id) return

  currentConvId.value = id
  try {
    const res = await api.get(`/llm/conversations/${id}/messages`)
    messages.value = res.data.messages || []
  } catch {
    messages.value = []
    notifyRetry('会话历史加载失败。')
  }
}

async function sendMessage() {
  if (!inputText.value.trim() || streaming.value) return

  if (!currentConvId.value) {
    await createConversation()
    if (!currentConvId.value) return
  }

  const content = inputText.value.trim()
  inputText.value = ''
  messages.value.push({ message_id: Date.now(), role: 'user', content, sources: [] })

  streaming.value = true
  streamContent.value = ''
  streamingConvId = currentConvId.value
  abortController = new AbortController()
  let sseBuffer = ''

  const resetTimeout = () => {
    if (streamTimeout) clearTimeout(streamTimeout)
    streamTimeout = setTimeout(() => {
      notifyRetry('响应等待时间较长。')
      abortStream()
    }, STREAM_TIMEOUT_MS)
  }

  resetTimeout()

  try {
    const token = localStorage.getItem('token') || ''
    const response = await fetch(`/api/v1/llm/conversations/${streamingConvId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ content, use_rag: true, stream: true }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      if (response.status === 401) notifyRetry('登录状态已过期。')
      else if (response.status === 429) notifyRetry('当前请求较多。')
      else notifyRetry(`服务返回 ${response.status}。`)
      return
    }

    if (!response.body) {
      notifyRetry('服务返回为空。')
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      resetTimeout()
      sseBuffer += decoder.decode(value, { stream: true })
      const lines = sseBuffer.split('\n')
      sseBuffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6).trim()
        if (!jsonStr) continue

        try {
          const data = JSON.parse(jsonStr)
          if (currentConvId.value !== streamingConvId) return

          if (data.token) streamContent.value += data.token
          if (data.content && data.type === 'final_answer') streamContent.value = data.content
          if (data.error) notifyRetry(data.error)

          if (data.done) {
            messages.value.push({
              message_id: data.message_id || Date.now(),
              role: 'assistant',
              content: streamContent.value,
              sources: data.sources || [],
            })
            streamContent.value = ''
          }
        } catch {
          continue
        }
      }

      await nextTick()
      messagesRef.value?.scrollTo(0, messagesRef.value.scrollHeight)
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      if (streamContent.value) {
        messages.value.push({
          message_id: Date.now(),
          role: 'assistant',
          content: `${streamContent.value}\n\n[Stopped]`,
          sources: [],
        })
        streamContent.value = ''
      }
    } else {
      notifyRetry('网络连接不稳定。')
    }
  } finally {
    streaming.value = false
    streamingConvId = null
    abortController = null
    if (streamTimeout) {
      clearTimeout(streamTimeout)
      streamTimeout = null
    }
  }
}

function abortStream() {
  if (abortController) abortController.abort()
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
.chat-workspace {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 18px;
  min-height: calc(100vh - 86px);
  padding: 24px;
}

.history-rail {
  min-height: 0;
  padding: 18px;
  border: 1px solid var(--app-border);
  border-radius: 22px;
  background: rgba(15, 23, 42, 0.58);
  backdrop-filter: blur(18px);
  box-shadow: var(--app-shadow-soft);
}

.rail-create {
  width: 100%;
  min-height: 52px;
  margin-bottom: 16px;
  font-weight: 800;
}

.history-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 4px;
  border: 0;
  color: var(--app-text-strong);
  background: transparent;
  cursor: pointer;
  font-weight: 700;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 230px);
  overflow: auto;
}

.history-item {
  padding: 14px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 16px;
  background: rgba(30, 41, 59, 0.46);
  cursor: pointer;
  transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}

.history-item:hover,
.history-item.active {
  transform: translateY(-1px);
  border-color: rgba(20, 184, 166, 0.38);
  background: rgba(20, 184, 166, 0.12);
}

.history-item.disabled {
  pointer-events: none;
  opacity: 0.5;
}

.history-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta,
.history-empty {
  margin-top: 6px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.chat-stage {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 18px;
  min-width: 0;
}

.chat-stage.empty {
  grid-template-rows: 1fr auto 1fr;
  align-content: center;
}

.chat-hero {
  display: grid;
  place-items: center;
  text-align: center;
  padding: 10px 0 0;
}

.chat-stage:not(.empty) .chat-hero {
  display: none;
}

.ai-orb {
  position: relative;
  width: 78px;
  height: 78px;
  display: grid;
  place-items: center;
  margin-bottom: 18px;
}

.ai-orb::before,
.ai-orb::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 999px;
  border: 1px solid rgba(20, 184, 166, 0.36);
  animation: breathe 3s ease-in-out infinite;
}

.ai-orb::after {
  animation-delay: 1.5s;
}

.ai-core {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 20px;
  color: #ffffff;
  font-weight: 900;
  background: linear-gradient(135deg, #14b8a6 0%, #2563eb 100%);
  box-shadow: 0 20px 50px rgba(20, 184, 166, 0.22);
}

.chat-hero h1 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: 34px;
}

.chat-hero p {
  margin: 10px 0 0;
  color: var(--app-text-muted);
}

.message-panel {
  min-height: 0;
  overflow: hidden;
}

.messages {
  height: 100%;
  max-height: calc(100vh - 276px);
  padding: 22px;
  overflow: auto;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  border-radius: 14px;
  color: var(--app-text-strong);
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.16);
  font-size: 12px;
  font-weight: 800;
}

.bubble {
  max-width: min(860px, 74%);
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.62);
  line-height: 1.75;
  box-shadow: var(--app-shadow-soft);
}

.message.user .bubble {
  border-color: rgba(20, 184, 166, 0.28);
  background: linear-gradient(135deg, rgba(20, 184, 166, 0.26), rgba(37, 99, 235, 0.22));
}

.message-label {
  margin-bottom: 8px;
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.sources {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.source-label {
  margin-right: 4px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.composer {
  width: min(920px, 100%);
  justify-self: center;
  padding: 18px;
}

.composer :deep(.el-textarea__inner) {
  min-height: 112px !important;
  border-radius: 18px;
  font-size: 15px;
  line-height: 1.7;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 14px;
}

.composer-hint {
  color: var(--app-text-muted);
  font-size: 12px;
}

.composer-buttons {
  display: flex;
  gap: 10px;
}

.cursor {
  animation: blink 1s infinite;
}

.soft-slide-enter-active,
.soft-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.soft-slide-enter-from,
.soft-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@keyframes breathe {
  0%,
  100% {
    transform: scale(0.88);
    opacity: 0.5;
  }
  50% {
    transform: scale(1.12);
    opacity: 0.12;
  }
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

@media (max-width: 1180px) {
  .chat-workspace {
    grid-template-columns: 1fr;
  }

  .history-list {
    max-height: 240px;
  }

  .bubble {
    max-width: 100%;
  }
}
</style>
