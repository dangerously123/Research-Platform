import axios from 'axios'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 防止多个 401 并发时重复跳转
let isRedirecting = false

// 请求拦截器：附加 Token
api.interceptors.request.use((config) => {
  const userStore = useUserStore()
  if (userStore.token) {
    config.headers.Authorization = `Bearer ${userStore.token}`
  }
  return config
})

// 响应拦截器：处理 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !isRedirecting) {
      isRedirecting = true
      const userStore = useUserStore()
      userStore.logout()
      router.push('/login').finally(() => {
        // 跳转完成后重置标记，允许后续再次触发
        setTimeout(() => { isRedirecting = false }, 1000)
      })
    }
    return Promise.reject(error)
  }
)

export default api
