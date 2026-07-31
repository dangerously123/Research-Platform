/**
 * LLM 模型管理 API。
 */

import api from '@/utils/api'

export interface ModelConfig {
  model_id: string
  model_name: string
  provider: string
  status: string
  priority: number
  avg_latency_ms: number | null
  last_health_check: string | null
}

export interface AddModelRequest {
  model_id: string
  model_name: string
  provider: string
  endpoint_url: string
  api_key?: string
  priority?: number
  context_window?: number
  max_tokens?: number
  temperature?: number
  task_types?: string[]
}

/** 获取模型列表 */
export function listModels() {
  return api.get<ModelConfig[]>('/llm/models')
}

/** 添加模型（管理员） */
export function addModel(data: AddModelRequest) {
  return api.post('/llm/models', data)
}

/** 健康检查 */
export function healthCheck(modelId: string) {
  return api.post(`/llm/models/${modelId}/health-check`)
}

/** 删除模型（管理员） */
export function deleteModel(modelId: string) {
  return api.delete(`/llm/models/${modelId}`)
}
