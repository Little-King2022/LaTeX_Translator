<template>
  <router-view v-if="$route.path === '/login'" v-slot="{ Component }">
    <Transition name="page-fade" mode="out-in">
      <component :is="Component" />
    </Transition>
  </router-view>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand">LaTeX Translator</div>
      <nav>
        <RouterLink to="/tasks"><ListChecks :size="18" />任务管理</RouterLink>
        <RouterLink to="/llm-configs"><Settings :size="18" />LLM 配置</RouterLink>
      </nav>
      <button class="logout" @click="logout"><LogOut :size="17" />退出</button>
    </aside>
    <main class="main">
      <router-view v-slot="{ Component }">
        <Transition name="page-fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { ListChecks, LogOut, Settings } from 'lucide-vue-next';
import { useRouter } from 'vue-router';

const router = useRouter();
function logout() {
  localStorage.removeItem('token');
  router.push('/login');
}
</script>

