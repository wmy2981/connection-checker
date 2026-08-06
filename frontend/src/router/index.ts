import { createRouter, createWebHistory } from 'vue-router'

import { checkAuth } from '@/store/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('@/views/ConfigView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
  const authenticated = await checkAuth()
  if (!authenticated && !to.meta.public) return { name: 'login' }
  if (authenticated && to.name === 'login') return { name: 'dashboard' }
  return true
})

export default router
