/**
 * 工具管理 API。
 */

import api from '@/utils/api'

export interface ToolInfo {
  name: string
  description: string
  category: string
  parameters: Record<string, unknown>
  examples: string[]
}

export interface ExecuteToolRequest {
  tool_name: string
  params: Record<string, unknown>
}

/** 获取工具列表 */
export function listTools(category?: string) {
  return api.get<ToolInfo[]>('/tools', { params: category ? { category } : undefined })
}

/** 获取工具分类 */
export function listCategories() {
  return api.get<{ categories: string[] }>('/tools/categories')
}

/** 手动执行工具 */
export function executeTool(data: ExecuteToolRequest) {
  return api.post('/tools/execute', data)
}
