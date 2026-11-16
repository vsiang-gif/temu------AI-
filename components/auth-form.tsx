'use client'

import { useActionState } from 'react'
import { KeyRound } from 'lucide-react'
import { login, setupAdmin } from '@/app/actions/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function AuthForm({ mode }: { mode: 'login' | 'setup' }) {
  const [state, action, pending] = useActionState(mode === 'login' ? login : setupAdmin, undefined)
  const isSetup = mode === 'setup'

  return (
    <main className="flex min-h-svh items-center justify-center p-6">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-xl border bg-background p-8 shadow-sm">
        <div className="flex flex-col gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-foreground text-background">
            <KeyRound className="size-5" aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold text-balance">{isSetup ? '创建管理员账号' : '卡密管理后台'}</h1>
            <p className="text-sm text-muted-foreground text-pretty">
              {isSetup ? '首次使用，请设置后台登录账号。只能创建一次。' : 'POD 印花抠图软件 · 授权管理'}
            </p>
          </div>
        </div>

        <form action={action} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="username">用户名</Label>
            <Input id="username" name="username" autoComplete="username" required />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">密码</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete={isSetup ? 'new-password' : 'current-password'}
              required
            />
          </div>
          {isSetup && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="confirm">确认密码</Label>
              <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
            </div>
          )}
          {state?.error && (
            <p role="alert" className="text-sm text-destructive">
              {state.error}
            </p>
          )}
          <Button type="submit" disabled={pending} className="w-full">
            {pending ? '请稍候…' : isSetup ? '创建并登录' : '登录'}
          </Button>
        </form>
      </div>
    </main>
  )
}
