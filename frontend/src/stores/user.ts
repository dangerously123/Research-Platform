import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'

export interface UserInfo {
  id: number
  username: string
  email: string | null
  department_id: number
  position: string | null
  roles: number[]
}

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<UserInfo | null>(null)
  const roles = ref<any[]>([])
  const permissions = ref<any[]>([])

  const isLoggedIn = computed(() => !!token.value)

  async function login(username: string, password: string) {
    const res = await api.post('/auth/login', { username, password })
    token.value = res.data.access_token
    user.value = res.data.user
    localStorage.setItem('token', token.value)
  }

  async function fetchUserInfo() {
    const res = await api.get('/auth/me')
    user.value = res.data.user
    roles.value = res.data.roles
    permissions.value = res.data.permissions
  }

  function logout() {
    api.post('/auth/logout').catch(() => {})
    token.value = ''
    user.value = null
    roles.value = []
    permissions.value = []
    localStorage.removeItem('token')
  }

  return { token, user, roles, permissions, isLoggedIn, login, fetchUserInfo, logout }
})
