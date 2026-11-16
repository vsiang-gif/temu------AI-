'use client'

import { useState } from 'react'
import { Copy, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LicenseManageDialog } from './license-manage-dialog'
import { formatDateTime, licenseState, relativeTime } from './license-utils'

export type LicenseRow = {
  id: number
  code: string
  note: string
  status: string
  durationDays: number | null
  maxDevices: number
  deviceCount: number
  geminiEnabled: boolean
  geminiDailyLimit: number | null
  activatedAt: string | null
  expiresAt: string | null
  lastSeenAt: string | null
  createdAt: string
}

const stateStyle: Record<string, string> = {
  unused: 'bg-muted text-muted-foreground',
  active: 'bg-emerald-100 text-emerald-800',
  expired: 'bg-amber-100 text-amber-800',
  disabled: 'bg-red-100 text-red-800',
}

export function LicenseTable({ rows }: { rows: LicenseRow[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = rows.find((r) => r.id === selectedId) ?? null

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border bg-background py-16 text-center">
        <p className="font-medium">暂无卡密</p>
        <p className="text-sm text-muted-foreground">点击右上角“批量生成卡密”开始</p>
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-background">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>卡密</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>到期时间</TableHead>
            <TableHead>设备</TableHead>
            <TableHead>Google AI</TableHead>
            <TableHead>最后在线</TableHead>
            <TableHead>备注</TableHead>
            <TableHead className="text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const state = licenseState(row)
            return (
              <TableRow key={row.id}>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-sm">{row.code}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={`复制卡密 ${row.code}`}
                      onClick={async () => {
                        await navigator.clipboard.writeText(row.code)
                        toast.success('已复制')
                      }}
                    >
                      <Copy className="size-3.5" aria-hidden="true" />
                    </Button>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary" className={stateStyle[state.key]}>
                    {state.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.expiresAt
                    ? formatDateTime(row.expiresAt)
                    : row.activatedAt || row.durationDays == null
                      ? '永久'
                      : `激活后 ${row.durationDays} 天`}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.deviceCount}/{row.maxDevices}
                </TableCell>
                <TableCell className="text-sm">
                  {row.geminiEnabled ? (row.geminiDailyLimit ? `${row.geminiDailyLimit} 次/天` : '不限') : '关闭'}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{relativeTime(row.lastSeenAt)}</TableCell>
                <TableCell className="max-w-40 truncate text-sm text-muted-foreground">{row.note || '—'}</TableCell>
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => setSelectedId(row.id)}>
                    <Settings2 aria-hidden="true" />
                    管理
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <LicenseManageDialog license={selected} onClose={() => setSelectedId(null)} />
    </div>
  )
}
