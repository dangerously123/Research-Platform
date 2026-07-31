/**
 * 数据报表 API。
 */

import api from '@/utils/api'

/** 获取报表列表 */
export function listReports(params?: { page?: number; page_size?: number }) {
  return api.get('/reports', { params })
}

/** 获取报表详情 */
export function getReport(reportId: number) {
  return api.get(`/reports/${reportId}`)
}

/** 导出报表 */
export function exportReport(reportId: number, format: 'xlsx' | 'csv' | 'pdf' = 'xlsx') {
  return api.get(`/reports/${reportId}/export`, {
    params: { format },
    responseType: 'blob',
  })
}
