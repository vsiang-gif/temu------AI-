'use client'

import { useActionState, useEffect } from 'react'
import { toast } from 'sonner'
import { saveSettings } from '@/app/actions/settings'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { PublicSettings } from '@/lib/settings'

export function SettingsForm({ settings, geminiConfigured }: { settings: PublicSettings; geminiConfigured: boolean }) {
  const [state, action, pending] = useActionState(saveSettings, undefined)

  useEffect(() => {
    if (state?.saved) toast.success('设置已保存')
  }, [state])

  return (
    <form action={action} className="flex flex-col gap-5 rounded-xl border bg-background p-6">
      <h2 className="font-semibold">全局设置</h2>

      <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="loginEnabled">允许软件登录使用</Label>
          <span className="text-xs text-muted-foreground text-pretty">关闭后所有用户立即被踢下线，且无法登录（总开关）</span>
        </div>
        <Switch id="loginEnabled" name="loginEnabled" defaultChecked={settings.loginEnabled} />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="notice">软件公告</Label>
        <Textarea id="notice" name="notice" rows={3} defaultValue={settings.notice} placeholder="显示在软件主界面顶部，可留空" />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="latestVersion">最新版本号</Label>
        <Input id="latestVersion" name="latestVersion" defaultValue={settings.latestVersion} placeholder="如 1.0.0，软件版本低于此会提示更新" />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="geminiModel">Google AI 图像模型</Label>
        <Input id="geminiModel" name="geminiModel" defaultValue={settings.geminiModel} className="font-mono" />
        <p className={geminiConfigured ? 'text-xs text-emerald-700' : 'text-xs text-amber-700'}>
          {geminiConfigured
            ? 'GEMINI_API_KEY 已配置，Google AI 抠图可用'
            : '尚未配置 GEMINI_API_KEY：在右上角设置 → Vars 中添加后即可启用，软件端无需改动'}
        </p>
      </div>

      {state?.error && (
        <p role="alert" className="text-sm text-destructive">
          {state.error}
        </p>
      )}
      <Button type="submit" disabled={pending} className="self-start">
        {pending ? '保存中…' : '保存设置'}
      </Button>
    </form>
  )
}
