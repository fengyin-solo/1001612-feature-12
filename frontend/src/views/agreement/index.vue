<template>
  <section class="page" data-module="agreement">
    <header class="page-head">
      <div>
        <h2>保障协议管理</h2>
        <p class="page-desc">维护保障协议，围绕到期提醒、续签留痕与协议终止做登记、筛选与状态流转；到期口径以后端到期日期为准。</p>
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

    <section v-if="reminders.length" class="remind-box">
      <h3 class="remind-title">到期提醒（提前 {{ remindDays }} 天，基准日 {{ today }}）</h3>
      <ul class="remind-list">
        <li v-for="item in reminders" :key="String(item.id)" :class="{ expired: item.协议状态 === '已到期' }">
          <span class="remind-no">{{ item.协议编号 }}</span>
          <span>{{ item.服务单位 }} · {{ item.保障项目 }}</span>
          <span>到期日期：{{ item.到期日期 }}</span>
          <strong>{{ item.到期提醒 }}</strong>
        </li>
      </ul>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>协议编号</span>
        <input v-model="keyword" placeholder="按协议编号检索" />
      </label>
      <label class="filter-item">
        <span>协议状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="st in statuses" :key="st" :value="st">{{ st }}</option>
        </select>
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
            <span v-if="column === '到期提醒' && row[column]" :class="['remind-tag', { expired: row['协议状态'] === '已到期' }]">
              {{ row[column] }}
            </span>
            <span v-else-if="column === '到期提醒'">—</span>
            <span v-else-if="column === '协议金额'">￥{{ formatAmount(row[column]) }}</span>
            <span v-else>{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</span>
          </td>
          <td class="row-actions">
            <button
              v-if="row['协议状态'] === '待签订'"
              class="link"
              type="button"
              @click="runAction('确认签订', row)"
            >
              确认签订
            </button>
            <button
              v-if="row['协议状态'] === '履行中' && row['到期提醒'] === '已到期'"
              class="link"
              type="button"
              @click="runAction('标记到期', row)"
            >
              标记到期
            </button>
            <button
              v-if="row['协议状态'] !== '已终止' && row['协议状态'] !== '待签订'"
              class="link"
              type="button"
              @click="openRenew(row)"
            >
              确认续签
            </button>
            <button
              v-if="row['协议状态'] !== '已终止'"
              class="link danger"
              type="button"
              @click="terminate(row)"
            >
              终止协议
            </button>
            <span v-if="row['协议状态'] === '已终止'" class="muted-text">已终止</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保障协议数据，可先登记保障协议</td>
        </tr>
      </tbody>
    </table>

    <section class="renew-log">
      <h3 class="remind-title">续签留痕（同一协议编号重复续签只保留最新一次）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in renewColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rec in renewals" :key="String(rec.协议编号)">
            <td v-for="column in renewColumns" :key="column">
              <span v-if="column === '原协议金额' || column === '新协议金额'">￥{{ formatAmount(rec[column]) }}</span>
              <span v-else>{{ rec[column] ?? '—' }}</span>
            </td>
          </tr>
          <tr v-if="!renewals.length">
            <td :colspan="renewColumns.length" class="empty-state">暂无续签记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="renewOpen" class="modal-mask" @click.self="closeRenew">
      <div class="modal">
        <h3>确认续签 · {{ renewForm.协议编号 }}</h3>
        <p class="muted-text">
          服务单位：{{ renewForm.服务单位 }} ｜ 保障项目：{{ renewForm.保障项目 }}<br />
          原到期日期 {{ renewForm.到期日期 }} 与保障项目续签后原样保留，列表续签次数会加 1。
        </p>
        <form @submit.prevent="submitRenew">
          <label class="form-item">
            <span>服务单位</span>
            <input v-model="renewForm.服务单位" placeholder="空缺时续签会被拒绝" />
          </label>
          <label class="form-item">
            <span>新服务期限（起始日期）</span>
            <input v-model="renewForm.服务期限" type="date" />
          </label>
          <label class="form-item">
            <span>签订日期</span>
            <input v-model="renewForm.签订日期" type="date" />
            <small class="muted-text">新服务期限早于签订日期时将被拒绝</small>
          </label>
          <label class="form-item">
            <span>协议金额（元）</span>
            <input v-model="renewForm.协议金额" type="number" min="0" step="0.01" />
          </label>
          <label class="form-item">
            <span>签订人员</span>
            <input v-model="renewForm.签订人员" placeholder="本次续签的签订人员" />
          </label>
          <p v-if="renewError" class="error-text">{{ renewError }}</p>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="closeRenew">取消</button>
            <button class="btn primary" type="submit" :disabled="renewSubmitting">
              {{ renewSubmitting ? '提交中…' : '确认续签' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障协议记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Summary = Record<string, string | number>

interface RenewForm {
  id: number | null
  协议编号: string
  服务单位: string
  保障项目: string
  到期日期: string
  服务期限: string
  签订日期: string
  协议金额: string
  签订人员: string
}

const ENDPOINT = '/api/agreement'
const columns = ['协议编号', '服务单位', '保障项目', '协议金额', '服务期限', '签订人员', '到期日期', '协议状态', '到期提醒', '续签次数']
const renewColumns = ['协议编号', '续签次数', '原服务期限', '新服务期限', '原协议金额', '新协议金额', '原签订人员', '新签订人员', '签订日期', '原到期日期', '续签时间']
const statuses = ['待签订', '履行中', '已到期', '已终止']
const stats = ref<{ label: string, value: string | number }[]>([
  { label: '履行中协议', value: 0 },
  { label: '即将到期协议', value: 0 },
  { label: '已到期协议', value: 0 },
  { label: '协议总金额（元）', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const reminders = ref<Row[]>([])
const renewals = ref<Row[]>([])
const remindDays = ref(30)
const today = ref('')

const renewOpen = ref(false)
const renewSubmitting = ref(false)
const renewError = ref('')
const renewForm = reactive<RenewForm>({
  id: null,
  协议编号: '',
  服务单位: '',
  保障项目: '',
  到期日期: '',
  服务期限: '',
  签订日期: '',
  协议金额: '',
  签订人员: '',
})

function formatAmount(value: string | number | null): string {
  const num = Number(value)
  return Number.isFinite(num) ? num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '保障协议登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '保障协议动作未生效，请稍后重试')
    }
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障协议操作失败'
  }
}

async function terminate(row: Row) {
  if (!window.confirm(`确认终止协议 ${String(row.协议编号)}？终止后不能再续签，且不影响已有续签留痕。`)) {
    return
  }
  await runAction('终止协议', row)
}

function openRenew(row: Row) {
  renewError.value = ''
  Object.assign(renewForm, {
    id: Number(row.id),
    协议编号: String(row.协议编号 ?? ''),
    服务单位: String(row.服务单位 ?? ''),
    保障项目: String(row.保障项目 ?? ''),
    到期日期: String(row.到期日期 ?? ''),
    服务期限: '',
    签订日期: today.value,
    协议金额: row.协议金额 == null ? '' : String(row.协议金额),
    签订人员: String(row.签订人员 ?? ''),
  })
  renewOpen.value = true
}

function closeRenew() {
  renewOpen.value = false
  renewError.value = ''
}

async function submitRenew() {
  if (renewForm.id == null) {
    return
  }
  renewSubmitting.value = true
  renewError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${renewForm.id}/renew`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          服务单位: renewForm.服务单位,
          服务期限: renewForm.服务期限,
          签订日期: renewForm.签订日期,
          协议金额: renewForm.协议金额,
          签订人员: renewForm.签订人员,
        },
      }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '续签未生效，请稍后重试')
    }
    renewOpen.value = false
    await refreshAll()
  } catch (error) {
    renewError.value = error instanceof Error ? error.message : '续签失败'
  } finally {
    renewSubmitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  query.set('page', '1')
  query.set('size', '100')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('保障协议列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保障协议列表读取失败'
  }
}

async function loadSummary() {
  const response = await request(`${ENDPOINT}/summary`)
  if (!response.ok) {
    return
  }
  const payload: Summary = await response.json()
  remindDays.value = Number(payload.提醒提前天数 ?? 30)
  today.value = String(payload.统计基准日 ?? '')
  stats.value = [
    { label: '履行中协议', value: Number(payload.履行中协议 ?? 0) },
    { label: '即将到期协议', value: Number(payload.即将到期协议 ?? 0) },
    { label: '已到期协议', value: Number(payload.已到期协议 ?? 0) },
    { label: '协议总金额（元）', value: formatAmount(String(payload.协议总金额 ?? 0)) },
  ]
}

async function loadReminders() {
  const response = await request(`${ENDPOINT}/reminders`)
  if (!response.ok) {
    return
  }
  const payload = await response.json()
  reminders.value = payload.items ?? []
}

async function loadRenewals() {
  const response = await request(`${ENDPOINT}/renewals`)
  if (!response.ok) {
    return
  }
  const payload = await response.json()
  renewals.value = payload.items ?? []
}

async function refreshAll() {
  // 列表、提醒、统计、留痕一起刷新，保证返回列表页后口径仍然对得上
  await Promise.all([reload(), loadSummary(), loadReminders(), loadRenewals()])
}

onMounted(refreshAll)
</script>

<style scoped>
.remind-box,
.renew-log {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.renew-log {
  margin-top: 12px;
}
.remind-title {
  font-size: 14px;
  margin: 0 0 8px;
}
.remind-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.remind-list li {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 13px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 6px 10px;
}
.remind-list li.expired {
  color: #b42318;
  background: #fef3f2;
  border-color: #fecdca;
}
.remind-no {
  font-weight: 600;
}
.remind-tag {
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  white-space: nowrap;
}
.remind-tag.expired {
  color: #b42318;
  background: #fef3f2;
  border-color: #fecdca;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.link.danger {
  color: #b42318;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 460px;
  max-width: calc(100vw - 32px);
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 8px;
  font-size: 16px;
}
.form-item {
  display: block;
  margin-bottom: 10px;
}
.form-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.form-item input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.form-item small {
  display: block;
  margin-top: 2px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>
