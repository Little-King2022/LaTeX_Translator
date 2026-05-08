<template>
  <div class="login-page">
    <div class="login-panel">
      <h1>LaTeX Translator</h1>
      <el-form :model="form" @submit.prevent="login">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
        <el-button type="primary" size="large" native-type="submit" :loading="loading">登录</el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api/client';

const router = useRouter();
const loading = ref(false);
const error = ref('');
const form = reactive({ username: 'admin', password: '' });

async function login() {
  loading.value = true;
  error.value = '';
  try {
    const { data } = await api.post('/auth/login', form);
    localStorage.setItem('token', data.access_token);
    router.push('/tasks');
  } catch (err) {
    error.value = err.response?.data?.detail || '登录失败';
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: #eef2f7;
}

.login-panel {
  width: min(380px, calc(100vw - 32px));
  background: white;
  border: 1px solid #d9dee7;
  border-radius: 8px;
  padding: 28px;
}

h1 {
  margin: 0 0 22px;
  font-size: 22px;
}

.el-button {
  width: 100%;
  margin-top: 14px;
}
</style>

