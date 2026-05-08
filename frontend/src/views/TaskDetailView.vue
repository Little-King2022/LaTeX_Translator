<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ task?.name || '任务详情' }}</h1>
        <div class="status-line" v-if="task">
          <el-tag :type="statusType(task.status)">{{ task.status }}</el-tag>
          <span class="muted">主文件：{{ task.main_tex_path || '未识别' }}</span>
          <span class="muted">进度：{{ task.translated_blocks }}/{{ task.total_blocks }}</span>
        </div>
      </div>
      <div class="toolbar">
        <el-upload :show-file-list="false" :http-request="uploadZip" accept=".zip">
          <el-button><Upload :size="16" />上传 zip</el-button>
        </el-upload>
        <el-button @click="queue('/compile-original')"><FileCog :size="16" />编译英文</el-button>
        <el-button @click="queue('/extract-glossary')"><ListPlus :size="16" />提取术语</el-button>
        <el-button type="primary" @click="queue('/start-translation')"><Languages :size="16" />确认术语并翻译</el-button>
      </div>
    </div>

    <el-progress v-if="task" :percentage="progress" :stroke-width="10" style="margin-bottom: 16px" />

    <el-tabs v-model="tab" class="panel">
      <el-tab-pane label="概览" name="overview">
        <div class="grid-two">
          <div>
            <h3>任务状态</h3>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="任务 ID">{{ task?.id }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ task?.status }}</el-descriptions-item>
              <el-descriptions-item label="总块数">{{ task?.total_blocks }}</el-descriptions-item>
              <el-descriptions-item label="失败块">{{ task?.failed_blocks }}</el-descriptions-item>
              <el-descriptions-item label="错误">{{ task?.error_message || '无' }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <div>
            <h3>文件下载</h3>
            <div class="toolbar">
              <el-button :disabled="!task?.original_pdf_path" @click="download('/download/original-pdf')">英文 PDF</el-button>
              <el-button :disabled="!task?.translated_pdf_path" @click="download('/download/translated-pdf')">中文 PDF</el-button>
              <el-button :disabled="!comparisonPdfExists" @click="download('/download/comparison-pdf')">对照 PDF</el-button>
              <el-button @click="download('/download/translated-project')">中文项目 zip</el-button>
              <el-button @click="queue('/compile-translated')">重新编译中文</el-button>
              <el-button type="warning" @click="queue('/retry-failed-blocks')">重试失败块</el-button>
              <el-button type="danger" @click="queue('/cancel')">取消任务</el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="术语库" name="glossary">
        <div class="toolbar" style="margin-bottom: 12px">
          <el-input v-model="termSearch" placeholder="搜索术语" style="width: 220px" />
          <el-button type="primary" @click="addTerm"><Plus :size="16" />新增术语</el-button>
          <el-upload :show-file-list="false" :http-request="importTerms" accept=".json">
            <el-button><Upload :size="16" />导入 JSON</el-button>
          </el-upload>
          <el-button @click="download('/glossary/export')">导出 JSON</el-button>
        </div>
        <el-table :data="filteredTerms" stripe>
          <el-table-column label="英文术语" min-width="180">
            <template #default="{ row }"><el-input v-model="row.source_term" @change="saveTerm(row)" /></template>
          </el-table-column>
          <el-table-column label="中文译名" min-width="180">
            <template #default="{ row }"><el-input v-model="row.target_term" @change="saveTerm(row)" /></template>
          </el-table-column>
          <el-table-column label="类型" width="170">
            <template #default="{ row }">
              <el-select v-model="row.term_type" @change="saveTerm(row)">
                <el-option v-for="type in termTypes" :key="type" :label="type" :value="type" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="锁定" width="90">
            <template #default="{ row }"><el-switch v-model="row.is_locked" @change="saveTerm(row)" /></template>
          </el-table-column>
          <el-table-column prop="context" label="上下文" min-width="220" show-overflow-tooltip />
          <el-table-column width="90">
            <template #default="{ row }"><el-button size="small" type="danger" @click="removeTerm(row.id)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="翻译进度" name="blocks">
        <el-table :data="blocks" stripe height="560">
          <el-table-column prop="block_index" label="#" width="70" />
          <el-table-column prop="file_path" label="文件" min-width="180" />
          <el-table-column prop="block_type" label="类型" width="130" />
          <el-table-column label="状态" width="130">
            <template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="source_text" label="原文" min-width="260" show-overflow-tooltip />
          <el-table-column label="译文" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="block-preview">{{ row.translated_text || '未翻译' }}</span>
            </template>
          </el-table-column>
          <el-table-column width="160">
            <template #default="{ row }">
              <el-button size="small" @click="openBlockEditor(row)">编辑</el-button>
              <el-button size="small" @click="retranslate(row.id)">重译</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="PDF 对照" name="pdf">
        <div ref="pdfCompareEl" class="pdf-compare" :class="{ 'is-fullscreen': isPdfFullscreen }">
          <div class="toolbar pdf-toolbar">
            <el-slider v-model="scale" :min="0.7" :max="2" :step="0.1" class="pdf-scale" />
            <el-button type="primary" :disabled="!task?.original_pdf_path || !task?.translated_pdf_path" @click="generateComparisonPdf">
              <FileCog :size="16" />生成/更新对照 PDF
            </el-button>
            <el-button :disabled="!comparisonPdfExists" @click="pdfRefresh++"><RefreshCw :size="16" />刷新 PDF</el-button>
            <el-button :disabled="!comparisonPdfExists" @click="download('/download/comparison-pdf')">下载对照 PDF</el-button>
            <el-button @click="togglePdfFullscreen">
              <Minimize2 v-if="isPdfFullscreen" :size="16" />
              <Maximize2 v-else :size="16" />
              {{ isPdfFullscreen ? '退出全屏' : '全屏展示' }}
            </el-button>
          </div>
          <div v-if="comparisonPdfExists" class="pdf-grid comparison-grid">
            <PdfPane title="中英文对照 PDF" :url="comparisonPdfUrl" :scale="scale" :refresh-key="pdfRefresh" />
          </div>
          <div v-else class="pdf-placeholder">
            请先生成对照 PDF
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="日志" name="logs">
        <div class="log-box">{{ logText }}</div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="blockEditorVisible" title="修改翻译块" width="860px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="原文">
          <el-input v-model="blockForm.source_text" type="textarea" :rows="8" readonly />
        </el-form-item>
        <el-form-item label="译文">
          <el-input v-model="blockForm.translated_text" type="textarea" :rows="10" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="blockForm.status" style="width: 180px">
            <el-option label="completed" value="completed" />
            <el-option label="pending" value="pending" />
            <el-option label="failed" value="failed" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="blockEditorVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBlockEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { FileCog, Languages, ListPlus, Maximize2, Minimize2, Plus, RefreshCw, Upload } from 'lucide-vue-next';
import { ElMessage } from 'element-plus';
import PdfPane from '../components/PdfPane.vue';
import { api } from '../api/client';

const route = useRoute();
const taskId = route.params.id;
const task = ref(null);
const glossary = ref([]);
const blocks = ref([]);
const logs = ref([]);
const tab = ref('overview');
const termSearch = ref('');
const scale = ref(1.1);
const pdfRefresh = ref(0);
const comparisonPdfExists = ref(false);
const pdfCompareEl = ref(null);
const isPdfFullscreen = ref(false);
const blockEditorVisible = ref(false);
const editingBlockId = ref('');
const blockForm = ref({ source_text: '', translated_text: '', status: 'completed' });
let timer;
const termTypes = ['technical_term', 'model_name', 'dataset_name', 'metric', 'abbreviation', 'do_not_translate', 'custom'];

const progress = computed(() => {
  if (!task.value?.total_blocks) return task.value?.translated_pdf_path ? 100 : 0;
  return Math.round((task.value.translated_blocks / task.value.total_blocks) * 100);
});
const comparisonPdfUrl = computed(() => (comparisonPdfExists.value ? `/tasks/${taskId}/pdf/comparison` : ''));
const filteredTerms = computed(() => {
  const q = termSearch.value.trim().toLowerCase();
  if (!q) return glossary.value;
  return glossary.value.filter((term) => `${term.source_term} ${term.target_term} ${term.term_type}`.toLowerCase().includes(q));
});
const logText = computed(() => logs.value.map((log) => `[${log.created_at}] ${log.level} ${log.module}: ${log.message}`).join('\n\n'));

function statusType(status) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'warning';
  if (status === 'translating' || status?.startsWith('compiling') || status === 'extracting') return 'primary';
  return 'info';
}

async function load() {
  const [taskRes, glossaryRes, blockRes, logRes, comparisonRes] = await Promise.all([
    api.get(`/tasks/${taskId}`),
    api.get(`/tasks/${taskId}/glossary`),
    api.get(`/tasks/${taskId}/blocks`),
    api.get(`/tasks/${taskId}/logs`),
    api.get(`/tasks/${taskId}/pdf/comparison/status`)
  ]);
  task.value = taskRes.data;
  glossary.value = glossaryRes.data;
  blocks.value = blockRes.data;
  logs.value = logRes.data;
  comparisonPdfExists.value = comparisonRes.data.exists;
}

async function uploadZip({ file }) {
  const form = new FormData();
  form.append('file', file);
  await api.post(`/tasks/${taskId}/upload`, form);
  ElMessage.success('上传成功，已开始编译英文 PDF');
  await load();
}

async function queue(endpoint) {
  await api.post(`/tasks/${taskId}${endpoint}`);
  ElMessage.success('任务已加入后台队列');
  await load();
}

async function generateComparisonPdf() {
  await api.post(`/tasks/${taskId}/generate-comparison-pdf`);
  comparisonPdfExists.value = false;
  ElMessage.success('对照 PDF 已加入后台队列');
  await load();
}

async function addTerm() {
  const { data } = await api.post(`/tasks/${taskId}/glossary`, {
    source_term: 'new term',
    target_term: '新术语',
    term_type: 'custom',
    frequency: 1,
    context: '',
    is_locked: false
  });
  glossary.value.unshift(data);
}

async function saveTerm(row) {
  await api.put(`/tasks/${taskId}/glossary/${row.id}`, row);
}

async function removeTerm(id) {
  await api.delete(`/tasks/${taskId}/glossary/${id}`);
  await load();
}

async function importTerms({ file }) {
  const form = new FormData();
  form.append('file', file);
  await api.post(`/tasks/${taskId}/glossary/import`, form);
  await load();
}

async function retranslate(blockId) {
  await api.post(`/tasks/${taskId}/blocks/${blockId}/retranslate`);
  ElMessage.success('已加入重译队列');
}

function openBlockEditor(row) {
  editingBlockId.value = row.id;
  blockForm.value = {
    source_text: row.source_text || '',
    translated_text: row.translated_text || '',
    status: row.status === 'completed' || row.status === 'failed' || row.status === 'pending' ? row.status : 'completed'
  };
  blockEditorVisible.value = true;
}

async function saveBlockEdit() {
  await api.put(`/tasks/${taskId}/blocks/${editingBlockId.value}`, {
    translated_text: blockForm.value.translated_text,
    status: blockForm.value.status
  });
  blockEditorVisible.value = false;
  ElMessage.success('翻译块已保存');
  await load();
}

function download(endpoint) {
  window.open(`/api/tasks/${taskId}${endpoint}?token=${localStorage.getItem('token')}`, '_blank');
}

async function togglePdfFullscreen() {
  const target = pdfCompareEl.value;
  if (!target) return;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await target.requestFullscreen();
    }
  } catch {
    ElMessage.error('当前浏览器不允许进入全屏');
  }
}

function updateFullscreenState() {
  isPdfFullscreen.value = document.fullscreenElement === pdfCompareEl.value;
}

onMounted(() => {
  load();
  timer = setInterval(load, 3500);
  document.addEventListener('fullscreenchange', updateFullscreenState);
});
onUnmounted(() => {
  clearInterval(timer);
  document.removeEventListener('fullscreenchange', updateFullscreenState);
});
</script>

<style scoped>
h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.pdf-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.comparison-grid {
  grid-template-columns: minmax(0, 1fr);
}

.pdf-placeholder {
  min-height: 520px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  background: #f8fafc;
}

.pdf-compare {
  min-height: 0;
}

.pdf-compare.is-fullscreen {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 12px;
  background: #f3f4f6;
}

.pdf-compare.is-fullscreen .pdf-toolbar {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.pdf-compare.is-fullscreen .pdf-grid {
  flex: 1 1 auto;
  min-height: 0;
}

.pdf-compare.is-fullscreen .pdf-placeholder {
  flex: 1 1 auto;
  min-height: 0;
}

.pdf-compare.is-fullscreen .pdf-grid :deep(.pdf-pane) {
  min-height: 0;
}

.pdf-compare.is-fullscreen .pdf-grid :deep(.pdf-frame) {
  height: auto;
  min-height: 0;
}

.pdf-scale {
  width: 220px;
}

.block-preview {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

@media (max-width: 980px) {
  .pdf-grid {
    grid-template-columns: 1fr;
  }
}
</style>
