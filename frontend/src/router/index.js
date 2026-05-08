import { createRouter, createWebHistory } from 'vue-router';
import LoginView from '../views/LoginView.vue';
import TasksView from '../views/TasksView.vue';
import TaskDetailView from '../views/TaskDetailView.vue';
import LLMConfigView from '../views/LLMConfigView.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/', redirect: '/tasks' },
    { path: '/tasks', component: TasksView },
    { path: '/tasks/:id', component: TaskDetailView },
    { path: '/llm-configs', component: LLMConfigView }
  ]
});

router.beforeEach((to) => {
  if (to.path !== '/login' && !localStorage.getItem('token')) return '/login';
});

export default router;

