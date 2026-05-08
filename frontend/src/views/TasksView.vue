<template>
  <div>
    <div class="page-head">
      <div>
        <h1>任务管理</h1>
        <div class="muted task-count">共 {{ tasks.length }} 个翻译任务</div>
      </div>
      <div class="toolbar">
        <el-input v-model="newTaskName" placeholder="任务名称" style="width: 220px" clearable />
        <el-select v-model="newTaskConfig" placeholder="LLM 配置" style="width: 180px" clearable>
          <el-option v-for="config in configs" :key="config.id" :label="config.name" :value="config.id" />
        </el-select>
        <el-button type="primary" :loading="creating" @click="createTask"><Plus :size="16" />新建任务</el-button>
      </div>
    </div>

    <div class="panel">
      <el-table v-loading="loading" :data="tasks" stripe :row-class-name="rowClassName">
        <template #empty>
          <el-empty description="暂无任务，请先新建一个 LaTeX 翻译任务" />
        </template>
        <el-table-column label="任务名称" min-width="220">
          <template #default="{ row }">
            <div class="task-name-cell">
              <component :is="statusIcon(row.status)" :size="17" :class="['status-icon', 'status-' + row.status]" />
              <div>
                <div class="task-name">{{ row.name }}</div>
                <div class="muted task-meta">主文件：{{ row.main_tex_path || '未上传' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="170">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="progress(row)" :stroke-width="8" :status="row.status === 'failed' ? 'exception' : undefined" />
            <div class="muted progress-meta">
              完成 {{ row.translated_blocks || 0 }} / {{ row.total_blocks || 0 }}
              <template v-if="row.failed_blocks">，失败 {{ row.failed_blocks }}</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="PDF" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="row.original_pdf_path ? 'success' : 'info'">英</el-tag>
            <el-tag size="small" :type="row.translated_pdf_path ? 'success' : 'info'" style="margin-left: 6px">中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="$router.push(`/tasks/${row.id}`)">查看详情</el-button>
            <el-popconfirm title="删除该任务？" @confirm="deleteTask(row.id)">
              <template #reference><el-button size="small" type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { AlertTriangle, CheckCircle2, Circle, Loader2, Plus, XCircle } from 'lucide-vue-next';
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { api } from '../api/client';

const router = useRouter();
const tasks = ref([]);
const configs = ref([]);
const newTaskName = ref('');
const newTaskConfig = ref(null);
const loading = ref(false);
const creating = ref(false);
let timer;

function progress(row) {
  if (!row.total_blocks) return row.translated_pdf_path ? 100 : 0;
  return Math.round((row.translated_blocks / row.total_blocks) * 100);
}

function statusType(status) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'warning';
  if (status === 'translating' || status?.startsWith('compiling') || status === 'extracting') return 'primary';
  return 'info';
}

function statusLabel(status) {
  const labels = {
    created: '待上传',
    uploaded: '已上传',
    compiling_original: '编译英文中',
    extracting: '提取术语中',
    waiting_glossary_review: '待审阅术语',
    translating: '翻译中',
    compiling_translated: '编译中文中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return labels[status] || status;
}

function statusIcon(status) {
  if (status === 'completed') return CheckCircle2;
  if (status === 'failed') return XCircle;
  if (status === 'cancelled') return AlertTriangle;
  if (status === 'translating' || status?.startsWith('compiling') || status === 'extracting') return Loader2;
  return Circle;
}

function rowClassName({ row }) {
  if (row.status === 'failed') return 'task-row-failed';
  if (row.status === 'completed') return 'task-row-completed';
  if (row.status === 'translating' || row.status?.startsWith('compiling') || row.status === 'extracting') return 'task-row-running';
  return '';
}

function formatDateTime(value) {
  if (!value) return '-';
  const raw = String(value);
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : raw + 'Z';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return raw.replace('T', ' ').replace(/\.\d+$/, '').slice(0, 16);
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).replace(/\//g, '-');
}

async function load() {
  loading.value = true;
  try {
    const [taskRes, configRes] = await Promise.all([api.get('/tasks'), api.get('/llm-configs')]);
    tasks.value = taskRes.data;
    configs.value = configRes.data;
  } finally {
    loading.value = false;
  }
}

async function createTask() {
  creating.value = true;
  try {
    const name = newTaskName.value.trim() || `LaTeX 翻译任务 ${new Date().toLocaleString()}`;
    const { data } = await api.post('/tasks', { name, llm_config_id: newTaskConfig.value });
    ElMessage.success('任务已创建');
    router.push(`/tasks/${data.id}`);
  } finally {
    creating.value = false;
  }
}

async function deleteTask(id) {
  await api.delete(`/tasks/${id}`);
  ElMessage.success('任务已删除');
  await load();
}

onMounted(() => {
  load();
  timer = setInterval(load, 4000);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.task-count {
  margin-top: 6px;
  font-size: 13px;
}

.task-name-cell {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.task-name {
  font-weight: 600;
  color: #111827;
}

.task-meta,
.progress-meta {
  margin-top: 4px;
  font-size: 12px;
}

.status-icon {
  flex: 0 0 auto;
  margin-top: 2px;
}

.status-completed {
  color: #16a34a;
}

.status-failed {
  color: #dc2626;
}

.status-cancelled {
  color: #d97706;
}

.status-translating,
.status-compiling_original,
.status-compiling_translated,
.status-extracting {
  color: #2563eb;
  animation: spin 1.2s linear infinite;
}

:deep(.task-row-failed) {
  --el-table-tr-bg-color: #fff7f7;
}

:deep(.task-row-completed) {
  --el-table-tr-bg-color: #f7fff9;
}

:deep(.task-row-running) {
  --el-table-tr-bg-color: #f7fbff;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

