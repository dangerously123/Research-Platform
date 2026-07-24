<template>
  <div class="chat-container">
    <!-- 会话列表侧边 -->
    <div class="sidebar">
      <el-button type="primary" @click="createConversation" style="width:100%;margin-bottom:12px">
        新建对话
      </el-button>
      <div v-for="conv in conversations" :key="conv.id"
        class="conv-item" :class="{ active: currentConvId === conv.id }"
        @click="selectConversation(conv.id)">
        {{ conv.title || `对话 #${conv.id}` }}
      </div>
    </div>

    <!-- 聊天区域 -->
    <div class="chat-area">
      <div class="messages" ref="messagesRef">
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
        <div v-if="streaming" class="message assistant">
          <div class="bubble">
            <div class="content">{{ streamContent }}<span class="cursor">|</span></div>
          </div>
        </div>
      </div>

      <!-- 输入框 -->
      <div class="input-area">
        <el-input v-model="inputText" placeholder="输入问题..." :rows="2" type="textarea"
          @keydown.enter.ctrl="sendMessage" :disabled="streaming" />
        <el-button type="primary" @click="sendMessage" :loading="streaming" :disabled="!inputText.trim()">
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import api from '@/utils/api'

const conversations = ref<any[]>([])
const currentConvId = ref<number | null>(null)
const messages = ref<any[]>([])
const inputText = ref('')
const streaming = ref(false)
const streamContent = ref('')
const messagesRef = ref<HTMLElement>()

onMounted(() => { loadConversations() })

async function loadConversations() {
  // 简单实现：实际项目中需要分页加载
  conversations.value = []
}

async function createConversation() {
  const res = await api.post('/llm/conversations', { title: null })
  const conv = res.data
  conversations.value.unshift(conv)
  currentConvId.value = conv.id
  messages.value = []
}

async function selectConversation(id: number) {
  currentConvId.value = id
  const res = await api.get(`/llm/conversations/${id}/messages`)
  messages.value = res.data.messages
}

async function sendMessage() {
  if (!inputText.value.trim() || streaming.value) return
  if (!currentConvId.value) await createConversation()

  const content = inputText.value
  inputText.value = ''
  messages.value.push({ message_id: Date.now(), role: 'user', content, sources: [] })

  // SSE 流式接收
  streaming.value = true
  streamContent.value = ''

  try {
    const response = await fetch(`/api/v1/llm/conversations/${currentConvId.value}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`,
      },
      body: JSON.stringify({ content, use_rag: true, stream: true }),
    })

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      const lines = text.split('\n')
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6))
          if (data.token) {
            streamContent.value += data.token
          }
          if (data.done) {
            messages.value.push({
              message_id: data.message_id,
              role: 'assistant',
              content: streamContent.value,
              sources: [],
            })
            streamContent.value = ''
          }
          if (data.error) {
            messages.value.push({
              message_id: Date.now(),
              role: 'assistant',
              content: `⚠️ ${data.error}`,
              sources: [],
            })
          }
        }
      }
      await nextTick()
      messagesRef.value?.scrollTo(0, messagesRef.value.scrollHeight)
    }
  } catch (e) {
    messages.value.push({ message_id: Date.now(), role: 'assistant', content: '⚠️ 请求失败', sources: [] })
  } finally {
    streaming.value = false
  }
}

function renderMarkdown(text: string) {
  // 简单处理换行
  return text.replace(/\n/g, '<br>')
}
</script>

<style scoped>
.chat-container { display: flex; height: calc(100vh - 100px); }
.sidebar { width: 220px; border-right: 1px solid #eee; padding: 12px; overflow-y: auto; }
.conv-item { padding: 8px 12px; cursor: pointer; border-radius: 4px; margin-bottom: 4px; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-item:hover, .conv-item.active { background: #ecf5ff; color: #409eff; }
.chat-area { flex: 1; display: flex; flex-direction: column; }
.messages { flex: 1; overflow-y: auto; padding: 16px; }
.message { margin-bottom: 16px; display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }
.bubble { max-width: 70%; padding: 12px 16px; border-radius: 8px; font-size: 14px; line-height: 1.6; }
.message.user .bubble { background: #409eff; color: #fff; }
.message.assistant .bubble { background: #f4f4f5; }
.sources { margin-top: 8px; }
.source-label { font-size: 12px; color: #909399; }
.input-area { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #eee; }
.input-area .el-input { flex: 1; }
.cursor { animation: blink 1s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
</style>
