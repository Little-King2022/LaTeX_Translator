<template>
  <div class="pdf-pane">
    <div class="pdf-title">{{ title }}</div>
    <iframe
      v-if="viewerUrl"
      ref="frameEl"
      class="pdf-frame"
      :src="viewerUrl"
      :title="title"
      @load="loading = false"
    />
    <div v-else class="pdf-state">PDF 尚不可用</div>
    <div v-if="loading && viewerUrl" class="pdf-loading">加载中</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';

const props = defineProps({
  title: String,
  url: String,
  scale: Number,
  refreshKey: Number
});
const emit = defineEmits(['scroll']);
const frameEl = ref(null);
const loading = ref(false);

const viewerUrl = computed(() => {
  if (!props.url) return '';
  const token = localStorage.getItem('token');
  const apiUrl = props.url.startsWith('/api/') ? props.url : `/api${props.url}`;
  const url = new URL(apiUrl, window.location.origin);
  if (token) url.searchParams.set('token', token);
  url.searchParams.set('preview', props.title || 'pdf');
  url.searchParams.set('v', String(props.refreshKey || 0));
  const zoom = Math.round((props.scale || 1) * 100);
  return `${url.pathname}${url.search}#zoom=${zoom}`;
});

function setScrollTop(value) {
  try {
    frameEl.value?.contentWindow?.scrollTo({ top: value });
  } catch {
    // Browser-native PDF viewers do not expose a reliable scroll API.
  }
}

function scrollRatio() {
  return 0;
}

function applyRatio(ratio) {
  setScrollTop(ratio);
}

watch(viewerUrl, () => {
  loading.value = !!viewerUrl.value;
  emit('scroll', {});
}, { immediate: true });
defineExpose({ setScrollTop, scrollRatio, applyRatio });
</script>

<style scoped>
.pdf-pane {
  position: relative;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid #d9dee7;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.pdf-title {
  flex: 0 0 auto;
  height: 42px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  border-bottom: 1px solid #d9dee7;
  font-weight: 600;
}

.pdf-frame {
  flex: 1 1 auto;
  width: 100%;
  height: calc(100vh - 244px);
  min-height: 520px;
  border: 0;
  background: #e5e7eb;
}

.pdf-state {
  flex: 1 1 auto;
  min-height: 520px;
  color: #4b5563;
  text-align: center;
  padding: 42px 0;
}

.pdf-loading {
  position: absolute;
  right: 12px;
  bottom: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(17, 24, 39, 0.78);
  color: #fff;
  font-size: 13px;
}
</style>
