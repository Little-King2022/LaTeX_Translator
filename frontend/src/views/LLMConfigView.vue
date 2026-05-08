<template>
  <div>
    <div class="page-head">
      <h1>LLM 配置</h1>
      <el-button type="primary" @click="newConfig"><Plus :size="16" />新增配置</el-button>
    </div>

    <div class="grid-two">
      <div class="panel">
        <el-table :data="configs" highlight-current-row @row-click="selectConfig">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="model" label="模型" />
          <el-table-column label="API Key">
            <template #default="{ row }">{{ row.api_key_masked || '未设置' }}</template>
          </el-table-column>
          <el-table-column label="默认" width="80">
            <template #default="{ row }"><el-tag v-if="row.is_default" type="success">默认</el-tag></template>
          </el-table-column>
          <el-table-column width="90">
            <template #default="{ row }">
              <el-popconfirm title="删除配置？" @confirm.stop="remove(row.id)">
                <template #reference><el-button size="small" type="danger" @click.stop>删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <el-form label-position="top" :model="form">
          <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="Base URL"><el-input v-model="form.base_url" placeholder="http://127.0.0.1:11434/v1" /></el-form-item>
          <el-form-item label="API Key"><el-input v-model="form.api_key" type="password" show-password placeholder="留空表示保存时保留原值" /></el-form-item>
          <el-form-item label="Model"><el-input v-model="form.model" /></el-form-item>
          <div class="grid-two">
            <el-form-item label="Temperature"><el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
            <el-form-item label="Top P"><el-input-number v-model="form.top_p" :min="0" :max="1" :step="0.05" /></el-form-item>
          </div>
          <div class="grid-two">
            <el-form-item label="Max Tokens"><el-input-number v-model="form.max_tokens" :min="256" :max="64000" /></el-form-item>
            <el-form-item label="Timeout"><el-input-number v-model="form.timeout" :min="10" :max="600" /></el-form-item>
          </div>
          <el-form-item label="翻译并发数">
            <el-input-number v-model="form.llm_concurrency" :min="1" :max="16" />
          </el-form-item>
          <el-form-item><el-checkbox v-model="form.is_default">设为默认配置</el-checkbox></el-form-item>
          <div class="toolbar">
            <el-button type="primary" @click="save"><Save :size="16" />保存配置</el-button>
            <el-button :disabled="!selectedId" @click="test"><PlugZap :size="16" />测试连接</el-button>
          </div>
          <el-alert v-if="message" :title="message" type="success" show-icon style="margin-top: 14px" />
          <el-alert v-if="error" :title="error" type="error" show-icon style="margin-top: 14px" />
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { PlugZap, Plus, Save } from 'lucide-vue-next';
import { onMounted, reactive, ref } from 'vue';
import { api } from '../api/client';

const configs = ref([]);
const selectedId = ref(null);
const message = ref('');
const error = ref('');
const empty = () => ({
  name: 'Default',
  base_url: 'http://127.0.0.1:11434/v1',
  api_key: '',
  model: 'qwen2.5:14b',
  temperature: 0.2,
  top_p: 1,
  max_tokens: 4096,
  timeout: 120,
  llm_concurrency: 1,
  stream: false,
  is_default: true
});
const form = reactive(empty());

function reset(next) {
  Object.assign(form, next);
}

function newConfig() {
  selectedId.value = null;
  reset(empty());
}

function selectConfig(row) {
  selectedId.value = row.id;
  reset({ ...row, api_key: '' });
}

async function load() {
  const { data } = await api.get('/llm-configs');
  configs.value = data;
  if (data.length && !selectedId.value) selectConfig(data[0]);
}

async function save() {
  message.value = '';
  error.value = '';
  try {
    if (selectedId.value) await api.put(`/llm-configs/${selectedId.value}`, form);
    else {
      const { data } = await api.post('/llm-configs', form);
      selectedId.value = data.id;
    }
    message.value = '配置已保存';
    await load();
  } catch (err) {
    error.value = err.response?.data?.detail || '保存失败';
  }
}

async function test() {
  message.value = '';
  error.value = '';
  try {
    await api.post(`/llm-configs/${selectedId.value}/test`);
    message.value = '连接测试成功';
  } catch (err) {
    error.value = err.response?.data?.detail || '连接测试失败';
  }
}

async function remove(id) {
  await api.delete(`/llm-configs/${id}`);
  selectedId.value = null;
  await load();
}

onMounted(load);
</script>
