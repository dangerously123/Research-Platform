<template>
  <div class="chat-container">
    <div class="sidebar">
      <el-button
        type="primary"
        @click="createConversation"
        :loading="creatingConv"
        :disabled="streaming"
        style="width:100%;margin-bottom:12px"
      >
        New Chat
      </el-button>
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: currentConvId === conv.id, disabled: streaming }"
        @click="selectConversation(conv.id)"
      >
        {{ conv.title || `Conversation #${conv.id}` }}
      </div>
    </div>

    <div class="chat-area">
      <div class="messages" ref="messagesRef">
        <div v-if="!messages.length && !streaming" class="empty-state">
          <p>Start a new conversation and enter your question.</p>
        </div>

        <div v-for="msg in messages" :key="msg.message_id" class="message" :class="msg.role">
          <div class="bubble">
            <div class="content" v-html="renderMarkdown(msg.content)"></div>
            <div v-if="msg.sources?.length" class="sources">
              <span class="source-label">Sources:</span>
              <el-tag v-for="source in msg.sources" :key="source.doc_id" size="small" type="info">
                {{ source.title }}
              </el-tag>
            </div>
          </div>
        </div>

        <div v-if="streaming" class="message assistant">
          <div class="bubble">
            <div class="content">{{ streamContent }}<span class="cursor">|</span></div>
          </div>
        </div>

        <div v-if="errorMsg" class="error-banner">
          <el-alert :title="errorMsg" type="error" show-icon closable @close="errorMsg = ''" />
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="inputText"
          placeholder="Ask a question... (Ctrl+Enter to send)"
          :rows="2"
          type="textarea"
          @keydown.enter.ctrl="sendMessage"
          :disabled="streaming"
        />
        <el-button
          type="primary"
          @click="sendMessage"
          :loading="streaming"
          :disabled="!inputText.trim() || streaming"
        >
          Send
        </el-button>
        <el-button v-if="streaming" type="danger" size="small" @click="abortStream">
          Stop
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
    errorMsg.value = ''
  } catch {
    errorMsg.value = 'Failed to create conversation.'
  } finally {
    creatingConv.value = false
  }
}

async function selectConversation(id: number) {
  if (streaming.value) return
  if (currentConvId.value === id) return

  currentConvId.value = id
  errorMsg.value = ''
  try {
    const res = await api.get(`/llm/conversations/${id}/messages`)
    messages.value = res.data.messages || []
  } catch {
    messages.value = []
    errorMsg.value = 'Failed to load conversation history.'
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
  errorMsg.value = ''
  messages.value.push({ message_id: Date.now(), role: 'user', content, sources: [] })

  streaming.value = true
  streamContent.value = ''
  streamingConvId = currentConvId.value
  abortController = new AbortController()
  let sseBuffer = ''

  const resetTimeout = () => {
    if (streamTimeout) clearTimeout(streamTimeout)
    streamTimeout = setTimeout(() => {
      errorMsg.value = 'Response timed out. Please retry.'
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
      if (response.status === 401) errorMsg.value = 'Login expired. Please sign in again.'
      else if (response.status === 429) errorMsg.value = 'Too many requests. Please retry later.'
      else errorMsg.value = `Service error (${response.status}). Please retry.`
      return
    }

    if (!response.body) {
      errorMsg.value = 'Server returned an empty response.'
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
          if (data.error) errorMsg.value = data.error

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
      errorMsg.value = 'Network error. Please check your connection and retry.'
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
