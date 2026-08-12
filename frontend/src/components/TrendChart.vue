<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TrendBucket } from '@/types'

const props = defineProps<{ buckets: TrendBucket[] }>()

const W = 620
const H = 220
const PAD = { top: 16, right: 12, bottom: 26, left: 42 }

const plotW = W - PAD.left - PAD.right
const plotH = H - PAD.top - PAD.bottom

const points = computed(() =>
  props.buckets.map((b) => {
    const rate = b.total > 0 ? (b.success / b.total) * 100 : null
    return { bucket: b, rate }
  }),
)

function xAt(i: number): number {
  const n = points.value.length
  return n <= 1 ? PAD.left + plotW / 2 : PAD.left + (i / (n - 1)) * plotW
}

function yAt(rate: number): number {
  return PAD.top + (1 - rate / 100) * plotH
}

const linePath = computed(() => {
  const pts = points.value
  let d = ''
  let pen = false
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i]
    if (p.rate === null) {
      pen = false
      continue
    }
    const x = xAt(i)
    const y = yAt(p.rate)
    d += pen ? ` L ${x.toFixed(1)} ${y.toFixed(1)}` : ` M ${x.toFixed(1)} ${y.toFixed(1)}`
    pen = true
  }
  return d.trim()
})

const areaPath = computed(() => {
  const pts = points.value
  if (!linePath.value) return ''
  let lastX = PAD.left
  for (let i = pts.length - 1; i >= 0; i--) {
    if (pts[i].rate !== null) {
      lastX = xAt(i)
      break
    }
  }
  const bottom = PAD.top + plotH
  return `${linePath.value} L ${lastX.toFixed(1)} ${bottom} L ${PAD.left} ${bottom} Z`
})

const grid = [0, 25, 50, 75, 100]

const hoverIndex = ref(-1)
const hoverX = ref(0)
const hoverY = ref(0)
const tooltipLeft = ref(0)
const tooltipTop = ref(0)

// 桶形如 "2026-08-08T05:00"（小时）或 "2026-08-08"（天），是后端按容器时区
// 聚合的本地时间，直接取分量显示，避免 new Date() 按浏览器时区二次换算。
function fmtShort(bucket: string): string {
  return bucket.length <= 10 ? bucket.slice(5) : bucket.slice(11, 16)
}

function fmtTime(bucket: string): string {
  if (bucket.length <= 10) return bucket
  const m = Number(bucket.slice(5, 7))
  const d = bucket.slice(8, 10)
  const hh = bucket.slice(11, 13)
  return `${m}/${d} ${hh}:00`
}

function onMove(ev: MouseEvent) {
  const svg = ev.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const n = points.value.length
  if (!n) return
  const px = ((ev.clientX - rect.left) / rect.width) * W
  const raw = Math.round(((px - PAD.left) / plotW) * (n - 1))
  const i = Math.max(0, Math.min(n - 1, raw))
  hoverIndex.value = i
  hoverX.value = xAt(i)
  const p = points.value[i]
  hoverY.value = p.rate !== null ? yAt(p.rate) : PAD.top
  tooltipLeft.value = ev.clientX - rect.left
  tooltipTop.value = hoverY.value * (rect.height / H)
}

function onLeave() {
  hoverIndex.value = -1
}

const hoverPoint = computed(() => {
  const i = hoverIndex.value
  if (i < 0 || i >= points.value.length) return null
  return { bucket: points.value[i].bucket, rate: points.value[i].rate }
})

const xLabels = computed(() => {
  const n = points.value.length
  // 数据点少（如 7 天视图）时全量显示标签，避免间隔跳号
  const step = n <= 7 ? 1 : Math.max(1, Math.ceil(n / 6))
  const labels: { x: number; text: string }[] = []
  for (let i = 0; i < n; i += step) {
    labels.push({ x: xAt(i), text: fmtShort(props.buckets[i].bucket) })
  }
  return labels
})
</script>

<template>
  <div class="trend">
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      class="trend-svg"
      role="img"
      :aria-label="`近 ${buckets.length} 小时检查成功率趋势`"
      @mousemove="onMove"
      @mouseleave="onLeave"
    >
      <g v-for="v in grid" :key="v">
        <line :x1="PAD.left" :x2="W - PAD.right" :y1="yAt(v)" :y2="yAt(v)" class="grid-line" />
        <text :x="PAD.left - 6" :y="yAt(v) + 3" class="axis-label" text-anchor="end">{{ v }}%</text>
      </g>
      <line :x1="PAD.left" :x2="W - PAD.right" :y1="PAD.top + plotH" :y2="PAD.top + plotH" class="baseline" />
      <path v-if="areaPath" :d="areaPath" class="trend-area" />
      <path v-if="linePath" :d="linePath" class="trend-line" fill="none" />
      <g v-for="lab in xLabels" :key="lab.x">
        <text :x="lab.x" :y="H - 6" class="axis-label" text-anchor="middle">{{ lab.text }}</text>
      </g>
      <g v-if="hoverIndex >= 0">
        <line :x1="hoverX" :x2="hoverX" :y1="PAD.top" :y2="PAD.top + plotH" class="crosshair" />
        <circle :cx="hoverX" :cy="hoverY" r="4" class="hover-dot" />
      </g>
    </svg>

    <div
      v-if="hoverPoint"
      class="tooltip"
      :style="{ left: tooltipLeft + 'px', top: tooltipTop + 'px' }"
    >
      <div class="tt-time">{{ fmtTime(hoverPoint.bucket.bucket) }}</div>
      <div class="tt-row">
        成功率
        <b>{{ hoverPoint.rate !== null ? hoverPoint.rate.toFixed(1) + '%' : '—' }}</b>
      </div>
      <div class="tt-row">总检查 <b>{{ hoverPoint.bucket.total }}</b></div>
      <div class="tt-row"><span class="dot dot-good"></span>成功 {{ hoverPoint.bucket.success }}</div>
      <div class="tt-row"><span class="dot dot-critical"></span>失败 {{ hoverPoint.bucket.fail }}</div>
      <div class="tt-row"><span class="dot dot-warning"></span>超时 {{ hoverPoint.bucket.timeout }}</div>
      <div class="tt-row"><span class="dot dot-serious"></span>错误 {{ hoverPoint.bucket.error }}</div>
      <div v-if="hoverPoint.bucket.avg_latency_ms != null" class="tt-row">
        平均延迟 <b>{{ hoverPoint.bucket.avg_latency_ms }}ms</b>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trend {
  position: relative;
  width: 100%;
}
.trend-svg {
  width: 100%;
  height: auto;
  display: block;
  touch-action: none;
}
.grid-line {
  stroke: var(--cc-panel-border);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.baseline {
  stroke: var(--cc-text-3);
  stroke-width: 1;
}
.axis-label {
  font-size: 10px;
  fill: var(--cc-text-3);
}
.trend-area {
  fill: rgba(12, 163, 12, 0.1);
}
.trend-line {
  stroke: #0ca30c;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.crosshair {
  stroke: var(--cc-text-3);
  stroke-width: 1;
  stroke-dasharray: 2 2;
}
.hover-dot {
  fill: #0ca30c;
  stroke: var(--cc-bg);
  stroke-width: 2;
}
.tooltip {
  position: absolute;
  transform: translate(-50%, -115%);
  background: var(--cc-hover);
  border: 1px solid var(--cc-panel-border);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
  z-index: 5;
}
.tt-time {
  font-weight: 600;
  margin-bottom: 2px;
}
.tt-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot-good {
  background: #0ca30c;
}
.dot-critical {
  background: #d03b3b;
}
.dot-warning {
  background: #fab219;
}
.dot-serious {
  background: #ec835a;
}
</style>
