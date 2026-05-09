<template>
  <div>
    <!-- 步骤条 -->
    <div class="steps-bar panel">
      <el-steps :active="currentStepIndex" align-center finish-status="success" process-status="process">
        <el-step title="上传" :status="stepStatus(0)" />
        <el-step title="编译英文" :status="stepStatus(1)" />
        <el-step title="提取术语" :status="stepStatus(2)" />
        <el-step title="审阅术语" :status="stepStatus(3)" />
        <el-step title="翻译" :status="stepStatus(4)" />
        <el-step title="编译中文" :status="stepStatus(5)" />
        <el-step title="完成" :status="stepStatus(6)" />
      </el-steps>
    </div>

    <!-- 错误横幅 -->
    <el-alert
      v-if="task && (task.status === 'failed' || task.failed_blocks)"
      :title="errorBannerTitle"
      :type="task.status === 'failed' ? 'error' : 'warning'"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    >
      <template v-if="task.failed_blocks && task.status !== 'failed'">
        有 {{ task.failed_blocks }} 个翻译块失败。
        <el-button size="small" type="warning" @click="queue('/retry-failed-blocks')">重试失败块</el-button>
      </template>
      <template v-else-if="task.status === 'failed'">
        {{ task.error_message || '任务失败' }}
        <el-button size="small" type="primary" @click="queue('/retry-failed-blocks')">重试</el-button>
      </template>
    </el-alert>

    <!-- 页面标题 -->
    <div class="page-head">
      <div>
        <div class="title-edit-row">
          <el-input
            v-if="editingTaskName"
            v-model="taskNameDraft"
            class="task-name-input"
            size="large"
            maxlength="120"
            show-word-limit
            @keyup.enter="saveTaskName"
            @keyup.esc="cancelTaskNameEdit"
          />
          <h1 v-else>{{ task?.name || '任务详情' }}</h1>
          <template v-if="task">
            <el-button v-if="!editingTaskName" size="small" @click="startTaskNameEdit">修改名称</el-button>
            <template v-else>
              <el-button size="small" type="primary" :loading="savingTaskName" @click="saveTaskName">保存</el-button>
              <el-button size="small" @click="cancelTaskNameEdit">取消</el-button>
            </template>
          </template>
        </div>
        <div class="status-line" v-if="task">
          <el-tag :type="statusType(task.status)">{{ task.status }}</el-tag>
          <span class="muted">主文件：{{ task.main_tex_path || '未识别' }}</span>
          <span class="muted">
            进度：{{ task.translated_blocks }}/{{ task.total_blocks }}
            <template v-if="task.failed_blocks">（{{ task.failed_blocks }} 失败）</template>
          </span>
        </div>
      </div>
    </div>

    <el-progress v-if="task && task.total_blocks" :percentage="progress" :stroke-width="10" :color="progressColors" style="margin-bottom: 16px" />

    <el-tabs v-model="tab" class="panel">
      <!-- ==================== 概览 Tab ==================== -->
      <el-tab-pane label="概览" name="overview">
        <div class="grid-two">
          <div class="overview-card">
            <h3>任务状态</h3>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="任务 ID">{{ task?.id }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="statusType(task?.status)">{{ task?.status }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="总块数">{{ task?.total_blocks || '-' }}</el-descriptions-item>
              <el-descriptions-item label="已完成">{{ task?.translated_blocks || 0 }}
                <template v-if="task?.total_blocks">（{{ Math.round((task.translated_blocks / task.total_blocks) * 100) }}%）</template>
              </el-descriptions-item>
              <el-descriptions-item label="待翻译">{{ task?.pending_blocks ?? ((task?.total_blocks || 0) - (task?.translated_blocks || 0) - (task?.failed_blocks || 0)) }}</el-descriptions-item>
              <el-descriptions-item label="失败">{{ task?.failed_blocks || 0 }}</el-descriptions-item>
              <el-descriptions-item label="错误">{{ task?.error_message || '无' }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <div class="overview-card">
            <h3>操作指引</h3>
            <div class="action-grid">
              <div class="action-group">
                <div class="action-label">1. 上传 LaTeX 项目</div>
                <el-upload
                  :show-file-list="false"
                  :http-request="uploadZip"
                  accept=".zip"
                  drag
                  class="upload-drag"
                >
                  <div class="upload-drop-area">
                    <Upload :size="28" class="upload-icon" />
                    <div>拖拽 .zip 文件到此处</div>
                    <div class="upload-hint">或点击选择文件</div>
                  </div>
                </el-upload>
                <div v-if="task?.main_tex_path" class="action-done">
                  <el-tag type="success" size="small">已上传：{{ task.main_tex_path }}</el-tag>
                </div>
              </div>

              <div class="action-group">
                <div class="action-label">2. 编译英文 PDF</div>
                <el-button :disabled="!task?.main_tex_path" @click="queue('/compile-original')">编译英文 PDF</el-button>
                <div v-if="task?.original_pdf_path" class="action-done"><el-tag type="success" size="small">已就绪</el-tag></div>
              </div>

              <div class="action-group">
                <div class="action-label">3. 提取术语表</div>
                <el-button
                  :disabled="!task?.original_pdf_path || task?.status === 'extracting'"
                  :loading="task?.status === 'extracting'"
                  @click="extractGlossary"
                >
                  提取术语
                </el-button>
                <div v-if="showGlossaryProgress" class="glossary-progress-panel compact">
                  <div class="glossary-progress-head">
                    <span>{{ glossaryProgressLabel }}</span>
                    <el-tag size="small" effect="plain">{{ glossaryProgress.status }}</el-tag>
                  </div>
                  <el-progress :percentage="glossaryProgressPercent" :stroke-width="8" />
                  <div class="muted">{{ glossaryProgress.message || '等待后台任务更新' }}</div>
                </div>
              </div>

              <div class="action-group">
                <div class="action-label">4. 审阅术语并开始翻译</div>
                <el-button type="primary" :disabled="!task?.total_blocks" @click="confirmTranslate">
                  开始翻译
                </el-button>
              </div>

              <div class="action-group">
                <div class="action-label">5. 编译与下载</div>
                <div class="toolbar">
                  <el-button :disabled="!task?.translated_blocks" @click="queue('/compile-translated')">编译中文 PDF</el-button>
                  <el-button :disabled="!task?.original_pdf_path" @click="download('/download/original-pdf')">英文 PDF</el-button>
                  <el-button :disabled="!task?.translated_pdf_path" @click="download('/download/translated-pdf')">中文 PDF</el-button>
                  <el-button :disabled="!comparisonPdfExists" @click="download('/download/comparison-pdf')">对照 PDF</el-button>
                  <el-button :disabled="!task?.translated_blocks" @click="download('/download/translated-project')">中文项目 zip</el-button>
                </div>
              </div>

              <div class="action-group">
                <div class="action-label">高级操作</div>
                <div class="toolbar">
                  <el-button type="warning" size="small" :disabled="!task?.failed_blocks" @click="queue('/retry-failed-blocks')">重试失败块</el-button>
                  <el-button size="small" @click="generateComparisonPdf">生成对照 PDF</el-button>
                  <el-popconfirm title="确定要取消此任务吗？所有进行中的操作将被中断。" @confirm="queue('/cancel')">
                    <template #reference><el-button size="small" type="danger">取消任务</el-button></template>
                  </el-popconfirm>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ==================== 术语库 Tab ==================== -->
      <el-tab-pane label="术语库" name="glossary">
        <div v-if="showGlossaryProgress" class="glossary-progress-panel">
          <div class="glossary-progress-head">
            <div>
              <div class="action-label">{{ glossaryProgressLabel }}</div>
              <div class="muted">{{ glossaryProgress.message || '等待后台任务更新' }}</div>
            </div>
            <el-tag size="small" effect="plain">{{ glossaryProgress.status }}</el-tag>
          </div>
          <el-progress :percentage="glossaryProgressPercent" :stroke-width="10" />
          <div class="glossary-progress-meta">
            <span>新增候选：{{ glossaryProgress.terms_count || 0 }}</span>
            <span>更新：{{ formatDateTime(glossaryProgress.updated_at) }}</span>
          </div>
          <div v-if="glossaryProgress.preview" class="llm-preview">
            <div class="llm-preview-title">LLM 实时响应</div>
            <pre ref="llmPreviewEl">{{ glossaryProgress.preview }}</pre>
          </div>
        </div>

        <el-empty v-if="!glossary.length && !termSearch" description="暂无术语，请先提取术语或手动添加">
          <el-button type="primary" @click="addTerm">新增术语</el-button>
        </el-empty>

        <template v-else>
          <el-alert
            v-if="glossaryConflicts.length"
            :title="'发现 ' + glossaryConflicts.length + ' 个术语冲突（同一英文对应多个中文译名）'"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 12px"
          >
            <template v-for="c in glossaryConflicts" :key="c.source_term">
              <el-tag size="small" style="margin-right:4px">{{ c.source_term }}</el-tag>
              <span class="muted">→ {{ (c.target_terms||[]).join(', ') }}</span>
              <br />
            </template>
          </el-alert>

          <div class="toolbar" style="margin-bottom:12px">
            <el-input v-model="termSearch" placeholder="搜索术语" style="width:220px" clearable />
            <el-button type="primary" @click="addTerm">新增术语</el-button>
            <el-button @click="importPreviewVisible = true">导入 JSON</el-button>
            <el-button @click="download('/glossary/export')">导出 JSON</el-button>
          </div>

          <el-table
            :data="filteredTerms"
            row-key="id"
            stripe
            border
            highlight-current-row
            max-height="520"
            class="glossary-table"
          >
            <template #empty>
              <el-empty description="没有匹配的术语" />
            </template>
            <el-table-column label="英文术语" min-width="160">
              <template #default="{ row }">
                <el-input
                  v-model="row.source_term"
                  size="small"
                  class="table-input"
                  @focus="markTermEditing(row.id)"
                  @input="markTermEditing(row.id)"
                  @blur="releaseTermEditing(row.id)"
                  @change="saveTerm(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="中文译名" min-width="160">
              <template #default="{ row }">
                <el-input
                  v-model="row.target_term"
                  size="small"
                  class="table-input"
                  @focus="markTermEditing(row.id)"
                  @input="markTermEditing(row.id)"
                  @blur="releaseTermEditing(row.id)"
                  @change="saveTerm(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="类型" width="180">
              <template #default="{ row }">
                <el-select
                  v-model="row.term_type"
                  size="small"
                  class="term-type-select"
                  @visible-change="(visible) => handleTermSelectVisible(row.id, visible)"
                  @change="saveTerm(row)"
                >
                  <el-option v-for="type in termTypes" :key="type" :label="type" :value="type" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="锁定" width="86" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.is_locked" size="small" @change="saveTerm(row)" />
              </template>
            </el-table-column>
            <el-table-column label="上下文" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="context-preview">{{ row.context || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="96" align="center">
              <template #default="{ row }">
                <el-popconfirm title="删除此术语？" @confirm="removeTerm(row.id)">
                  <template #reference><el-button size="small" type="danger" plain>删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- 导入预览对话框 -->
        <el-dialog v-model="importPreviewVisible" title="导入术语预览" width="700px" destroy-on-close>
          <el-upload
            :show-file-list="false"
            :http-request="previewImport"
            accept=".json"
            drag
            style="margin-bottom:16px"
          >
            <div class="upload-drop-area" style="padding:24px">
              <Upload :size="24" class="upload-icon" />
              <div>选择 JSON 文件预览</div>
            </div>
          </el-upload>
          <el-table v-if="importPreviewData.length" :data="importPreviewData" max-height="360" stripe>
            <el-table-column prop="source_term" label="英文术语" />
            <el-table-column prop="target_term" label="中文译名" />
            <el-table-column prop="term_type" label="类型" width="140" />
          </el-table>
          <el-empty v-else description="请先选择 JSON 文件" />
          <template #footer>
            <el-button @click="importPreviewVisible = false">取消</el-button>
            <el-button type="primary" :disabled="!importFile" @click="confirmImport">确认导入 ({{ importPreviewData.length }} 条)</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ==================== 翻译进度 Tab ==================== -->
      <el-tab-pane label="翻译进度" name="blocks">
        <div class="toolbar" style="margin-bottom:12px">
          <el-radio-group v-model="blockFilter" size="small">
            <el-radio-button value="all">全部 ({{ blocks.length }})</el-radio-button>
            <el-radio-button value="pending">待翻译 ({{ countByStatus('pending') }})</el-radio-button>
            <el-radio-button value="translating">翻译中 ({{ countByStatus('translating') }})</el-radio-button>
            <el-radio-button value="completed">已完成 ({{ countByStatus('completed') }})</el-radio-button>
            <el-radio-button value="failed">失败 ({{ countByStatus('failed') }})</el-radio-button>
          </el-radio-group>
          <el-button size="small" type="warning" :disabled="!selectedBlocks.length" @click="batchRetranslate">
            批量重译 ({{ selectedBlocks.length }})
          </el-button>
        </div>

        <el-table
          ref="blockTableRef"
          :data="filteredBlocks"
          stripe
          border
          highlight-current-row
          height="520"
          class="translation-block-table"
          @selection-change="onBlockSelection"
          row-key="id"
        >
          <template #empty>
            <el-empty description="没有匹配的翻译块" />
          </template>
          <el-table-column type="selection" width="46" align="center" reserve-selection />
          <el-table-column prop="block_index" label="#" width="64" align="center" />
          <el-table-column label="文件" min-width="170" show-overflow-tooltip>
            <template #default="{ row }"><span class="file-path-text">{{ row.file_path }}</span></template>
          </el-table-column>
          <el-table-column label="类型" width="120" align="center">
            <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.block_type }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="112" align="center">
            <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ blockStatusLabel(row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="原文" min-width="240">
            <template #default="{ row }">
              <el-popover placement="bottom" :width="520" trigger="hover">
                <template #reference>
                  <span class="block-preview source-preview">{{ row.source_text }}</span>
                </template>
                <div class="block-popover">{{ row.source_text }}</div>
              </el-popover>
            </template>
          </el-table-column>
          <el-table-column label="译文" min-width="240">
            <template #default="{ row }">
              <el-popover placement="bottom" :width="520" trigger="hover" v-if="row.translated_text">
                <template #reference>
                  <span class="block-preview target-preview">{{ row.translated_text }}</span>
                </template>
                <div class="block-popover">{{ row.translated_text }}</div>
              </el-popover>
              <span v-else class="empty-translation">未翻译</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="148" align="center" fixed="right">
            <template #default="{ row }">
              <div class="table-actions">
                <el-button size="small" type="primary" plain @click="openBlockEditor(row)">编辑</el-button>
                <el-button size="small" type="warning" plain @click="retranslate(row.id)">重译</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ==================== PDF 预览 Tab ==================== -->
      <el-tab-pane label="PDF 预览" name="pdf">
        <div ref="pdfCompareEl" class="pdf-panel" :class="{ 'is-fullscreen': isPdfFullscreen }">
          <div class="toolbar pdf-toolbar">
            <el-radio-group v-model="pdfSubTab">
              <el-radio-button value="comparison">对照</el-radio-button>
              <el-radio-button value="side">并排</el-radio-button>
            </el-radio-group>
            <div class="toolbar-spacer"></div>
            <template v-if="pdfSubTab === 'comparison'">
              <el-button type="primary" :disabled="!task?.original_pdf_path || !task?.translated_pdf_path" @click="generateComparisonPdf">生成/更新</el-button>
              <el-button :disabled="!comparisonPdfExists" @click="pdfRefresh++">刷新</el-button>
              <el-button :disabled="!comparisonPdfExists" @click="download('/download/comparison-pdf')">下载</el-button>
            </template>
            <template v-else>
              <el-button @click="pdfRefresh++">刷新</el-button>
            </template>
            <el-button @click="togglePdfFullscreen">
              <Minimize2 v-if="isPdfFullscreen" :size="18" />
              <Maximize2 v-else :size="18" />
            </el-button>
          </div>
          <template v-if="pdfSubTab === 'comparison'">
            <div v-if="comparisonPdfExists" class="pdf-grid comparison-grid">
              <PdfPane title="中英文对照 PDF" :url="comparisonPdfUrl" :refresh-key="pdfRefresh" :show-title="false" />
            </div>
            <div v-else class="pdf-placeholder">请先生成对照 PDF</div>
          </template>
          <template v-else>
            <div class="pdf-grid side-grid">
              <PdfPane title="英文 PDF" :url="originalPdfUrl" :refresh-key="pdfRefresh" />
              <PdfPane title="中文 PDF" :url="translatedPdfUrl" :refresh-key="pdfRefresh" />
            </div>
          </template>
        </div>
      </el-tab-pane>

      <!-- ==================== 日志 Tab ==================== -->
      <el-tab-pane label="日志" name="logs">
        <div class="toolbar" style="margin-bottom:10px">
          <el-select v-model="logLevel" placeholder="日志级别" style="width:130px" clearable size="small">
            <el-option label="全部" value="" />
            <el-option label="info" value="info" />
            <el-option label="warning" value="warning" />
            <el-option label="error" value="error" />
          </el-select>
          <el-input v-model="logSearch" placeholder="搜索日志" style="width:260px" clearable size="small" />
          <span class="muted">共 {{ filteredLogs.length }} 条</span>
        </div>
        <div class="log-box">{{ filteredLogText }}</div>
      </el-tab-pane>
    </el-tabs>

    <!-- 翻译块编辑对话框 -->
    <el-dialog v-model="blockEditorVisible" title="修改翻译块" width="900px" destroy-on-close>
      <div class="block-edit-grid">
        <div>
          <div class="block-edit-label">原文</div>
          <el-input v-model="blockForm.source_text" type="textarea" :rows="12" readonly />
        </div>
        <div>
          <div class="block-edit-label">译文</div>
          <el-input v-model="blockForm.translated_text" type="textarea" :rows="12" />
        </div>
      </div>
      <div style="margin-top:12px">
        <el-form-item label="状态">
          <el-select v-model="blockForm.status" style="width:180px">
            <el-option label="completed" value="completed" />
            <el-option label="pending" value="pending" />
            <el-option label="failed" value="failed" />
          </el-select>
        </el-form-item>
      </div>
      <template #footer>
        <el-button @click="blockEditorVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBlockEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  Maximize2, Minimize2, Upload
} from 'lucide-vue-next';
import { ElMessage, ElMessageBox } from 'element-plus';
import PdfPane from '../components/PdfPane.vue';
import { api } from '../api/client';

const route = useRoute();
const taskId = route.params.id;
const task = ref(null);
const glossary = ref([]);
const glossaryConflicts = ref([]);
const glossaryProgress = ref({ status: 'idle', message: '', percent: 0, preview: '', terms_count: 0, updated_at: null });
const blocks = ref([]);
const logs = ref([]);
const tab = ref('overview');
const termSearch = ref('');
const pdfRefresh = ref(0);
const comparisonPdfExists = ref(false);
const pdfCompareEl = ref(null);
const llmPreviewEl = ref(null);
const isPdfFullscreen = ref(false);
const blockEditorVisible = ref(false);
const editingBlockId = ref('');
const blockForm = ref({ source_text: '', translated_text: '', status: 'completed' });
const importPreviewVisible = ref(false);
const importPreviewData = ref([]);
const importFile = ref(null);
const pdfSubTab = ref('comparison');
const blockFilter = ref('all');
const selectedBlocks = ref([]);
const blockTableRef = ref(null);
const logLevel = ref('');
const logSearch = ref('');
const editingTaskName = ref(false);
const taskNameDraft = ref('');
const savingTaskName = ref(false);
let timer;
const termTypes = ['technical_term', 'model_name', 'dataset_name', 'metric', 'abbreviation', 'person_name', 'do_not_translate', 'custom'];
const termEditReleaseTimers = new Map();
const editingTermIds = new Set();
const savingTermIds = new Set();
const pinnedNewTermIds = [];
const glossaryReadonlyFields = new Set(['id', 'task_id', 'created_at', 'updated_at']);

const stepByStatus = {
  created: 0,
  uploaded: 1,
  compiling_original: 1,
  extracting: 2,
  waiting_glossary_review: 3,
  translating: 4,
  compiling_translated: 5,
  completed: 6,
};
const currentStepIndex = computed(() => {
  if (!task.value) return 0;
  return stepByStatus[task.value.status] ?? 0;
});
function stepStatus(index) {
  if (!task.value) return '';
  if (task.value.status === 'failed' || task.value.status === 'cancelled') {
    if (index < currentStepIndex.value) return 'error';
    if (index === currentStepIndex.value) return 'error';
    return '';
  }
  if (task.value.status === 'completed') return 'success';
  return '';
}

const errorBannerTitle = computed(() => {
  if (task.value?.status === 'failed') return task.value.error_message || '任务执行失败';
  if (task.value?.failed_blocks) return '有 ' + task.value.failed_blocks + ' 个翻译块翻译失败';
  return '';
});

const progress = computed(() => {
  if (!task.value?.total_blocks) return task.value?.translated_pdf_path ? 100 : 0;
  return Math.round((task.value.translated_blocks / task.value.total_blocks) * 100);
});
const progressColors = computed(() => {
  if (task.value?.failed_blocks) return '#e6a23c';
  return '#409eff';
});
const activeGlossaryProgressStatuses = new Set([
  'queued',
  'parsing_blocks',
  'preparing',
  'requesting_llm',
  'streaming',
  'parsing_json',
  'saving_terms',
  'fallback',
]);
const showGlossaryProgress = computed(() =>
  task.value?.status === 'extracting' || activeGlossaryProgressStatuses.has(glossaryProgress.value?.status)
);
const glossaryProgressPercent = computed(() => {
  const value = Number(glossaryProgress.value?.percent || 0);
  return Math.max(0, Math.min(100, Math.round(value)));
});
const glossaryProgressLabel = computed(() => {
  const labels = {
    queued: '术语提取排队中',
    parsing_blocks: '解析 LaTeX',
    preparing: '整理论文片段',
    requesting_llm: '请求 LLM',
    streaming: '接收 LLM 响应',
    parsing_json: '解析术语 JSON',
    saving_terms: '保存术语',
    fallback: '生成本地候选',
    completed: '术语提取完成',
    failed: '术语提取失败',
    idle: '术语提取',
  };
  return labels[glossaryProgress.value?.status] || '术语提取';
});
const comparisonPdfUrl = computed(() => (comparisonPdfExists.value ? '/tasks/' + taskId + '/pdf/comparison' : ''));
const originalPdfUrl = computed(() => (task.value?.original_pdf_path ? '/tasks/' + taskId + '/pdf/original' : ''));
const translatedPdfUrl = computed(() => (task.value?.translated_pdf_path ? '/tasks/' + taskId + '/pdf/translated' : ''));
const filteredTerms = computed(() => {
  const q = termSearch.value.trim().toLowerCase();
  if (!q) return glossary.value;
  return glossary.value.filter((term) =>
    (term.source_term + ' ' + term.target_term + ' ' + term.term_type).toLowerCase().includes(q)
  );
});
const filteredBlocks = computed(() => {
  if (blockFilter.value === 'all') return blocks.value;
  return blocks.value.filter((b) => b.status === blockFilter.value);
});
const filteredLogs = computed(() => {
  let list = logs.value;
  if (logLevel.value) list = list.filter((l) => l.level === logLevel.value);
  if (logSearch.value.trim()) {
    const q = logSearch.value.trim().toLowerCase();
    list = list.filter((l) => (l.message || '').toLowerCase().includes(q));
  }
  return list;
});
const filteredLogText = computed(() =>
  filteredLogs.value
    .map((log) => '[' + formatDateTime(log.created_at) + '] ' + log.level.toUpperCase() + ' ' + log.module + ': ' + log.message)
    .join('\n\n')
);

function formatDateTime(value) {
  if (!value) return '-';
  const raw = String(value);
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : raw + 'Z';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return raw.replace('T', ' ').replace(/\.\d+$/, '').slice(0, 19);
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).replace(/\//g, '-');
}

function countByStatus(status) {
  return blocks.value.filter((b) => b.status === status).length;
}

function statusType(status) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'warning';
  if (status === 'translating' || (status && status.startsWith('compiling')) || status === 'extracting') return 'primary';
  return 'info';
}

function blockStatusLabel(status) {
  const labels = {
    pending: '待翻译',
    translating: '翻译中',
    completed: '已完成',
    failed: '失败',
  };
  return labels[status] || status;
}

function pollInterval() {
  if (!task.value) return 5000;
  const s = task.value.status;
  if (s === 'translating') return 2000;
  if (s === 'extracting') return 1500;
  if (s === 'compiling_original' || s === 'compiling_translated') return 3000;
  if (tab.value === 'blocks') return 3000;
  return 8000;
}

function restartPolling() {
  clearInterval(timer);
  timer = setInterval(load, pollInterval());
}

function markTermEditing(termId) {
  if (termId == null) return;
  const timerId = termEditReleaseTimers.get(termId);
  if (timerId) {
    clearTimeout(timerId);
    termEditReleaseTimers.delete(termId);
  }
  editingTermIds.add(termId);
}

function releaseTermEditing(termId) {
  if (termId == null || savingTermIds.has(termId)) return;
  const timerId = termEditReleaseTimers.get(termId);
  if (timerId) clearTimeout(timerId);
  termEditReleaseTimers.set(
    termId,
    setTimeout(() => {
      if (!savingTermIds.has(termId)) editingTermIds.delete(termId);
      termEditReleaseTimers.delete(termId);
    }, 300)
  );
}

function handleTermSelectVisible(termId, visible) {
  if (visible) markTermEditing(termId);
  else releaseTermEditing(termId);
}

function isTermLocallyOwned(termId) {
  return editingTermIds.has(termId) || savingTermIds.has(termId);
}

function pinNewTerm(termId) {
  const index = pinnedNewTermIds.indexOf(termId);
  if (index !== -1) pinnedNewTermIds.splice(index, 1);
  pinnedNewTermIds.unshift(termId);
}

function unpinNewTerm(termId) {
  const index = pinnedNewTermIds.indexOf(termId);
  if (index !== -1) pinnedNewTermIds.splice(index, 1);
}

function mergeGlossaryFromServer(serverTerms) {
  const localById = new Map(glossary.value.map((term) => [term.id, term]));
  const mergedTerms = serverTerms.map((serverTerm) => {
    const localTerm = localById.get(serverTerm.id);
    if (!localTerm || !isTermLocallyOwned(serverTerm.id)) return serverTerm;

    for (const [key, value] of Object.entries(serverTerm)) {
      if (glossaryReadonlyFields.has(key)) localTerm[key] = value;
    }
    return localTerm;
  });
  const mergedById = new Map(mergedTerms.map((term) => [term.id, term]));
  const pinnedTerms = pinnedNewTermIds.map((termId) => mergedById.get(termId)).filter(Boolean);
  const pinnedIds = new Set(pinnedTerms.map((term) => term.id));
  glossary.value = [...pinnedTerms, ...mergedTerms.filter((term) => !pinnedIds.has(term.id))];
}

function glossaryPayload(row) {
  return {
    source_term: row.source_term,
    target_term: row.target_term,
    term_type: row.term_type,
    frequency: row.frequency,
    context: row.context,
    is_locked: row.is_locked,
  };
}

async function load() {
  const prevStatus = task.value?.status;
  const [taskRes, glossaryRes, blockRes, logRes, comparisonRes, conflictsRes, glossaryProgressRes] = await Promise.all([
    api.get('/tasks/' + taskId),
    api.get('/tasks/' + taskId + '/glossary'),
    api.get('/tasks/' + taskId + '/blocks'),
    api.get('/tasks/' + taskId + '/logs'),
    api.get('/tasks/' + taskId + '/pdf/comparison/status'),
    api.get('/tasks/' + taskId + '/glossary/conflicts').catch(() => ({ data: [] })),
    api.get('/tasks/' + taskId + '/glossary/progress').catch(() => ({ data: glossaryProgress.value })),
  ]);
  task.value = taskRes.data;
  mergeGlossaryFromServer(glossaryRes.data);
  blocks.value = blockRes.data;
  logs.value = logRes.data;
  comparisonPdfExists.value = comparisonRes.data.exists;
  glossaryConflicts.value = conflictsRes.data || [];
  glossaryProgress.value = glossaryProgressRes.data || glossaryProgress.value;

  if (prevStatus && prevStatus !== taskRes.data.status) {
    const labels = {
      compiling_original: '英文 PDF 编译中',
      extracting: '术语提取中',
      waiting_glossary_review: '术语已提取，请审阅',
      translating: '翻译中',
      compiling_translated: '中文 PDF 编译中',
      completed: '任务完成',
      failed: '任务失败',
    };
    const label = labels[taskRes.data.status];
    if (label) {
      ElMessage({ message: '状态更新：' + label, type: taskRes.data.status === 'failed' ? 'error' : 'success', duration: 4000 });
    }
  }

  restartPolling();
}

async function uploadZip({ file }) {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/tasks/' + taskId + '/upload', form);
  ElMessage.success('上传成功，已开始编译英文 PDF');
  if (data.main_candidates?.length) {
    ElMessage.info('检测到主文件候选：' + data.main_candidates.join(', '));
  }
  await load();
}

function startTaskNameEdit() {
  taskNameDraft.value = task.value?.name || '';
  editingTaskName.value = true;
}

function cancelTaskNameEdit() {
  editingTaskName.value = false;
  taskNameDraft.value = '';
}

async function saveTaskName() {
  const name = taskNameDraft.value.trim();
  if (!name) {
    ElMessage.warning('任务名称不能为空');
    return;
  }
  if (name === task.value?.name) {
    cancelTaskNameEdit();
    return;
  }
  savingTaskName.value = true;
  try {
    const { data } = await api.patch('/tasks/' + taskId, { name });
    task.value = data;
    editingTaskName.value = false;
    ElMessage.success('任务名称已更新');
  } finally {
    savingTaskName.value = false;
  }
}

async function confirmTranslate() {
  if (!glossary.value.length) {
    try {
      await ElMessageBox.confirm('尚未提取术语，是否直接开始翻译？LLM 将不使用术语库。', '提示', {
        confirmButtonText: '直接翻译',
        cancelButtonText: '先去提取术语',
        type: 'warning',
      });
    } catch {
      return;
    }
  }
  await queue('/start-translation');
}

async function extractGlossary() {
  glossaryProgress.value = {
    status: 'queued',
    message: '术语提取已加入后台队列',
    percent: 1,
    preview: '',
    terms_count: 0,
    updated_at: new Date().toISOString(),
  };
  await queue('/extract-glossary');
}

async function queue(endpoint) {
  await api.post('/tasks/' + taskId + endpoint);
  ElMessage.success('任务已加入后台队列');
  await load();
}

async function generateComparisonPdf() {
  await api.post('/tasks/' + taskId + '/generate-comparison-pdf');
  comparisonPdfExists.value = false;
  ElMessage.success('对照 PDF 生成已加入后台队列');
  await load();
}

async function addTerm() {
  const { data } = await api.post('/tasks/' + taskId + '/glossary', {
    source_term: 'new term',
    target_term: '新术语',
    term_type: 'custom',
    frequency: 1,
    context: '',
    is_locked: false,
  });
  pinNewTerm(data.id);
  markTermEditing(data.id);
  glossary.value.unshift(data);
}

async function saveTerm(row) {
  markTermEditing(row.id);
  savingTermIds.add(row.id);
  let saved = false;
  try {
    await api.put('/tasks/' + taskId + '/glossary/' + row.id, glossaryPayload(row));
    saved = true;
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '术语保存失败，请重试');
  } finally {
    savingTermIds.delete(row.id);
    if (saved) {
      unpinNewTerm(row.id);
      releaseTermEditing(row.id);
    }
  }
}

async function removeTerm(id) {
  await api.delete('/tasks/' + taskId + '/glossary/' + id);
  unpinNewTerm(id);
  editingTermIds.delete(id);
  savingTermIds.delete(id);
  glossary.value = glossary.value.filter((t) => t.id !== id);
  ElMessage.success('术语已删除');
}

async function previewImport({ file }) {
  try {
    const text = await file.text();
    importPreviewData.value = JSON.parse(text);
    importFile.value = file;
  } catch {
    ElMessage.error('无法解析 JSON 文件');
  }
}

async function confirmImport() {
  if (!importFile.value) return;
  const form = new FormData();
  form.append('file', importFile.value);
  await api.post('/tasks/' + taskId + '/glossary/import', form);
  ElMessage.success('已导入 ' + importPreviewData.value.length + ' 条术语');
  importPreviewVisible.value = false;
  importPreviewData.value = [];
  importFile.value = null;
  await load();
}

async function retranslate(blockId) {
  await api.post('/tasks/' + taskId + '/blocks/' + blockId + '/retranslate');
  ElMessage.success('已加入重译队列');
  await load();
}

function onBlockSelection(val) {
  selectedBlocks.value = val;
}

async function batchRetranslate() {
  if (!selectedBlocks.value.length) return;
  try {
    await ElMessageBox.confirm(
      '确定要重译选中的 ' + selectedBlocks.value.length + ' 个翻译块吗？',
      '批量重译',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    );
  } catch {
    return;
  }
  const ids = selectedBlocks.value.map((b) => b.id);
  await api.post('/tasks/' + taskId + '/blocks/batch-retranslate', ids);
  ElMessage.success('已加入 ' + ids.length + ' 个块的重译队列');
  selectedBlocks.value = [];
  await load();
}

function openBlockEditor(row) {
  editingBlockId.value = row.id;
  blockForm.value = {
    source_text: row.source_text || '',
    translated_text: row.translated_text || '',
    status: row.status || 'completed',
  };
  blockEditorVisible.value = true;
}

async function saveBlockEdit() {
  await api.put('/tasks/' + taskId + '/blocks/' + editingBlockId.value, {
    translated_text: blockForm.value.translated_text,
    status: blockForm.value.status,
  });
  blockEditorVisible.value = false;
  ElMessage.success('翻译块已保存');
  await load();
}

function download(endpoint) {
  window.open('/api/tasks/' + taskId + endpoint + '?token=' + localStorage.getItem('token'), '_blank');
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

watch(
  () => glossaryProgress.value?.preview,
  async () => {
    await nextTick();
    if (llmPreviewEl.value) {
      llmPreviewEl.value.scrollTop = llmPreviewEl.value.scrollHeight;
    }
  }
);

onMounted(() => {
  load();
  timer = setInterval(load, pollInterval());
  document.addEventListener('fullscreenchange', updateFullscreenState);
});
onUnmounted(() => {
  clearInterval(timer);
  termEditReleaseTimers.forEach((timerId) => clearTimeout(timerId));
  termEditReleaseTimers.clear();
  document.removeEventListener('fullscreenchange', updateFullscreenState);
});
</script>

<style scoped>
.steps-bar {
  margin-bottom: 16px;
}

.overview-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
}
.overview-card h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.title-edit-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-name-input {
  width: min(560px, 70vw);
}

.action-grid {
  display: grid;
  gap: 16px;
}
.action-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.action-label {
  font-weight: 600;
  font-size: 14px;
  color: #374151;
}
.action-done {
  display: flex;
  align-items: center;
  gap: 6px;
}

.glossary-progress-panel {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid #d8e6f8;
  border-radius: 8px;
  background: #f7fbff;
}

.glossary-progress-panel.compact {
  margin-bottom: 0;
}

.glossary-progress-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.glossary-progress-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  color: #64748b;
  font-size: 12px;
}

.llm-preview {
  border-top: 1px solid #dbe7f5;
  padding-top: 10px;
}

.llm-preview-title {
  margin-bottom: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
}

.llm-preview pre {
  max-height: 220px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.upload-drag {
  width: 100%;
}
.upload-drag :deep(.el-upload-dragger) {
  width: 100%;
  padding: 18px 0;
}
.upload-drop-area {
  text-align: center;
  color: #6b7280;
}
.upload-icon {
  color: #9ca3af;
  margin-bottom: 4px;
}
.upload-hint {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
}

.pdf-panel {
  min-height: 0;
}
.pdf-toolbar {
  justify-content: flex-end;
  padding: 8px 0 10px;
  margin-top: 6px;
  border-bottom: 1px solid #e5e7eb;
}
.toolbar-spacer {
  flex: 1;
}
.pdf-toolbar .el-button {
  margin-left: 0;
}
.pdf-panel.is-fullscreen {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 12px;
  background: #f3f4f6;
}
.pdf-panel.is-fullscreen .pdf-toolbar {
  flex: 0 0 auto;
  margin-bottom: 12px;
}
.pdf-panel.is-fullscreen .pdf-grid {
  flex: 1 1 auto;
  min-height: 0;
}
.pdf-panel.is-fullscreen .pdf-placeholder {
  flex: 1 1 auto;
  min-height: 0;
}

.pdf-grid {
  display: grid;
  gap: 12px;
}
.comparison-grid {
  grid-template-columns: minmax(0, 1fr);
}
.side-grid {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
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

.block-preview {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
  cursor: default;
}

.source-preview {
  color: #334155;
}

.target-preview {
  color: #1f4f46;
}

.empty-translation {
  color: #94a3b8;
  font-size: 13px;
}

.table-actions {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.block-popover {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  max-height: 360px;
  overflow: auto;
  font-size: 13px;
}

.block-edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.block-edit-label {
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 14px;
}

.term-type-select {
  width: 100%;
}

.glossary-table {
  border-radius: 8px;
  overflow: hidden;
}

.glossary-table :deep(.el-table__header th) {
  background: #f8fafc;
  color: #374151;
  font-weight: 700;
}

.glossary-table :deep(.el-table__cell) {
  padding: 10px 0;
}

.glossary-table :deep(.el-table__row:hover .el-input__wrapper),
.glossary-table :deep(.el-table__row:hover .el-select__wrapper) {
  box-shadow: 0 0 0 1px #c6e2ff inset;
}

.translation-block-table {
  border-radius: 8px;
  overflow: hidden;
}

.translation-block-table :deep(.el-table__header th) {
  background: #f8fafc;
  color: #374151;
  font-weight: 700;
}

.translation-block-table :deep(.el-table__cell) {
  padding: 10px 0;
}

.translation-block-table :deep(.el-table__row:hover .block-preview) {
  color: #1558b0;
}

.file-path-text {
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.table-input :deep(.el-input__wrapper),
.term-type-select :deep(.el-select__wrapper) {
  background: #fbfdff;
}

.context-preview {
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
}

@media (max-width: 860px) {
  .side-grid {
    grid-template-columns: 1fr;
  }
  .block-edit-grid {
    grid-template-columns: 1fr;
  }
}
</style>
