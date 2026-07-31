<template>
  <div class="chat-container">
    <!-- 会话列表侧边 -->
    <div class="sidebar">
      <el-button type="primary" @click="createConversation" :loading="creatingConv"
        :disabled="streaming" style="width:100%;margin-bottom:12px">
        新建对话
      </el-button>
      <div v-for="conv in conversations" :key="conv.id"
        class="conv-item" :class="{ active: currentConvId === conv.id, disabled: streaming }"
        @click="selectConversation(conv.id)">
        {{ conv.title || `对话 #${conv.id}` }}
      </div>
    </div>

    <!-- 聊天区域 -->
    <div class="chat-area">
      <!-- 消息列表 -->
      <div class="messages" ref="messagesRef">
        <!-- 空状态 -->
        <div v-if="!messages.length && !streaming" class="empty-state">
          <p>开始新对话，输入您的问题</p>
        </div>

        <div v-for="msg in messages" :key="msg.message_id" class="message" :class="msg.role">
          <div class="bubble">
            <div class="content" v-html="renderMarkdown(msg.content)"></div>
            <div v-if="msg.sources?.length" class="sources">
              <span class="source-label">参考来源：</span>
              <el-tag v-for="s in msg.sources" :key="s.doc_id" size="small" type="info">
                {{ s.title }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 流式响应 -->
        <div v-if="streaming" class="message assistant">
          <div class="bubble">
            <div class="content">{{ streamContent }}<span class="cursor">|</span></div>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="errorMsg" class="error-banner">
          <el-alert :title="errorMsg" type="error" show-icon closable
            @close="errorMsg = ''" />
        </div>
      </div>

      <!-- 输入框 -->
      <div class="input-area">
        <el-input v-model="inputText" placeholder="输入问题... (Ctrl+Enter 发送)"
          :rows="2" type="textarea"
          @keydown.enter.ctrl="sendMessage" :disabled="streaming" />
        <el-button type="primary" @click="sendMessage" :loading="streaming"
          :disabled="!inputText.trim() || streaming">
          发送
        </el-button>
        <el-button v-if="streaming" type="danger" size="small" @click="abortStream">
          停止
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import api from '@/utils/api'

const conversations = ref<any[]>([])
const currentConvId = ref<number | null>(null)
const messages = ref<any[]>([])
const inputText = ref('')
const streaming = ref(false)
const streamContent = ref('')
const messagesRef = ref<HTMLElement>()
const errorMsg = ref('')
const creatingConv = ref(false)

// SSE 控制
let abortController: AbortController | null = null
let streamTimeout: ReturnType<typeof setTimeout> | null = null
const STREAM_TIMEOUT_MS = 90_000 // 90秒无数据超时

// 会话切换锁：记录当前流式绑定的会话ID
let streamingConvId: number | null = null

onMounted(() => { loadConversations() })

onBeforeUnmount(() => {
  // 页面卸载时取消进行中的流式请求
  abortStream()
})

async function loadConversations() {
  try {
    // 实际项目中应分页加载
    conversations.value = []
  } catch {
    // 静默
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
    errorMsg.value = ''
  } catch (e: any) {
    errorMsg.value = '创建对话失败'
  } finally {
    creatingConv.value = false
  }
}

async function selectConversation(id: number) {
  // 流式回答中禁止切换会话
  if (streaming.value) return
  if (currentConvId.value === id) return

  currentConvId.value = id
  errorMsg.value = ''
  try {
    const res = await api.get(`/llm/conversations/${id}/messages`)
    messages.value = res.data.messages
  } catch {
    messages.value = []
    errorMsg.value = '加载会话历史失败'
  }
}

async function sendMessage() {
  if (!inputText.value.trim() || streaming.value) return

  // 确保有会话
  if (!currentConvId.value) {
    await createConversation()
    if (!currentConvId.value) return
  }

  const content = inputText.value.trim()
  inputText.value = ''
  errorMsg.value = ''
  messages.value.push({ message_id: Date.now(), role: 'user', content, sources: [] })

  // 开始 SSE 流式接收
  streaming.value = true
  streamContent.value = ''
  streamingConvId = currentConvId.value

  // 创建 AbortController
  abortController = new AbortController()
  let sseBuffer = '' // 分片 buffer

  // 超时检测
  const resetTimeout = () => {
    if (streamTimeout) clearTimeout(streamTimeout)
    streamTimeout = setTimeout(() => {
      abortStream()
      errorMsg.value = '响应超时，请重试'
    }, STREAM_TIMEOUT_MS)
  }
  resetTimeout()

  try {
    const token = localStorage.getItem('token') || ''
    const response = await fetch(
      `/api/v1/llm/conversations/${streamingConvId}/messages`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ content, use_rag: true, stream: true }),
        signal: abortController.signal,
      },
    )

    // HTTP 状态检查
    if (!response.ok) {
      const status = response.status
      if (status === 401) {
        errorMsg.value = '登录已过期，请重新登录'
      } else if (status === 429) {
        errorMsg.value = '请求频率过高，请稍后再试'
      } else {
        errorMsg.value = `服务错误 (${status})，请重试`
      }
      return
    }

    if (!response.body) {
      errorMsg.value = '服务器返回空响应'
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // 每收到数据重置超时
      resetTimeout()

      // 分片安全解析：追加到 buffer 后按完整行处理
      sseBuffer += decoder.decode(value, { stream: true })
      const lines = sseBuffer.split('\n')
      // 最后一行可能不完整，保留在 buffer
      sseBuffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6).trim()
        if (!jsonStr) continue

        try {
          const data = JSON.parse(jsonStr)

          // 检查会话是否仍匹配（防止切换后写入错误会话）
          if (currentConvId.value !== streamingConvId) break

          if (data.token) {
            streamContent.value += data.token
          }
          if (data.done) {
            messages.value.push({
              message_id: data.message_id || Date.now(),
              role: 'assistant',
              content: streamContent.value,
              sources: [],
            })
            streamContent.value = ''
          }
          if (data.error) {
            errorMsg.value = data.error
          }
        } catch {
          // JSON 解析失败：跳过（可能是空行或格式异常）
          continue
        }
      }

      await nextTick()
      messagesRef.value?.scrollTo(0, messagesRef.value.scrollHeight)
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      // 用户主动取消，不显示错误
      if (streamContent.value) {
        messages.value.push({
          message_id: Date.now(),
          role: 'assistant',
          content: streamContent.value + '\n\n[已停止]',
          sources: [],
        })
        streamContent.value = ''
      }
    } else {
      errorMsg.value = '网络连接失败，请检查网络后重试'
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
  if (abortController) {
    abortController.abort()
  }
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  // 安全处理：转义 HTML 特殊字符后再替换换行
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
  return escaped.replace(/\n/g, '<br>')
}
</script>

<style scoped>
.chat-container { display: flex; height: calc(100vh - 100px); }
.sidebar { width: 220px; border-right: 1px solid #eee; padding: 12px; overflow-y: auto; }
.conv-item { padding: 8px 12px; cursor: pointer; border-radius: 4px; margin-bottom: 4px; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-item:hover, .conv-item.active { background: #ecf5ff; color: #409eff; }
.conv-item.disabled { pointer-events: none; opacity: 0.5; }
.chat-area { flex: 1; display: flex; flex-direction: column; }
.messages { flex: 1; overflow-y: auto; padding: 16px; }
.empty-state { display: flex; align-items: center; justify-content: center; height: 100%; color: #909399; }
.message { margin-bottom: 16px; display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }
.bubble { max-width: 70%; padding: 12px 16px; border-radius: 8px; font-size: 14px; line-height: 1.6; }
.message.user .bubble { background: #409eff; color: #fff; }
.message.assistant .bubble { background: #f4f4f5; }
.sources { margin-top: 8px; }
.source-label { font-size: 12px; color: #909399; }
.input-area { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #eee; align-items: flex-end; }
.input-area .el-input { flex: 1; }
.error-banner { margin-top: 8px; }
.cursor { animation: blink 1s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
</style>
