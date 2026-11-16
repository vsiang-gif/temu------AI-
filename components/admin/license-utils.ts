type LicenseLike = { status: string; activatedAt: string | null; expiresAt: string | null }

export function licenseState(row: LicenseLike) {
  if (row.status === 'disabled') return { key: 'disabled', label: '已停用' }
  if (row.expiresAt && new Date(row.expiresAt).getTime() <= Date.now()) return { key: 'expired', label: '已过期' }
  if (!row.activatedAt) return { key: 'unused', label: '未激活' }
  return { key: 'active', label: '使用中' }
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function relativeTime(iso: string | null) {
  if (!iso) return '从未'
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

export function toDateTimeLocal(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
