'use client'

import { useEffect, useState, useTransition } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import {
  deleteLicense,
  extendLicense,
  getLicenseDevices,
  kickLicense,
  setLicenseExpiry,
  setLicenseStatus,
  unbindDevice,
  updateLicense,
} from '@/app/actions/licenses'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import type { LicenseRow } from './license-table'
import { formatDateTime, licenseState, relativeTime, toDateTimeLocal } from './license-utils'

export function LicenseManageDialog({ license, onClose }: { license: LicenseRow | null; onClose: () => void }) {
  return (
    <Dialog open={license !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        {license && <ManagePanel key={license.id} license={license} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t pt-4">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  )
}

function ManagePanel({ license, onClose }: { license: LicenseRow; onClose: () => void }) {
  const [pending, startTransition] = useTransition()
  const [expiry, setExpiry] = useState(toDateTimeLocal(license.expiresAt))
  const [note, setNote] = useState(license.note)
  const [maxDevices, setMaxDevices] = useState(String(license.maxDevices))
  const [geminiEnabled, setGeminiEnabled] = useState(license.geminiEnabled)
  const [geminiLimit, setGeminiLimit] = useState(license.geminiDailyLimit ? String(license.geminiDailyLimit) : '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const { data: devices, mutate } = useSWR(['devices', license.id], () => getLicenseDevices(license.id))
  const state = licenseState(license)
  const disabled = license.status === 'disabled'

  useEffect(() => setExpiry(toDateTimeLocal(license.expiresAt)), [license.expiresAt])

  function run(task: () => Promise<unknown>, success: string) {
    startTransition(async () => {
      try {
        await task()
        toast.success(success)
      } catch (error) {
        toast.error(error instanceof Error ? error.message : '操作失败')
      }
    })
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-mono">{license.code}</DialogTitle>
        <DialogDescription>
          {state.label} · 创建于 {formatDateTime(license.createdAt)}
          {license.activatedAt && ` · 激活于 ${formatDateTime(license.activatedAt)}`}
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-wrap gap-2">
        <Button
          variant={disabled ? 'default' : 'destructive'}
          disabled={pending}
          onClick={() =>
            run(() => setLicenseStatus(license.id, disabled ? 'active' : 'disabled'), disabled ? '已启用' : '已停用，用户已被强制下线')
          }
        >
          {disabled ? '恢复使用' : '立即停用'}
        </Button>
        <Button variant="outline" disabled={pending} onClick={() => run(() => kickLicense(license.id), '已踢下线，需重新登录')}>
          踢下线
        </Button>
      </div>

      <Section title="使用时间">
        <div className="flex flex-wrap gap-2">
          {[1, 7, 30, 365].map((d) => (
            <Button key={d} variant="outline" size="sm" disabled={pending} onClick={() => run(() => extendLicense(license.id, d), `已延长 ${d} 天`)}>
              +{d} 天
            </Button>
          ))}
          <Button variant="outline" size="sm" disabled={pending} onClick={() => run(() => extendLicense(license.id, -1), '已减少 1 天')}>
            -1 天
          </Button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="expiry">指定到期时间</Label>
            <Input id="expiry" type="datetime-local" value={expiry} onChange={(e) => setExpiry(e.target.value)} className="w-56" />
          </div>
          <Button
            size="sm"
            disabled={pending || !expiry}
            onClick={() => run(() => setLicenseExpiry(license.id, new Date(expiry).toISOString()), '到期时间已更新')}
          >
            保存
          </Button>
          <Button variant="ghost" size="sm" disabled={pending} onClick={() => run(() => setLicenseExpiry(license.id, null), '已设为永久')}>
            设为永久
          </Button>
        </div>
      </Section>

      <Section title="权限与备注">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="maxDevices-edit">可绑电脑数</Label>
            <Input id="maxDevices-edit" type="number" min={1} max={20} value={maxDevices} onChange={(e) => setMaxDevices(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="geminiLimit-edit">AI 每日次数</Label>
            <Input id="geminiLimit-edit" type="number" min={1} placeholder="不限" value={geminiLimit} onChange={(e) => setGeminiLimit(e.target.value)} />
          </div>
        </div>
        <div className="flex items-center justify-between rounded-lg border p-3">
          <Label htmlFor="gemini-edit">允许 Google AI 抠图</Label>
          <Switch id="gemini-edit" checked={geminiEnabled} onCheckedChange={setGeminiEnabled} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="note-edit">备注</Label>
          <Input id="note-edit" value={note} maxLength={100} onChange={(e) => setNote(e.target.value)} />
        </div>
        <Button
          size="sm"
          className="self-start"
          disabled={pending}
          onClick={() =>
            run(
              () =>
                updateLicense(license.id, {
                  note,
                  maxDevices: Number(maxDevices),
                  geminiEnabled,
                  geminiDailyLimit: geminiLimit ? Number(geminiLimit) : null,
                }),
              '已保存',
            )
          }
        >
          保存修改
        </Button>
      </Section>

      <Section title={`已绑定电脑（${devices?.length ?? license.deviceCount}/${license.maxDevices}）`}>
        {!devices ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : devices.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚未绑定任何电脑</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {devices.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">{d.machineName || '未知电脑'}</span>
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    {d.machineId.slice(0, 16)}… · {d.lastIp || '无 IP'} · {relativeTime(new Date(d.lastSeenAt).toISOString())}
                  </span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pending}
                  onClick={() =>
                    run(async () => {
                      const next = await unbindDevice(license.id, d.id)
                      await mutate(next, { revalidate: false })
                    }, '已解绑')
                  }
                >
                  解绑
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="危险操作">
        {confirmDelete ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-destructive">确定永久删除此卡密及其记录？</span>
            <Button
              variant="destructive"
              size="sm"
              disabled={pending}
              onClick={() =>
                run(async () => {
                  await deleteLicense(license.id)
                  onClose()
                }, '已删除')
              }
            >
              确认删除
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              取消
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" className="self-start text-destructive" onClick={() => setConfirmDelete(true)}>
            删除卡密
          </Button>
        )}
      </Section>
    </>
  )
}
