/**
 * 认证相关 API。
 */

import api from '@/utils/api'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface UserInfo {
  user_id: number
  username: string
  department_id: number
  roles: string[]
}

/** 登录 */
export function login(data: LoginRequest) {
  return api.post<LoginResponse>('/auth/login', data)
}

/** 登出 */
export function logout() {
  return api.post('/auth/logout')
}

/** 获取当前用户信息 */
export function getCurrentUser() {
  return api.get<UserInfo>('/auth/me')
}
