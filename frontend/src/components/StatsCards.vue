<script setup lang="ts">
import { NCard, NStatistic } from 'naive-ui'

import type { StatsSummary } from '@/types'

defineProps<{ stats: StatsSummary | null }>()
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
      <n-statistic :label="`成功（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_success ?? 0" />
    </n-card>
    <n-card size="small">
      <n-statistic :label="`失败（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_fail ?? 0">
        <template #suffix v-if="stats && stats.last_total_checks">
          <span class="sub">{{ Math.round((stats.last_fail / stats.last_total_checks) * 100) }}%</span>
        </template>
      </n-statistic>
    </n-card>
    <n-card size="small">
      <n-statistic :label="`超时（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_timeout ?? 0" />
    </n-card>
    <n-card size="small">
      <n-statistic :label="`错误（近${stats?.stats_window ?? 50}次）`" :value="stats?.last_error ?? 0" />
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
</style>
