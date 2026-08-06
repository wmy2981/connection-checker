<script setup lang="ts">
import { NStatistic } from 'naive-ui'

import type { StatsSummary } from '@/types'

defineProps<{ stats: StatsSummary | null }>()
</script>

<template>
  <n-grid :cols="5" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
    <n-grid-item span="5 s:1 m:1">
      <n-card size="small">
        <n-statistic label="目标数" :value="stats?.total_targets ?? 0">
          <template #suffix>
            <span class="sub">启用 {{ stats?.enabled_targets ?? 0 }}</span>
          </template>
        </n-statistic>
      </n-card>
    </n-grid-item>
    <n-grid-item span="5 s:1 m:1">
      <n-card size="small">
        <n-statistic label="成功（近50次）" :value="stats?.last_success ?? 0" />
      </n-card>
    </n-grid-item>
    <n-grid-item span="5 s:1 m:1">
      <n-card size="small">
        <n-statistic label="失败（近50次）" :value="stats?.last_fail ?? 0">
          <template #suffix v-if="stats && stats.last_total_checks">
            <span class="sub">{{ Math.round((stats.last_fail / stats.last_total_checks) * 100) }}%</span>
          </template>
        </n-statistic>
      </n-card>
    </n-grid-item>
    <n-grid-item span="5 s:1 m:1">
      <n-card size="small">
        <n-statistic label="超时（近50次）" :value="stats?.last_timeout ?? 0" />
      </n-card>
    </n-grid-item>
    <n-grid-item span="5 s:1 m:1">
      <n-card size="small">
        <n-statistic label="错误（近50次）" :value="stats?.last_error ?? 0" />
      </n-card>
    </n-grid-item>
  </n-grid>
</template>

<style scoped>
.sub {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-left: 4px;
}
</style>
