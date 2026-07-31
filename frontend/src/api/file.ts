/**
 * 文件上传与管理 API。
 */

import api from '@/utils/api'

export interface FileUploadResponse {
  file_id: number
  original_name: string
  file_type: string
  mime_type: string
  file_size: number
  process_status: string
  created_at: string
}

export interface FileInfo extends FileUploadResponse {
  extracted_content?: string | null
  extracted_metadata?: Record<string, unknown> | null
  image_description?: string | null
  ocr_text?: string | null
  error_message?: string | null
  processed_at?: string | null
}

/** 上传文件 */
export function uploadFile(file: File, conversationId?: number) {
  const formData = new FormData()
  formData.append('file', file)

  const params = conversationId ? `?conversation_id=${conversationId}` : ''

  return api.post<FileUploadResponse>(`/files/upload${params}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000, // 上传超时60秒
  })
}

/** 获取文件详情 */
export function getFileInfo(fileId: number) {
  return api.get<FileInfo>(`/files/${fileId}`)
}

/** 获取文件列表 */
export function listFiles(params?: { conversation_id?: number; page?: number; page_size?: number }) {
  return api.get('/files', { params })
}

/** 删除文件 */
export function deleteFile(fileId: number) {
  return api.delete(`/files/${fileId}`)
}
