import axios from 'axios';
import { ElMessage } from 'element-plus';

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      if (location.pathname !== '/login') location.href = '/login';
    } else if (!error.response) {
      ElMessage.error('网络连接异常，请检查后端服务是否可用');
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请稍后重试');
    } else if (error.response?.status >= 500) {
      ElMessage.error(error.response?.data?.detail || '服务端异常，请查看后台日志');
    }
    return Promise.reject(error);
  }
);

export async function fetchBlob(url) {
  const response = await api.get(url, { responseType: 'blob' });
  return URL.createObjectURL(response.data);
}

