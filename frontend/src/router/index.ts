import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', name: 'Chat', component: () => import('@/views/Chat.vue') },
        { path: 'knowledge', name: 'Knowledge', component: () => import('@/views/Knowledge.vue') },
        { path: 'reports', name: 'Reports', component: () => import('@/views/Reports.vue') },
        { path: 'memories', name: 'Memories', component: () => import('@/views/Memories.vue') },
        { path: 'admin/roles', name: 'Roles', component: () => import('@/views/admin/Roles.vue') },
        { path: 'admin/prompts', name: 'Prompts', component: () => import('@/views/admin/Prompts.vue') },
        { path: 'admin/tokens', name: 'Tokens', component: () => import('@/views/admin/Tokens.vue') },
        { path: 'admin/models', name: 'Models', component: () => import('@/views/admin/Models.vue') },
        { path: 'admin/audit', name: 'Audit', component: () => import('@/views/admin/Audit.vue') },
      ],
    },
  ],
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  if (to.meta.requiresAuth !== false && !userStore.token) {
    next('/login')
  } else {
    next()
  }
})

export default router
