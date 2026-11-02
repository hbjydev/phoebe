<script setup lang="ts">
import { onMounted, ref, useId, watch } from 'vue'
import { useData } from 'vitepress'

const props = defineProps<{ code: string }>()
const { isDark } = useData()
const id = `mermaid-${useId().replace(/[^a-zA-Z0-9-]/g, '-')}`
const svg = ref('')
const error = ref(false)

onMounted(() => {
  watch([() => props.code, isDark], async ([code, dark], _, onCleanup) => {
    let cancelled = false
    onCleanup(() => { cancelled = true })
    try {
      const { default: mermaid } = await import('mermaid')
      if (cancelled) return
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: dark ? 'dark' : 'default',
        suppressErrorRendering: true
      })
      const result = await mermaid.render(id, code)
      if (!cancelled) {
        svg.value = result.svg
        error.value = false
      }
    } catch (cause) {
      if (!cancelled) {
        svg.value = ''
        error.value = true
        console.error('Failed to render Mermaid diagram', cause)
      }
    }
  }, { immediate: true })
})
</script>

<template>
  <div class="mermaid-diagram">
    <p v-if="error" role="alert">The diagram did not load. Its source appears below.</p>
    <div v-if="svg" v-html="svg" />
    <pre v-else><code>{{ code }}</code></pre>
  </div>
</template>

<style scoped>
.mermaid-diagram {
  margin: 16px 0;
  overflow-x: auto;
}

.mermaid-diagram :deep(svg) {
  display: block;
  margin: 0 auto;
}
</style>
