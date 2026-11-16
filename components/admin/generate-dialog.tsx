'use client'

import { useActionState, useState } from 'react'
import { Copy, Download, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { generateLicenses } from '@/app/actions/licenses'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

const durations = [
  { value: '1', label: '1 天' },
  { value: '7', label: '7 天' },
  { value: '30', label: '30 天' },
  { value: '90', label: '90 天' },
  { value: '365', label: '1 年' },
  { value: 'forever', label: '永久' },
]

export function GenerateDialog() {
  const [open, setOpen] = useState(false)
  const [formKey, setFormKey] = useState(0)
  const [state, action, pending] = useActionState(generateLicenses, undefined)
  const [duration, setDuration] = useState('30')
  const codes = state?.codes
  const showResult = Boolean(codes?.length) && formKey === 0

  function reset() {
    setFormKey((k) => k + 1)
  }

  function download() {
    if (!codes) return
    const blob = new Blob([codes.join('\r\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `卡密_${new Date().toISOString().slice(0, 10)}_${codes.length}张.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <Button
        onClick={() => {
          setFormKey(0)
          setOpen(true)
        }}
      >
        <Plus aria-hidden="true" />
        批量生成卡密
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{showResult ? `已生成 ${codes!.length} 张卡密` : '批量生成卡密'}</DialogTitle>
            <DialogDescription>
              {showResult ? '请立即复制或下载保存，可在列表中随时查看。' : '使用天数从第一次登录激活时开始计算。'}
            </DialogDescription>
          </DialogHeader>

          {showResult ? (
            <>
              <Textarea readOnly value={codes!.join('\n')} rows={8} className="font-mono text-xs" aria-label="生成的卡密" />
              <DialogFooter>
                <Button variant="outline" onClick={download}>
                  <Download aria-hidden="true" />
                  下载 TXT
                </Button>
                <Button
                  onClick={async () => {
                    await navigator.clipboard.writeText(codes!.join('\n'))
                    toast.success('已复制全部卡密')
                  }}
                >
                  <Copy aria-hidden="true" />
                  复制全部
                </Button>
              </DialogFooter>
              <Button variant="ghost" size="sm" onClick={reset} className="justify-self-start">
                继续生成
              </Button>
            </>
          ) : (
            <form key={formKey} action={(fd) => { setFormKey(0); action(fd) }} className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="amount">生成数量</Label>
                  <Input id="amount" name="amount" type="number" min={1} max={500} defaultValue={1} required />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="maxDevices">每卡可绑电脑数</Label>
                  <Input id="maxDevices" name="maxDevices" type="number" min={1} max={20} defaultValue={1} required />
                </div>
              </div>

              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 text-sm font-medium">使用时长</legend>
                <div className="flex flex-wrap gap-2">
                  {durations.map((d) => (
                    <button
                      key={d.value}
                      type="button"
                      aria-pressed={duration === d.value}
                      onClick={() => setDuration(d.value)}
                      className={
                        duration === d.value
                          ? 'rounded-md border border-foreground bg-foreground px-3 py-1 text-sm text-background'
                          : 'rounded-md border px-3 py-1 text-sm text-muted-foreground hover:text-foreground'
                      }
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Label htmlFor="durationDays" className="shrink-0 text-muted-foreground">
                    自定义天数
                  </Label>
                  <Input
                    id="durationDays"
                    name="durationDays"
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    className="w-28"
                  />
                </div>
              </fieldset>

              <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
                <div className="flex flex-col gap-0.5">
                  <Label htmlFor="geminiEnabled">允许使用 Google AI 抠图</Label>
                  <span className="text-xs text-muted-foreground">关闭后只能用本地 U2-Net</span>
                </div>
                <Switch id="geminiEnabled" name="geminiEnabled" defaultChecked />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="geminiDailyLimit">AI 每日次数上限</Label>
                  <Input id="geminiDailyLimit" name="geminiDailyLimit" type="number" min={1} placeholder="不限" />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="note">备注</Label>
                  <Input id="note" name="note" placeholder="如：运营小王" maxLength={100} />
                </div>
              </div>

              {state?.error && (
                <p role="alert" className="text-sm text-destructive">
                  {state.error}
                </p>
              )}
              <DialogFooter>
                <Button type="submit" disabled={pending}>
                  {pending ? '生成中…' : '生成'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
