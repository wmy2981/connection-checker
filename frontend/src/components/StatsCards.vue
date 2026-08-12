<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NStatistic } from 'naive-ui'

import type { StatsSummary } from '@/types'

const props = defineProps<{ stats: StatsSummary | null }>()

// 全部目标近 24h 综合可用率（由每目标 uptime_pct × uptime_total 反推成功数汇总）
const uptime = computed(() => {
  const list = props.stats?.target_status ?? []
  let total = 0
  let ok = 0
  for (const t of list) {
    if (t.uptime_total != null && t.uptime_pct != null) {
      total += t.uptime_total
      ok += Math.round((t.uptime_pct / 100) * t.uptime_total)
    }
  }
  return total ? ok / total : null
})

const uptimeText = computed(() => (uptime.value != null ? `${(uptime.value * 100).toFixed(1)}%` : '-'))

const rateClass = computed(() => {
  if (uptime.value == null) return ''
  if (uptime.value >= 0.999) return 'rate-ok'
  if (uptime.value >= 0.95) return 'rate-warn'
  return 'rate-bad'
})
</script>

<template>
  <div class="stats-grid">
    <n-card size="small">
      <n-statistic label="目标数" :value="stats?.total_targets ?? 0">
        <template #suffix>
          <span class="sub">启用 {{ stats?.enabled_targets ?? 0 }}</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic label="24h 可用率">
        <span :class="rateClass">{{ uptimeText }}</span>
        <template #suffix v-if="uptime != null">
          <span class="sub">全部目标</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic :label="`成功（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_success ?? 0">
        <template #suffix v-if="stats && stats.last_total_checks">
          <span class="sub">{{ Math.round((stats.last_success / stats.last_total_checks) * 100) }}%</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic :label="`失败（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_fail ?? 0">
        <template #suffix v-if="stats && stats.last_total_checks">
          <span class="sub">{{ Math.round((stats.last_fail / stats.last_total_checks) * 100) }}%</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic :label="`超时（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_timeout ?? 0">
        <template #suffix v-if="stats && stats.last_total_checks">
          <span class="sub">{{ Math.round((stats.last_timeout / stats.last_total_checks) * 100) }}%</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic :label="`错误（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_error ?? 0">
        <template #suffix v-if="stats && stats.last_total_checks">
          <span class="sub">{{ Math.round((stats.last_error / stats.last_total_checks) * 100) }}%</span>
        </template>
      </n-statistic>
    </n-card>
  </div>
</template>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
.sub {
  font-size: 12px;
  color: var(--cc-text-3);
  margin-left: 4px;
}
.rate-ok {
  color: #0ca30c;
}
.rate-warn {
  color: #fab219;
}
.rate-bad {
  color: #d03b3b;
}
</style>
