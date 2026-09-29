<template>
  <section class="page" data-module="agreement">
    <header class="page-head">
      <div>
        <h2>保障协议管理</h2>
        <p class="page-desc">维护保障协议，围绕协议编号、服务单位、保障项目、协议金额做登记、筛选与状态流转；到期日期以后端为准，提前给出到期提醒与续签留痕。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记保障协议</button>
        <button class="btn" type="button" @click="exportRows">导出保障协议清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>协议状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="name in statuses" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="check-pill">
        <input v-model="onlyReminding" type="checkbox" @change="reload" />
        只看即将到期（{{ remindDays }} 天内）
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '到期提醒'">
              <span v-if="row['已逾期']" class="badge danger">{{ row[column] }}</span>
              <span v-else-if="row['即将到期']" class="badge warn">{{ row[column] }}</span>
              <template v-else>—</template>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openRenew(row)">确认续签</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保障协议数据，可先登记保障协议</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障协议记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="renewTarget" class="modal-mask" @click.self="closeRenew">
      <div class="modal-card" role="dialog" aria-modal="true">
        <h3 class="modal-title">确认续签：{{ renewTarget['协议编号'] }}</h3>
        <p class="modal-hint">
          原到期日期 {{ renewTarget['到期日期'] || '—' }} 与保障项目「{{ renewTarget['保障项目'] }}」将保留在续签记录中；
          同一协议编号重复续签只保留最新一次留痕。
        </p>
        <form @submit.prevent="submitRenew">
          <label>
            <span>签订日期 *</span>
            <input v-model="renewForm['签订日期']" type="date" required />
          </label>
          <label>
            <span>到期日期 *</span>
            <input v-model="renewForm['到期日期']" type="date" required />
          </label>
          <label style="grid-column: 1 / -1">
            <span>服务期限 *</span>
            <input v-model="renewForm['服务期限']" placeholder="如：2026-10-01 至 2027-09-30" required />
          </label>
          <label>
            <span>协议金额（元）*</span>
            <input v-model="renewForm['协议金额']" type="number" min="0" step="0.01" required />
          </label>
          <label>
            <span>签订人员 *</span>
            <input v-model="renewForm['签订人员']" required />
          </label>
          <p v-if="renewError" class="modal-error error-text">{{ renewError }}</p>
          <div class="modal-foot">
            <button class="btn ghost" type="button" :disabled="renewLoading" @click="closeRenew">取消</button>
            <button class="btn primary" type="submit" :disabled="renewLoading">
              {{ renewLoading ? '提交中…' : '确认续签' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/agreement'
const remindDays = 30
const columns = ["协议编号", "服务单位", "保障项目", "协议金额", "服务期限", "签订人员", "到期日期", "到期提醒", "续签次数", "协议状态"]
const actions = ["确认签订", "标记到期", "终止协议"]
const statuses = ["待签订", "履行中", "已到期", "已终止"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const statusFilter = ref('')
const onlyReminding = ref(false)
const stats = ref<{ label: string; value: number | string }[]>([
  { label: '履行中协议', value: 0 },
  { label: '即将到期协议', value: 0 },
  { label: '协议总金额（元）', value: 0 },
])
const filterFields = columns.slice(0, 3)

const renewTarget = ref<Row | null>(null)
const renewForm = ref<Record<string, string>>({})
const renewError = ref('')
const renewLoading = ref(false)

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  onlyReminding.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '保障协议登记入口尚未接入审批流'
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) params.set(key, value)
  }
  if (statusFilter.value) params.set('status', statusFilter.value)
  if (onlyReminding.value) params.set('reminding', 'true')
  params.set('remind_days', String(remindDays))

  try {
    // 列表与统计卡并发取数，到期提醒以后端 /stats 同口径结果为准
    const [listResp, statsResp] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}/stats?remind_days=${remindDays}`),
    ])
    if (!listResp.ok) {
      throw new Error('保障协议列表读取失败')
    }
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResp.ok) {
      const summary = await statsResp.json()
      stats.value[0].value = summary['履行中协议'] ?? 0
      stats.value[1].value = summary['即将到期协议'] ?? 0
      stats.value[2].value = (summary['协议总金额'] ?? 0).toLocaleString()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障协议列表读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (action === '终止协议' && !window.confirm(`确认终止协议 ${row['协议编号']}？终止后不可续签，续签留痕仍会保留。`)) {
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '保障协议动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障协议操作失败'
  }
}

function openRenew(row: Row) {
  renewTarget.value = row
  renewError.value = ''
  renewForm.value = {
    '签订日期': '',
    '到期日期': '',
    '服务期限': '',
    '协议金额': String(row['协议金额'] ?? ''),
    '签订人员': String(row['签订人员'] ?? ''),
  }
}

function closeRenew() {
  if (renewLoading.value) return
  renewTarget.value = null
  renewError.value = ''
}

async function submitRenew() {
  if (!renewTarget.value) return
  renewError.value = ''
  renewLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/${renewTarget.value.id}/renew`, {
      method: 'POST',
      body: JSON.stringify({ values: renewForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '续签未生效，请稍后重试')
    }
    renewTarget.value = null
    await reload()
  } catch (error) {
    renewError.value = error instanceof Error ? error.message : '续签提交失败'
  } finally {
    renewLoading.value = false
  }
}

onMounted(reload)
</script>
