<template>
  <div>
    <div class="page-head">
      <h1>任务管理</h1>
      <div class="toolbar">
        <el-input v-model="newTaskName" placeholder="任务名称" style="width: 220px" />
        <el-select v-model="newTaskConfig" placeholder="LLM 配置" style="width: 180px" clearable>
          <el-option v-for="config in configs" :key="config.id" :label="config.name" :value="config.id" />
        </el-select>
        <el-button type="primary" @click="createTask"><Plus :size="16" />新建任务</el-button>
      </div>
    </div>

    <div class="panel">
      <el-table :data="tasks" stripe>
        <el-table-column prop="name" label="任务名称" min-width="180" />
        <el-table-column prop="status" label="状态" width="170">
          <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="progress(row)" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="PDF" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="row.original_pdf_path ? 'success' : 'info'">英</el-tag>
            <el-tag size="small" :type="row.translated_pdf_path ? 'success' : 'info'" style="margin-left: 6px">中</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="上传时间" min-width="190" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">查看详情</el-button>
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
import { Plus } from 'lucide-vue-next';
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api/client';

const router = useRouter();
const tasks = ref([]);
const configs = ref([]);
const newTaskName = ref('');
const newTaskConfig = ref(null);
let timer;

function progress(row) {
  if (!row.total_blocks) return row.translated_pdf_path ? 100 : 0;
  return Math.round((row.translated_blocks / row.total_blocks) * 100);
}

function statusType(status) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'warning';
  return 'info';
}

async function load() {
  const [taskRes, configRes] = await Promise.all([api.get('/tasks'), api.get('/llm-configs')]);
  tasks.value = taskRes.data;
  configs.value = configRes.data;
}

async function createTask() {
  const name = newTaskName.value.trim() || `LaTeX 翻译任务 ${new Date().toLocaleString()}`;
  const { data } = await api.post('/tasks', { name, llm_config_id: newTaskConfig.value });
  router.push(`/tasks/${data.id}`);
}

async function deleteTask(id) {
  await api.delete(`/tasks/${id}`);
  await load();
}

onMounted(() => {
  load();
  timer = setInterval(load, 4000);
});
onUnmounted(() => clearInterval(timer));
</script>

