/**
 * LLM 对话相关 API。
 */

import api from '@/utils/api'

export interface CreateConversationRequest {
  title?: string
}

export interface Conversation {
  id: number
  title: string | null
  status: string
  model_id: string | null
  total_input_tokens: number
  total_output_tokens: number
  created_at: string
}

export interface SendMessageRequest {
  content: string
  file_ids?: number[]
  use_rag?: boolean
  stream?: boolean
}

export interface MessageResponse {
  message_id: number
  role: string
  content: string
  sources?: Array<{ doc_id: string; title: string; relevance_score: number; snippet: string }>
  input_tokens?: number
  output_tokens?: number
}

/** 创建新对话 */
export function createConversation(data: CreateConversationRequest) {
  return api.post<Conversation>('/llm/conversations', data)
}

/** 发送消息（非流式） */
export function sendMessage(conversationId: number, data: SendMessageRequest) {
  return api.post<MessageResponse>(`/llm/conversations/${conversationId}/messages`, {
    ...data,
    stream: false,
  })
}

/**
 * 发送消息（SSE 流式）。
 * 返回 EventSource URL，前端用 fetch + ReadableStream 处理。
 */
export function sendMessageStream(conversationId: number, data: SendMessageRequest) {
  return api.post(`/llm/conversations/${conversationId}/messages`, {
    ...data,
    stream: true,
  }, {
    responseType: 'stream',
  })
}

/** 重新生成最后一条回答 */
export function regenerate(conversationId: number) {
  return api.post<MessageResponse>(`/llm/conversations/${conversationId}/regenerate`)
}

/** 获取会话历史 */
export function getHistory(conversationId: number) {
  return api.get(`/llm/conversations/${conversationId}/messages`)
}

/** 删除会话 */
export function deleteConversation(conversationId: number) {
  return api.delete(`/llm/conversations/${conversationId}`)
}
