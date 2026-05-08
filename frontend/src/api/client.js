import axios from 'axios';

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
    }
    return Promise.reject(error);
  }
);

export async function fetchBlob(url) {
  const response = await api.get(url, { responseType: 'blob' });
  return URL.createObjectURL(response.data);
}

